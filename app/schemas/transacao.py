from datetime import date, datetime
from enum import Enum

from pydantic import Field, model_validator

from app.models.enums import TipoTransacao
from app.schemas.common import InputModel, OutputModel

# Teto de sanidade: 1 trilhão de reais em centavos (cabe folgado em BIGINT).
MAX_CENTAVOS = 100_000_000_000_000


class TransacaoCreate(InputModel):
    conta_id: int
    categoria_id: int | None = None
    tipo: TipoTransacao
    # strict=True: rejeita 10.5 ou "10.50" — só inteiros em centavos.
    valor_centavos: int = Field(gt=0, le=MAX_CENTAVOS, strict=True)
    descricao: str = Field(default="", max_length=255)
    data_competencia: date
    data_lancamento: date | None = None  # default: igual à competência

    @model_validator(mode="after")
    def _default_lancamento(self) -> "TransacaoCreate":
        if self.data_lancamento is None:
            self.data_lancamento = self.data_competencia
        return self


class TransacaoUpdate(InputModel):
    conta_id: int | None = None
    categoria_id: int | None = None
    tipo: TipoTransacao | None = None
    valor_centavos: int | None = Field(default=None, gt=0, le=MAX_CENTAVOS, strict=True)
    descricao: str | None = Field(default=None, max_length=255)
    data_competencia: date | None = None
    data_lancamento: date | None = None


class TransacaoOut(OutputModel):
    id: int
    conta_id: int
    categoria_id: int | None
    tipo: TipoTransacao
    valor_centavos: int
    descricao: str
    data_competencia: date
    data_lancamento: date
    created_at: datetime
    updated_at: datetime


class CampoData(str, Enum):
    competencia = "competencia"
    lancamento = "lancamento"


class TransacaoPage(OutputModel):
    items: list[TransacaoOut]
    total: int
    limit: int
    offset: int
