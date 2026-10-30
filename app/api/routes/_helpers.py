import calendar
from datetime import date
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_
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


def intervalo_mes(mes: str) -> tuple[date, date]:
    """"AAAA-MM" -> primeiro e último dia do mês (422 se inválido)."""
    try:
        ano, m = (int(p) for p in mes.split("-"))
        return date(ano, m, 1), date(ano, m, calendar.monthrange(ano, m)[1])
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mes deve ser AAAA-MM") from None


def filtro_meses(coluna: Any, meses: list[str]) -> ColumnElement[bool]:
    """Datas de `coluna` em qualquer um dos meses (podem ser salteados)."""
    intervalos = [intervalo_mes(m) for m in meses]
    return or_(*(and_(coluna >= inicio, coluna <= fim) for inicio, fim in intervalos))
