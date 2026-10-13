from fastapi import FastAPI

from app.api.routes import auth, categorias, contas, importacoes, resumo, transacoes, usuarios
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    # Sem docs públicas em produção.
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(contas.router)
app.include_router(categorias.router)
app.include_router(transacoes.router)
app.include_router(importacoes.router)
app.include_router(resumo.router)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok"}
