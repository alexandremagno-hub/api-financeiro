from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.db.tenant import TenantSession

M = TypeVar("M")


def get_or_404(tdb: TenantSession, model: type[M], id_: int, nome: str) -> M:
    # Registro de outro tenant é indistinguível de inexistente: sempre 404.
    obj = tdb.get(model, id_)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{nome} não encontrada")
    return obj


def commit_or_409(tdb: TenantSession, detail: str) -> None:
    try:
        tdb.commit()
    except IntegrityError:
        tdb.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from None


def apply_updates(obj: Any, data: dict[str, Any]) -> None:
    for field, value in data.items():
        setattr(obj, field, value)
