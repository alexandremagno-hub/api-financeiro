from pydantic import EmailStr, Field

from app.core.security import SENHA_MIN_CARACTERES
from app.schemas.common import InputModel, OutputModel


class LoginRequest(InputModel):
    email: EmailStr
    senha: str = Field(min_length=1, max_length=128)


class SignupRequest(InputModel):
    nome: str = Field(min_length=1, max_length=120)
    email: EmailStr
    senha: str = Field(min_length=SENHA_MIN_CARACTERES, max_length=128)
    # Nome do espaço (família, empresa...). Se omitido, usa "Conta de usuário".
    nome_tenant: str | None = Field(default=None, min_length=1, max_length=120)


class AccessTokenResponse(OutputModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
