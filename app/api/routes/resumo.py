from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import false, func, or_, select

from app.api.deps import TenantDB
from app.api.routes._helpers import filtro_meses
from app.models import Categoria, TipoTransacao, Transacao
from app.schemas.resumo import CategoriaResumo, DestinoResumo, ResumoMesOut
from app.services.destino import destino

router = APIRouter(prefix="/resumo", tags=["resumo"])



@router.get("/meses", response_model=list[str])
def meses(tdb: TenantDB) -> list[str]:
    """Meses (AAAA-MM) que têm lançamentos, do mais recente para o mais antigo."""
    datas = tdb.scalars(select(Transacao.data_competencia).distinct())
    return sorted({d.strftime("%Y-%m") for d in datas}, reverse=True)


@router.get("", response_model=ResumoMesOut)
def resumo(tdb: TenantDB, mes: Annotated[list[str], Query(min_length=1)]) -> ResumoMesOut:
    """Soma os meses pedidos (?mes=2026-01&mes=2026-03); podem ser salteados."""
    meses = sorted(set(mes), reverse=True)
    no_periodo = filtro_meses(Transacao.data_competencia, meses)
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
        .where(no_periodo)
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

    # Destino (gastos) e origem (entradas) saem da descrição, não são coluna: agrupa em Python.
    descricoes = tdb.session.execute(
        select(Transacao.tipo, Transacao.descricao, Transacao.valor_centavos)
        .outerjoin(Categoria, Categoria.id == Transacao.categoria_id)
        .where(
            no_periodo,
            or_(Categoria.fora_do_resumo.is_(None), Categoria.fora_do_resumo == false()),
        )
    ).all()
    por_destino: dict[str, DestinoResumo] = {}
    por_origem: dict[str, DestinoResumo] = {}
    for tipo, descricao, valor in descricoes:
        d = destino(descricao)
        grupo = por_destino if tipo == TipoTransacao.despesa else por_origem
        item = grupo.setdefault(d.chave, DestinoResumo(chave=d.chave, nome=d.nome, total_centavos=0, quantidade=0))
        item.total_centavos += valor
        item.quantidade += 1
    return ResumoMesOut(
        meses=meses,
        total_despesas_centavos=despesas,
        total_receitas_centavos=receitas,
        saldo_centavos=receitas - despesas,
        fora_do_resumo_centavos=fora,
        despesas_por_categoria=por_categoria,
        despesas_por_destino=sorted(por_destino.values(), key=lambda d: d.total_centavos, reverse=True),
        receitas_por_origem=sorted(por_origem.values(), key=lambda d: d.total_centavos, reverse=True),
        quantidade_transacoes=quantidade,
    )
