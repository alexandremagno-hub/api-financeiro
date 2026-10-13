from datetime import datetime

from pydantic import EmailStr, Field

from app.core.security import SENHA_MIN_CARACTERES
from app.models.enums import Role
from app.schemas.common import InputModel, OutputModel


class UsuarioCreate(InputModel):
    email: EmailStr
    nome: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=SENHA_MIN_CARACTERES, max_length=128)
    role: Role = Role.usuario


class UsuarioOut(OutputModel):
    id: int
    email: str
    nome: str
    role: Role
    ativo: bool
    created_at: datetime
