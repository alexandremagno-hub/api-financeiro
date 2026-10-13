from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.redis import get_redis
from app.core import token_store
from app.core.security import InvalidTokenError, TokenClaims, decode_token
from app.db.session import get_db
from app.models import Role, Tenant, Usuario

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Não autenticado",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_access_claims(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> TokenClaims:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        claims = decode_token(creds.credentials, "access")
    except InvalidTokenError:
        raise _UNAUTHORIZED from None
    if token_store.is_access_denied(redis, claims.jti):
        raise _UNAUTHORIZED
    return claims


def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_access_claims)],
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    # Consulta sem escopo de tenant (ainda não sabemos o tenant), mas casando
    # id + tenant do token. Usuário/tenant desativado perde acesso imediatamente.
    row = db.execute(
        select(Usuario, Tenant.ativo)
        .join(Tenant, Tenant.id == Usuario.tenant_id)
        .where(Usuario.id == claims.sub, Usuario.tenant_id == claims.tid)
    ).first()
    if row is None:
        raise _UNAUTHORIZED
    user, tenant_ativo = row
    if not user.ativo or not tenant_ativo:
        raise _UNAUTHORIZED
    return user


def require_admin(user: Annotated[Usuario, Depends(get_current_user)]) -> Usuario:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requer perfil admin")
    return user


CurrentUser = Annotated[Usuario, Depends(get_current_user)]
AdminUser = Annotated[Usuario, Depends(require_admin)]
