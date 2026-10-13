from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.db.session import get_db
from app.db.tenant import TenantSession
from app.models import Usuario


def get_tenant_db(
    user: Annotated[Usuario, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Iterator[TenantSession]:
    """Única porta de entrada para dados de domínio nas rotas.

    O tenant vem SEMPRE do usuário autenticado (nunca de path, query ou body).
    A partir daqui, toda consulta na sessão é filtrada por tenant_id.
    """
    tdb = TenantSession(db, user.tenant_id)
    try:
        yield tdb
    finally:
        db.info.pop("tenant_id", None)


TenantDB = Annotated[TenantSession, Depends(get_tenant_db)]
