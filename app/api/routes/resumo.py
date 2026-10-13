import calendar
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import TenantDB
from app.models import Categoria, TipoTransacao, Transacao
from app.schemas.resumo import CategoriaResumo, ResumoMesOut

router = APIRouter(prefix="/resumo", tags=["resumo"])


def _intervalo(mes: str) -> tuple[date, date]:
    try:
        ano, m = (int(p) for p in mes.split("-"))
        return date(ano, m, 1), date(ano, m, calendar.monthrange(ano, m)[1])
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "mes deve ser AAAA-MM") from None


@router.get("/meses", response_model=list[str])
def meses(tdb: TenantDB) -> list[str]:
    """Meses (AAAA-MM) que têm lançamentos, do mais recente para o mais antigo."""
    datas = tdb.scalars(select(Transacao.data_competencia).distinct())
    return sorted({d.strftime("%Y-%m") for d in datas}, reverse=True)


@router.get("", response_model=ResumoMesOut)
def resumo(tdb: TenantDB, mes: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]) -> ResumoMesOut:
    inicio, fim = _intervalo(mes)
    # Sem filtro de tenant explícito: a sessão aplica em Transacao e Categoria.
    linhas = tdb.session.execute(
        select(
            Transacao.categoria_id,
            Categoria.nome,
            Categoria.fora_do_resumo,
            Transacao.tipo,
            func.sum(Transacao.valor_centavos),
            func.count(),
        )
        .outerjoin(Categoria, Categoria.id == Transacao.categoria_id)
        .where(Transacao.data_competencia >= inicio, Transacao.data_competencia <= fim)
        .group_by(Transacao.categoria_id, Categoria.nome, Categoria.fora_do_resumo, Transacao.tipo)
    ).all()

    despesas = receitas = fora = quantidade = 0
    por_categoria: list[CategoriaResumo] = []
    for categoria_id, nome, fora_do_resumo, tipo, total, qtd in linhas:
        total = int(total)
        quantidade += qtd
        if fora_do_resumo:
            fora += total
        elif tipo == TipoTransacao.despesa:
            despesas += total
            por_categoria.append(
                CategoriaResumo(
                    categoria_id=categoria_id, nome=nome or "Sem categoria", total_centavos=total, quantidade=qtd
                )
            )
        else:
            receitas += total

    por_categoria.sort(key=lambda c: c.total_centavos, reverse=True)
    return ResumoMesOut(
        mes=mes,
        total_despesas_centavos=despesas,
        total_receitas_centavos=receitas,
        saldo_centavos=receitas - despesas,
        fora_do_resumo_centavos=fora,
        despesas_por_categoria=por_categoria,
        quantidade_transacoes=quantidade,
    )
