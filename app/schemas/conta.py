from pydantic import Field

from app.models.enums import TipoConta
from app.schemas.common import InputModel, OutputModel


class ContaCreate(InputModel):
    nome: str = Field(min_length=1, max_length=120)
    tipo: TipoConta
    saldo_inicial_centavos: int = 0


class ContaUpdate(InputModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    tipo: TipoConta | None = None
    saldo_inicial_centavos: int | None = None
    ativa: bool | None = None


class ContaOut(OutputModel):
    id: int
    nome: str
    tipo: TipoConta
    saldo_inicial_centavos: int
    ativa: bool
