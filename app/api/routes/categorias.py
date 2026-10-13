from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import TenantDB
from app.api.routes._helpers import apply_updates, commit_or_409, get_or_404
from app.db.tenant import TenantSession
from app.models import Categoria
from app.schemas.categoria import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(prefix="/categorias", tags=["categorias"])

_DUPLICADA = "Já existe uma categoria com esse nome nesse nível"


def descendentes(tdb: TenantSession, categoria_id: int) -> set[int]:
    """IDs da categoria e de todas as subcategorias (do tenant atual)."""
    filhos: dict[int | None, list[int]] = {}
    for cid, pai in tdb.session.execute(select(Categoria.id, Categoria.categoria_pai_id)):
        filhos.setdefault(pai, []).append(cid)
    resultado, pilha = set(), [categoria_id]
    while pilha:
        atual = pilha.pop()
        if atual not in resultado:
            resultado.add(atual)
            pilha.extend(filhos.get(atual, []))
    return resultado


def _validar_pai(tdb: TenantSession, pai_id: int | None, categoria_id: int | None = None) -> None:
    if pai_id is None:
        return
    # get() é filtrado por tenant: pai de outro tenant = "não encontrada".
    if tdb.get(Categoria, pai_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Categoria pai não encontrada")
    if categoria_id is not None and pai_id in descendentes(tdb, categoria_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Hierarquia cíclica")


@router.get("", response_model=list[CategoriaOut])
def listar(tdb: TenantDB) -> list[Categoria]:
    return list(tdb.scalars(select(Categoria).order_by(Categoria.nome)))


@router.post("", response_model=CategoriaOut, status_code=status.HTTP_201_CREATED)
def criar(body: CategoriaCreate, tdb: TenantDB) -> Categoria:
    _validar_pai(tdb, body.categoria_pai_id)
    categoria = tdb.add(Categoria(**body.model_dump()))
    commit_or_409(tdb, _DUPLICADA)
    return categoria


@router.get("/{categoria_id}", response_model=CategoriaOut)
def obter(categoria_id: int, tdb: TenantDB) -> Categoria:
    return get_or_404(tdb, Categoria, categoria_id, "Categoria")


@router.patch("/{categoria_id}", response_model=CategoriaOut)
def atualizar(categoria_id: int, body: CategoriaUpdate, tdb: TenantDB) -> Categoria:
    categoria = get_or_404(tdb, Categoria, categoria_id, "Categoria")
    data = body.model_dump(exclude_unset=True)
    if "categoria_pai_id" in data:
        _validar_pai(tdb, data["categoria_pai_id"], categoria_id)
    apply_updates(categoria, data)
    commit_or_409(tdb, _DUPLICADA)
    return categoria


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(categoria_id: int, tdb: TenantDB) -> Response:
    tdb.delete(get_or_404(tdb, Categoria, categoria_id, "Categoria"))
    commit_or_409(tdb, "Categoria possui subcategorias ou transações")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
