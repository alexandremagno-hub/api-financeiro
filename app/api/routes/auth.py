import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_redis
from app.core import token_store
from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models import Role, Tenant, Usuario
from app.schemas.auth import AccessTokenResponse, LoginRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_INVALID_CREDENTIALS = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")
_INVALID_REFRESH = HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="strict",
    )


def _issue_tokens(response: Response, redis: Redis, user: Usuario, family: str) -> AccessTokenResponse:
    access, _ = create_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role.value, token_type="access"
    )
    refresh, refresh_claims = create_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        token_type="refresh",
        family=family,
    )
    token_store.store_refresh(redis, refresh_claims)
    _set_refresh_cookie(response, refresh)
    response.headers["Cache-Control"] = "no-store"
    return AccessTokenResponse(
        access_token=access, expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60
    )


def _load_active_user(db: Session, **filters: object) -> Usuario | None:
    stmt = select(Usuario).join(Tenant, Tenant.id == Usuario.tenant_id).where(
        Usuario.ativo.is_(True), Tenant.ativo.is_(True)
    )
    for col, value in filters.items():
        stmt = stmt.where(getattr(Usuario, col) == value)
    return db.scalars(stmt).first()


@router.post("/signup", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AccessTokenResponse:
    """Cadastro público: cria um tenant novo com o usuário como admin e já faz login.

    Ninguém entra no tenant de outra pessoa por aqui; usuários adicionais de um
    tenant são criados pelo admin em POST /usuarios.
    """
    ip = request.client.host if request.client else "desconhecido"
    if token_store.signup_limit_exceeded(redis, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Muitos cadastros. Tente novamente mais tarde."
        )
    email = body.email.lower()
    if db.scalar(select(Usuario.id).where(Usuario.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")

    tenant = Tenant(nome=body.nome_tenant or "Conta de usuário")
    db.add(tenant)
    db.flush()
    user = Usuario(
        tenant_id=tenant.id,
        email=email,
        nome=body.nome,
        senha_hash=hash_password(body.senha),
        role=Role.admin,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Corrida: outro cadastro com o mesmo e-mail entrou entre a checagem e o commit.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado") from None
    return _issue_tokens(response, redis, user, family=uuid.uuid4().hex)


@router.post("/login", response_model=AccessTokenResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AccessTokenResponse:
    email = body.email.lower()
    if token_store.login_attempts_exceeded(redis, email):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Tente novamente mais tarde."
        )
    user = _load_active_user(db, email=email)
    # verify_password roda mesmo sem usuário (hash dummy) para não vazar existência por timing.
    if not verify_password(body.senha, user.senha_hash if user else None) or user is None:
        token_store.register_failed_login(redis, email)
        raise _INVALID_CREDENTIALS
    token_store.reset_login_attempts(redis, email)
    return _issue_tokens(response, redis, user, family=uuid.uuid4().hex)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
) -> AccessTokenResponse:
    if not refresh_token:
        raise _INVALID_REFRESH
    try:
        claims = decode_token(refresh_token, "refresh")
    except InvalidTokenError:
        raise _INVALID_REFRESH from None

    if not token_store.consume_refresh(redis, claims):
        # Token válido criptograficamente, mas já usado ou revogado: provável roubo.
        # Revoga a família inteira (derruba também o token que o atacante rotacionou).
        token_store.revoke_family(redis, claims.fam)
        raise _INVALID_REFRESH

    user = _load_active_user(db, id=claims.sub, tenant_id=claims.tid)
    if user is None:
        token_store.revoke_family(redis, claims.fam)
        raise _INVALID_REFRESH
    return _issue_tokens(response, redis, user, family=claims.fam or uuid.uuid4().hex)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    redis: Annotated[Redis, Depends(get_redis)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)] = None,
) -> Response:
    """Idempotente: sempre limpa o cookie, revoga o que for possível."""
    if refresh_token:
        try:
            claims = decode_token(refresh_token, "refresh")
            redis.delete(f"refresh:{claims.jti}")
            token_store.revoke_family(redis, claims.fam)
        except InvalidTokenError:
            pass
    if creds is not None:
        try:
            token_store.deny_access_token(redis, decode_token(creds.credentials, "access"))
        except InvalidTokenError:
            pass
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(response)
    return response
