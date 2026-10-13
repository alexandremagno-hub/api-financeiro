"""Isolamento entre tenants: A nunca enxerga nem altera dados de B."""

from sqlalchemy import select

from app.db.tenant import TenantSession, TenantViolationError
from app.models import Conta, TipoConta, Transacao


def _seed(client, headers) -> dict[str, int]:
    conta = client.post("/contas", json={"nome": "Nubank", "tipo": "cartao_credito"}, headers=headers)
    assert conta.status_code == 201, conta.text
    cat = client.post("/categorias", json={"nome": "Mercado"}, headers=headers)
    assert cat.status_code == 201, cat.text
    tx = client.post(
        "/transacoes",
        json={
            "conta_id": conta.json()["id"],
            "categoria_id": cat.json()["id"],
            "tipo": "despesa",
            "valor_centavos": 12_345,
            "descricao": "Compra do mês",
            "data_competencia": "2026-09-30",
            "data_lancamento": "2026-10-10",
        },
        headers=headers,
    )
    assert tx.status_code == 201, tx.text
    return {"conta": conta.json()["id"], "categoria": cat.json()["id"], "transacao": tx.json()["id"]}


def test_tenant_a_nao_le_edita_nem_deleta_transacao_do_tenant_b(client, tenant_factory):
    a = tenant_factory("alice@tenant-a.com")
    b = tenant_factory("bob@tenant-b.com")
    assert a.tenant_id != b.tenant_id

    dados_a = _seed(client, a.headers)
    dados_b = _seed(client, b.headers)
    tx_b = dados_b["transacao"]
    original_b = client.get(f"/transacoes/{tx_b}", headers=b.headers).json()

    # --- Leitura direta por ID manipulado na URL ---------------------------
    r = client.get(f"/transacoes/{tx_b}", headers=a.headers)
    assert r.status_code == 404  # 404, não 403: não revela que o ID existe

    # --- Edição -----------------------------------------------------------
    r = client.patch(
        f"/transacoes/{tx_b}",
        json={"valor_centavos": 1, "descricao": "hackeado"},
        headers=a.headers,
    )
    assert r.status_code == 404

    # --- Exclusão ---------------------------------------------------------
    r = client.delete(f"/transacoes/{tx_b}", headers=a.headers)
    assert r.status_code == 404

    # --- Listagem e filtros apontando para recursos de B --------------------
    ids_a = {t["id"] for t in client.get("/transacoes", headers=a.headers).json()["items"]}
    assert ids_a == {dados_a["transacao"]}
    for params in ({"conta_id": dados_b["conta"]}, {"categoria_id": dados_b["categoria"]}):
        page = client.get("/transacoes", params=params, headers=a.headers).json()
        assert page["items"] == [] and page["total"] == 0

    # --- Contas/categorias de B também são invisíveis -------------------------
    assert client.get(f"/contas/{dados_b['conta']}", headers=a.headers).status_code == 404
    assert client.get(f"/categorias/{dados_b['categoria']}", headers=a.headers).status_code == 404

    # --- B continua intacto -------------------------------------------------
    r = client.get(f"/transacoes/{tx_b}", headers=b.headers)
    assert r.status_code == 200
    assert r.json() == original_b


def test_tenant_a_nao_move_propria_transacao_para_conta_ou_categoria_de_b(client, tenant_factory):
    a = tenant_factory("alice@tenant-a.com")
    b = tenant_factory("bob@tenant-b.com")
    dados_a = _seed(client, a.headers)
    dados_b = _seed(client, b.headers)

    base = {"tipo": "despesa", "valor_centavos": 100, "data_competencia": "2026-10-01"}
    r = client.post("/transacoes", json={**base, "conta_id": dados_b["conta"]}, headers=a.headers)
    assert r.status_code == 422
    r = client.post(
        "/transacoes",
        json={**base, "conta_id": dados_a["conta"], "categoria_id": dados_b["categoria"]},
        headers=a.headers,
    )
    assert r.status_code == 422
    r = client.patch(
        f"/transacoes/{dados_a['transacao']}", json={"conta_id": dados_b["conta"]}, headers=a.headers
    )
    assert r.status_code == 422
    r = client.post(
        "/categorias", json={"nome": "Sub", "categoria_pai_id": dados_b["categoria"]}, headers=a.headers
    )
    assert r.status_code == 422


def test_tenant_id_no_corpo_e_rejeitado(client, tenant_factory):
    a = tenant_factory("alice@tenant-a.com")
    b = tenant_factory("bob@tenant-b.com")
    dados_a = _seed(client, a.headers)

    r = client.post(
        "/contas", json={"nome": "X", "tipo": "carteira", "tenant_id": b.tenant_id}, headers=a.headers
    )
    assert r.status_code == 422
    r = client.patch(
        f"/transacoes/{dados_a['transacao']}", json={"tenant_id": b.tenant_id}, headers=a.headers
    )
    assert r.status_code == 422


def test_wrapper_filtra_qualquer_query_e_bloqueia_escrita_cruzada(session_factory, make_user):
    """Testa o mecanismo central diretamente, sem passar pela API."""
    ta, _, _ = make_user("a@a.com")
    tb, _, _ = make_user("b@b.com")
    with session_factory() as db:
        db.add_all(
            [
                Conta(tenant_id=ta, nome="A1", tipo=TipoConta.carteira),
                Conta(tenant_id=tb, nome="B1", tipo=TipoConta.carteira),
                Conta(tenant_id=tb, nome="B2", tipo=TipoConta.corrente),
            ]
        )
        db.commit()
        conta_b_id = db.scalar(select(Conta.id).where(Conta.nome == "B1"))

    with session_factory() as db:
        tdb = TenantSession(db, ta)
        # SELECT sem nenhum WHERE explícito
        assert [c.nome for c in tdb.scalars(select(Conta))] == ["A1"]
        # get por ID de outro tenant
        assert tdb.get(Conta, conta_b_id) is None
        # count via subquery
        assert tdb.count(select(Conta)) == 1
        # session.get "cru" também passa pelo filtro
        assert db.get(Conta, conta_b_id) is None
        # update em massa ORM não atinge outro tenant
        from sqlalchemy import update

        db.execute(update(Conta).values(nome="pwned"))
        db.commit()

    with session_factory() as db:
        nomes = sorted(db.scalars(select(Conta.nome)))
        assert nomes == ["B1", "B2", "pwned"]

    with session_factory() as db:
        tdb = TenantSession(db, ta)
        # tentar criar registro explicitamente em outro tenant
        try:
            tdb.add(Conta(tenant_id=tb, nome="intrusa", tipo=TipoConta.carteira))
            raise AssertionError("deveria ter falhado")
        except TenantViolationError:
            pass
        # tenant_id é preenchido automaticamente
        nova = tdb.add(Conta(nome="auto", tipo=TipoConta.carteira))
        tdb.commit()
        assert nova.tenant_id == ta

    with session_factory() as db:
        tdb = TenantSession(db, ta)
        conta = tdb.scalars(select(Conta).where(Conta.nome == "auto"))[0]
        conta.tenant_id = tb  # tentativa de "mover" registro
        try:
            tdb.commit()
            raise AssertionError("deveria ter falhado")
        except TenantViolationError:
            tdb.rollback()

    with session_factory() as db:
        assert db.scalar(select(Transacao.id)) is None
