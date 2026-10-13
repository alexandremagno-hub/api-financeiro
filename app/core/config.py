from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "API Financeiro"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "mysql+pymysql://financeiro:financeiro@localhost:3306/financeiro?charset=utf8mb4"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Chaves simétricas (JWK "oct", 256 bits, base64url) para JWE alg=dir / enc=A256GCM.
    # Chaves distintas para access e refresh: um tipo de token nunca decifra com a chave do outro.
    JWE_ACCESS_KEY: str = Field(..., min_length=43)
    JWE_REFRESH_KEY: str = Field(..., min_length=43)

    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7

    REFRESH_COOKIE_NAME: str = "refresh_token"
    # Caminho que o NAVEGADOR enxerga. O proxy reverso publica a API em /api e
    # remove o prefixo, então o browser chama /api/auth/refresh. Com "/auth" o
    # cookie nunca seria enviado. Se acessar a API sem o proxy, use "/auth".
    REFRESH_COOKIE_PATH: str = "/api/auth"
    # Só desligue em desenvolvimento local sem HTTPS.
    COOKIE_SECURE: bool = True

    # Proteção contra força bruta no login (por e-mail).
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_WINDOW_SECONDS: int = 900

    # Limite de cadastros públicos por IP (anti-spam de tenants).
    SIGNUP_MAX_PER_IP: int = 10
    SIGNUP_WINDOW_SECONDS: int = 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
