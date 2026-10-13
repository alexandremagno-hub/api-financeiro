import pytest


@pytest.fixture
def ctx(client, tenant_factory):
    t = tenant_factory("user@x.com")
    h = t.headers
    corrente = client.post("/contas", json={"nome": "Itaú", "tipo": "corrente"}, headers=h).json()["id"]
    cartao = client.post("/contas", json={"nome": "Nubank", "tipo": "cartao_credito"}, headers=h).json()["id"]
    casa = client.post("/categorias", json={"nome": "Casa"}, headers=h).json()["id"]
    luz = client.post("/categorias", json={"nome": "Luz", "categoria_pai_id": casa}, headers=h).json()["id"]
    lazer = client.post("/categorias", json={"nome": "Lazer"}, headers=h).json()["id"]
    return {"h": h, "corrente": corrente, "cartao": cartao, "casa": casa, "luz": luz, "lazer": lazer}


def _criar(client, h, **kw):
    payload = {"tipo": "despesa", "valor_centavos": 1000, "data_competencia": "2026-10-01", **kw}
    r = client.post("/transacoes", json=payload, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_completo(client, ctx):
    h = ctx["h"]
    tx = _criar(client, h, conta_id=ctx["corrente"], categoria_id=ctx["luz"], valor_centavos=25_990, descricao="Conta de luz")
    assert tx["valor_centavos"] == 25_990
    assert tx["data_lancamento"] == tx["data_competencia"] == "2026-10-01"

    assert client.get(f"/transacoes/{tx['id']}", headers=h).json()["descricao"] == "Conta de luz"

    r = client.patch(
        f"/transacoes/{tx['id']}",
        json={"valor_centavos": 26_000, "data_lancamento": "2026-10-15", "conta_id": ctx["cartao"]},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["valor_centavos"] == 26_000
    assert r.json()["data_lancamento"] == "2026-10-15"
    assert r.json()["conta_id"] == ctx["cartao"]

    assert client.delete(f"/transacoes/{tx['id']}", headers=h).status_code == 204
    assert client.get(f"/transacoes/{tx['id']}", headers=h).status_code == 404


@pytest.mark.parametrize("valor", [10.5, "1050", 0, -100, 10.0])
def test_valor_precisa_ser_inteiro_positivo_em_centavos(client, ctx, valor):
    r = client.post(
        "/transacoes",
        json={"conta_id": ctx["corrente"], "tipo": "despesa", "valor_centavos": valor, "data_competencia": "2026-10-01"},
        headers=ctx["h"],
    )
    assert r.status_code == 422


def test_patch_nao_aceita_nulo_em_campo_obrigatorio(client, ctx):
    tx = _criar(client, ctx["h"], conta_id=ctx["corrente"])
    r = client.patch(f"/transacoes/{tx['id']}", json={"valor_centavos": None}, headers=ctx["h"])
    assert r.status_code == 422


def test_filtros_periodo_conta_categoria(client, ctx):
    h = ctx["h"]
    # Compra no cartão: competência em setembro, lançamento (fatura) em outubro.
    t1 = _criar(client, h, conta_id=ctx["cartao"], categoria_id=ctx["lazer"], data_competencia="2026-09-20", data_lancamento="2026-10-05")
    t2 = _criar(client, h, conta_id=ctx["corrente"], categoria_id=ctx["luz"], data_competencia="2026-10-03")
    t3 = _criar(client, h, conta_id=ctx["corrente"], categoria_id=ctx["casa"], data_competencia="2026-10-20")
    t4 = _criar(client, h, conta_id=ctx["corrente"], tipo="receita", valor_centavos=500_000, data_competencia="2026-10-05")

    def ids(**params):
        r = client.get("/transacoes", params=params, headers=h)
        assert r.status_code == 200, r.text
        return {t["id"] for t in r.json()["items"]}

    assert ids() == {t1["id"], t2["id"], t3["id"], t4["id"]}
    # período por competência (padrão) vs. por lançamento
    assert ids(data_inicio="2026-10-01", data_fim="2026-10-31") == {t2["id"], t3["id"], t4["id"]}
    assert ids(data_inicio="2026-10-01", data_fim="2026-10-31", campo_data="lancamento") == {t1["id"], t2["id"], t3["id"], t4["id"]}
    assert ids(data_fim="2026-09-30") == {t1["id"]}
    # conta
    assert ids(conta_id=ctx["cartao"]) == {t1["id"]}
    # categoria inclui subcategorias por padrão
    assert ids(categoria_id=ctx["casa"]) == {t2["id"], t3["id"]}
    assert ids(categoria_id=ctx["casa"], incluir_subcategorias=False) == {t3["id"]}
    # tipo + combinação
    assert ids(tipo="receita") == {t4["id"]}
    assert ids(conta_id=ctx["corrente"], data_inicio="2026-10-04", tipo="despesa") == {t3["id"]}
    # período inválido
    assert client.get("/transacoes", params={"data_inicio": "2026-10-10", "data_fim": "2026-10-01"}, headers=h).status_code == 422


def test_paginacao(client, ctx):
    for i in range(5):
        _criar(client, ctx["h"], conta_id=ctx["corrente"], data_competencia=f"2026-10-0{i + 1}")
    page = client.get("/transacoes", params={"limit": 2, "offset": 2}, headers=ctx["h"]).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert [t["data_competencia"] for t in page["items"]] == ["2026-10-03", "2026-10-02"]


def test_conta_com_transacoes_nao_pode_ser_removida(client, ctx):
    _criar(client, ctx["h"], conta_id=ctx["corrente"])
    assert client.delete(f"/contas/{ctx['corrente']}", headers=ctx["h"]).status_code == 409


def test_categoria_nao_aceita_ciclo(client, ctx):
    r = client.patch(f"/categorias/{ctx['casa']}", json={"categoria_pai_id": ctx["luz"]}, headers=ctx["h"])
    assert r.status_code == 422
