import os

# Configuração precisa existir antes de importar a app. Variáveis de ambiente
# têm precedência sobre o .env, então os testes não dependem do .env local.
os.environ.update(
    ENVIRONMENT="test",
    JWE_ACCESS_KEY="dGVzdC1hY2Nlc3Mta2V5LTMyLWJ5dGVzLWxvbmctISE",
    JWE_REFRESH_KEY="dGVzdC1yZWZyZXNoLWtleS0zMi1ieXRlcy1sb25nISE",
    DATABASE_URL="sqlite://",
    REDIS_URL="redis://localhost:6379/15",
    ACCESS_TOKEN_TTL_MINUTES="15",
    REFRESH_TOKEN_TTL_DAYS="7",
    COOKIE_SECURE="true",
    # Os testes chamam a API direto (sem o proxy que adiciona /api).
    REFRESH_COOKIE_PATH="/auth",
    LOGIN_MAX_ATTEMPTS="5",
    LOGIN_WINDOW_SECONDS="900",
    SIGNUP_MAX_PER_IP="10",
    SIGNUP_WINDOW_SECONDS="3600",
)

from collections.abc import Callable, Iterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, Tenant, Usuario  # noqa: E402

SENHA = "senha-super-secreta-123"


@pytest.fixture
def engine():
    # Padrão: SQLite em memória (rápido, sem dependências).
    # TEST_DATABASE_URL=mysql+pymysql://... roda a mesma suíte contra MySQL real
    # (use um banco descartável: as tabelas são recriadas a cada teste).
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    if url:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def client(session_factory, redis) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_redis] = lambda: redis
    # https: o cookie de refresh é Secure e só é reenviado em conexões seguras.
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@dataclass
class TenantCtx:
    tenant_id: int
    user_id: int
    email: str
    headers: dict[str, str]


@pytest.fixture
def make_user(session_factory) -> Callable[..., tuple[int, int, str]]:
    def _make(email: str, role: Role = Role.admin, tenant_id: int | None = None) -> tuple[int, int, str]:
        with session_factory() as db:
            if tenant_id is None:
                tenant = Tenant(nome=f"Tenant de {email}")
                db.add(tenant)
                db.flush()
                tenant_id = tenant.id
            user = Usuario(
                tenant_id=tenant_id,
                email=email,
                nome=email.split("@")[0],
                senha_hash=hash_password(SENHA),
                role=role,
            )
            db.add(user)
            db.commit()
            return tenant_id, user.id, email

    return _make


def login(client: TestClient, email: str, senha: str = SENHA) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def tenant_factory(client, make_user) -> Callable[[str], TenantCtx]:
    def _factory(email: str) -> TenantCtx:
        tenant_id, user_id, email = make_user(email)
        # Cada tenant tem seu próprio "navegador": cookies não vazam entre eles.
        client.cookies.clear()
        return TenantCtx(tenant_id, user_id, email, login(client, email))

    return _factory
