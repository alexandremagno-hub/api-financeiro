from app.core.config import get_settings
from app.models import Role
from tests.conftest import SENHA, login

settings = get_settings()


def _refresh_cookie(response) -> str:
    raw = response.headers["set-cookie"]
    assert raw.startswith(f"{settings.REFRESH_COOKIE_NAME}=")
    return raw


def test_login_devolve_access_no_corpo_e_refresh_em_cookie_seguro(client, make_user):
    make_user("admin@x.com")
    r = client.post("/auth/login", json={"email": "admin@x.com", "senha": SENHA})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    # JWE compact serialization: 5 partes (header.key.iv.ciphertext.tag)
    assert len(body["access_token"].split(".")) == 5
    assert "refresh_token" not in body

    cookie = _refresh_cookie(r).lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/auth" in cookie
    assert f"max-age={7 * 86400}" in cookie
    assert r.headers["cache-control"] == "no-store"


def test_credenciais_invalidas_e_rate_limit(client, make_user):
    make_user("admin@x.com")
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        r = client.post("/auth/login", json={"email": "admin@x.com", "senha": "errada"})
        assert r.status_code == 401
    # mesmo com a senha certa, bloqueado até a janela expirar
    r = client.post("/auth/login", json={"email": "admin@x.com", "senha": SENHA})
    assert r.status_code == 429
    # usuário inexistente recebe a mesma resposta genérica
    r = client.post("/auth/login", json={"email": "ninguem@x.com", "senha": SENHA})
    assert r.status_code == 401 and r.json()["detail"] == "Credenciais inválidas"


def test_rotas_protegidas_exigem_access_token(client, make_user):
    assert client.get("/transacoes").status_code == 401
    assert client.get("/transacoes", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_refresh_rotaciona_e_reuso_revoga_familia(client, make_user):
    make_user("admin@x.com")
    login(client, "admin@x.com")
    antigo = client.cookies.get(settings.REFRESH_COOKIE_NAME)

    r = client.post("/auth/refresh")
    assert r.status_code == 200
    novo = client.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert novo and novo != antigo
    assert client.get("/usuarios/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200

    # Atacante reutiliza o refresh antigo (roubado): rejeitado...
    client.cookies.clear()
    client.cookies.set(settings.REFRESH_COOKIE_NAME, antigo)
    assert client.post("/auth/refresh").status_code == 401

    # ...e a família toda é revogada: o token legítimo mais novo também cai.
    client.cookies.clear()
    client.cookies.set(settings.REFRESH_COOKIE_NAME, novo)
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_token_nao_serve_como_access_e_vice_versa(client, make_user):
    make_user("admin@x.com")
    headers = login(client, "admin@x.com")
    refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert client.get("/usuarios/me", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401

    client.cookies.clear()
    client.cookies.set(settings.REFRESH_COOKIE_NAME, headers["Authorization"].split()[1])
    assert client.post("/auth/refresh").status_code == 401


def test_logout_revoga_refresh_e_access(client, make_user):
    make_user("admin@x.com")
    headers = login(client, "admin@x.com")
    refresh = client.cookies.get(settings.REFRESH_COOKIE_NAME)

    r = client.post("/auth/logout", headers=headers)
    assert r.status_code == 204
    assert 'refresh_token=""' in r.headers["set-cookie"] or "max-age=0" in r.headers["set-cookie"].lower()

    assert client.get("/usuarios/me", headers=headers).status_code == 401
    client.cookies.set(settings.REFRESH_COOKIE_NAME, refresh)
    assert client.post("/auth/refresh").status_code == 401


def test_usuario_desativado_perde_acesso(client, make_user, session_factory):
    from app.models import Usuario

    _, user_id, _ = make_user("admin@x.com")
    headers = login(client, "admin@x.com")
    with session_factory() as db:
        db.get(Usuario, user_id).ativo = False
        db.commit()
    assert client.get("/usuarios/me", headers=headers).status_code == 401
    assert client.post("/auth/refresh").status_code == 401


def test_somente_admin_cria_usuario_no_proprio_tenant(client, make_user):
    tenant_id, _, _ = make_user("admin@x.com")
    make_user("comum@x.com", role=Role.usuario, tenant_id=tenant_id)
    novo = {"email": "Novo@X.com", "nome": "Novo", "senha": "outra-senha-forte-1"}

    comum = login(client, "comum@x.com")
    assert client.post("/usuarios", json=novo, headers=comum).status_code == 403

    admin = login(client, "admin@x.com")
    r = client.post("/usuarios", json=novo, headers=admin)
    assert r.status_code == 201
    assert r.json()["email"] == "novo@x.com" and r.json()["role"] == "usuario"
    # não é possível escolher o tenant do novo usuário
    r = client.post("/usuarios", json={**novo, "email": "y@x.com", "tenant_id": 999}, headers=admin)
    assert r.status_code == 422
    # e-mail é único globalmente
    assert client.post("/usuarios", json=novo, headers=admin).status_code == 409

    # o novo usuário entra no tenant do admin
    h = login(client, "novo@x.com", "outra-senha-forte-1")
    emails = {u["email"] for u in client.get("/usuarios", headers=admin).json()}
    assert emails == {"admin@x.com", "comum@x.com", "novo@x.com"}
    assert client.get("/usuarios/me", headers=h).status_code == 200


def test_admin_nao_lista_usuarios_de_outro_tenant(client, make_user):
    make_user("a@a.com")
    make_user("b@b.com")
    emails = {u["email"] for u in client.get("/usuarios", headers=login(client, "a@a.com")).json()}
    assert emails == {"a@a.com"}


def test_criar_usuario_exige_login(client):
    r = client.post("/usuarios", json={"email": "x@x.com", "nome": "x", "senha": "123456789012"})
    assert r.status_code == 401


SIGNUP = {"nome": "Maria", "email": "Maria@Exemplo.com", "senha": "senha-da-maria-123"}


def test_signup_cria_tenant_com_admin_e_ja_loga(client):
    r = client.post("/auth/signup", json={**SIGNUP, "nome_tenant": "Família Souza"})
    assert r.status_code == 201, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert "httponly" in _refresh_cookie(r).lower()

    me = client.get("/usuarios/me", headers=headers).json()
    assert me["email"] == "maria@exemplo.com" and me["role"] == "admin"
    # o cookie de refresh emitido no cadastro funciona
    assert client.post("/auth/refresh").status_code == 200
    # e o login normal também
    login(client, "maria@exemplo.com", SIGNUP["senha"])


def test_signups_diferentes_ficam_em_tenants_isolados(client):
    h1 = {"Authorization": "Bearer " + client.post("/auth/signup", json=SIGNUP).json()["access_token"]}
    h2 = {
        "Authorization": "Bearer "
        + client.post("/auth/signup", json={**SIGNUP, "email": "joao@exemplo.com"}).json()["access_token"]
    }
    conta = client.post("/contas", json={"nome": "Carteira", "tipo": "carteira"}, headers=h1).json()
    assert client.get(f"/contas/{conta['id']}", headers=h2).status_code == 404
    assert client.get("/contas", headers=h2).json() == []
    assert {u["email"] for u in client.get("/usuarios", headers=h2).json()} == {"joao@exemplo.com"}


def test_signup_rejeita_email_repetido_e_campos_extras(client, make_user):
    make_user("maria@exemplo.com")
    assert client.post("/auth/signup", json=SIGNUP).status_code == 409
    r = client.post("/auth/signup", json={**SIGNUP, "email": "z@z.com", "role": "admin"})
    assert r.status_code == 422
    r = client.post("/auth/signup", json={**SIGNUP, "email": "z@z.com", "tenant_id": 1})
    assert r.status_code == 422
    r = client.post("/auth/signup", json={**SIGNUP, "email": "z@z.com", "senha": "12345"})
    assert r.status_code == 422


def test_senha_com_6_caracteres_e_aceita(client):
    r = client.post("/auth/signup", json={**SIGNUP, "senha": "123456"})
    assert r.status_code == 201
    login(client, "maria@exemplo.com", "123456")


def test_signup_tem_limite_por_ip(client):
    for i in range(settings.SIGNUP_MAX_PER_IP):
        r = client.post("/auth/signup", json={**SIGNUP, "email": f"u{i}@exemplo.com"})
        assert r.status_code == 201
    r = client.post("/auth/signup", json={**SIGNUP, "email": "mais-um@exemplo.com"})
    assert r.status_code == 429
