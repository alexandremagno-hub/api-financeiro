from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.deps import TenantDB
from app.api.routes._helpers import apply_updates, commit_or_409, get_or_404
from app.models import Conta
from app.schemas.conta import ContaCreate, ContaOut, ContaUpdate

router = APIRouter(prefix="/contas", tags=["contas"])


@router.get("", response_model=list[ContaOut])
def listar(tdb: TenantDB) -> list[Conta]:
    return list(tdb.scalars(select(Conta).order_by(Conta.nome)))


@router.post("", response_model=ContaOut, status_code=status.HTTP_201_CREATED)
def criar(body: ContaCreate, tdb: TenantDB) -> Conta:
    conta = tdb.add(Conta(**body.model_dump()))
    commit_or_409(tdb, "Já existe uma conta com esse nome")
    return conta


@router.get("/{conta_id}", response_model=ContaOut)
def obter(conta_id: int, tdb: TenantDB) -> Conta:
    return get_or_404(tdb, Conta, conta_id, "Conta")


@router.patch("/{conta_id}", response_model=ContaOut)
def atualizar(conta_id: int, body: ContaUpdate, tdb: TenantDB) -> Conta:
    conta = get_or_404(tdb, Conta, conta_id, "Conta")
    apply_updates(conta, body.model_dump(exclude_unset=True))
    commit_or_409(tdb, "Já existe uma conta com esse nome")
    return conta


@router.delete("/{conta_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(conta_id: int, tdb: TenantDB) -> Response:
    tdb.delete(get_or_404(tdb, Conta, conta_id, "Conta"))
    commit_or_409(tdb, "Conta possui transações; desative-a em vez de remover")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
