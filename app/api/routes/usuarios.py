from fastapi import APIRouter, HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, CurrentUser, TenantDB
from app.core.security import hash_password
from app.models import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioOut

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _email_em_uso(session: Session, email: str) -> bool:
    # E-mail é único globalmente, então a checagem precisa enxergar todos os
    # tenants. Apenas um booleano sai daqui; nenhum dado de outro tenant é lido.
    return bool(
        session.scalar(
            select(exists().where(Usuario.email == email)),
            execution_options={"skip_tenant_filter": True},
        )
    )


@router.post("", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def criar_usuario(body: UsuarioCreate, admin: AdminUser, tdb: TenantDB) -> Usuario:
    """Só admin adiciona usuários, sempre no próprio tenant (o tenant vem do token)."""
    email = body.email.lower()
    if _email_em_uso(tdb.session, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    user = tdb.add(
        Usuario(email=email, nome=body.nome, senha_hash=hash_password(body.senha), role=body.role)
    )
    tdb.commit()
    tdb.refresh(user)
    return user


@router.get("", response_model=list[UsuarioOut])
def listar_usuarios(admin: AdminUser, tdb: TenantDB) -> list[Usuario]:
    return list(tdb.scalars(select(Usuario).order_by(Usuario.nome)))


@router.get("/me", response_model=UsuarioOut)
def me(user: CurrentUser) -> Usuario:
    return user
