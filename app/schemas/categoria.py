from pydantic import Field

from app.schemas.common import InputModel, OutputModel


class CategoriaCreate(InputModel):
    nome: str = Field(min_length=1, max_length=120)
    categoria_pai_id: int | None = None


class CategoriaUpdate(InputModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    categoria_pai_id: int | None = None


class CategoriaOut(OutputModel):
    id: int
    nome: str
    categoria_pai_id: int | None
    fora_do_resumo: bool
