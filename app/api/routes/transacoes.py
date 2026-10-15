from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import TenantDB
from app.api.routes._helpers import apply_updates, commit_or_409, get_or_404
from app.api.routes.categorias import descendentes
from app.db.tenant import TenantSession
from app.models import Categoria, Conta, TipoTransacao, Transacao
from app.schemas.transacao import (
    CampoData,
    TransacaoCreate,
    TransacaoOut,
    TransacaoPage,
    TransacaoUpdate,
)
from app.services.destino import destino as extrair_destino

router = APIRouter(prefix="/transacoes", tags=["transacoes"])


def _validar_referencias(tdb: TenantSession, conta_id: int | None, categoria_id: int | None) -> None:
    """Garante que conta/categoria referenciadas pertencem ao tenant.

    Sem isso, um usuário poderia criar uma transação no próprio tenant apontando
    para a conta de outro tenant (a FK simples não impede).
    """
    if conta_id is not None and tdb.get(Conta, conta_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Conta não encontrada")
    if categoria_id is not None and tdb.get(Categoria, categoria_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Categoria não encontrada")


@router.get("", response_model=TransacaoPage)
def listar(
    tdb: TenantDB,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    campo_data: CampoData = CampoData.competencia,
    conta_id: int | None = None,
    categoria_id: int | None = None,
    incluir_subcategorias: bool = True,
    tipo: TipoTransacao | None = None,
    destino: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransacaoPage:
    if data_inicio and data_fim and data_inicio > data_fim:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "data_inicio > data_fim")

    coluna = (
        Transacao.data_competencia
        if campo_data == CampoData.competencia
        else Transacao.data_lancamento
    )
    # Note: nenhum filtro de tenant aqui — ele é aplicado pela sessão.
    stmt = select(Transacao)
    if data_inicio:
        stmt = stmt.where(coluna >= data_inicio)
    if data_fim:
        stmt = stmt.where(coluna <= data_fim)
    if conta_id is not None:
        stmt = stmt.where(Transacao.conta_id == conta_id)
    if categoria_id is not None:
        ids = descendentes(tdb, categoria_id) if incluir_subcategorias else {categoria_id}
        stmt = stmt.where(Transacao.categoria_id.in_(ids))
    if tipo is not None:
        stmt = stmt.where(Transacao.tipo == tipo)

    ordem = (coluna.desc(), Transacao.id.desc())
    if destino is not None:
        # Chave de /resumo (despesas_por_destino); vem da descrição, então filtra em Python.
        todos = [t for t in tdb.scalars(stmt.order_by(*ordem)) if extrair_destino(t.descricao).chave == destino]
        total, items = len(todos), todos[offset : offset + limit]
    else:
        total = tdb.count(stmt)
        items = tdb.scalars(stmt.order_by(*ordem).limit(limit).offset(offset))
    return TransacaoPage(
        items=[TransacaoOut.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TransacaoOut, status_code=status.HTTP_201_CREATED)
def criar(body: TransacaoCreate, tdb: TenantDB) -> Transacao:
    _validar_referencias(tdb, body.conta_id, body.categoria_id)
    transacao = tdb.add(Transacao(**body.model_dump()))
    commit_or_409(tdb, "Não foi possível criar a transação")
    tdb.refresh(transacao)
    return transacao


@router.get("/{transacao_id}", response_model=TransacaoOut)
def obter(transacao_id: int, tdb: TenantDB) -> Transacao:
    return get_or_404(tdb, Transacao, transacao_id, "Transação")


@router.patch("/{transacao_id}", response_model=TransacaoOut)
def atualizar(transacao_id: int, body: TransacaoUpdate, tdb: TenantDB) -> Transacao:
    transacao = get_or_404(tdb, Transacao, transacao_id, "Transação")
    data = body.model_dump(exclude_unset=True)
    for obrigatorio in ("conta_id", "tipo", "valor_centavos", "data_competencia", "data_lancamento", "descricao"):
        if obrigatorio in data and data[obrigatorio] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{obrigatorio} não pode ser nulo")
    _validar_referencias(tdb, data.get("conta_id"), data.get("categoria_id"))
    apply_updates(transacao, data)
    commit_or_409(tdb, "Não foi possível atualizar a transação")
    tdb.refresh(transacao)
    return transacao


@router.delete("/{transacao_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(transacao_id: int, tdb: TenantDB) -> Response:
    tdb.delete(get_or_404(tdb, Transacao, transacao_id, "Transação"))
    tdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
