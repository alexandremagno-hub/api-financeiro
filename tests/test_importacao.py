from tests.test_csv_extrato import NUBANK_CARTAO, NUBANK_CONTA


def _importar(client, headers, conteudo: bytes, nome="extrato.csv", **form):
    return client.post(
        "/importacoes",
        files={"arquivo": (nome, conteudo, "text/csv")},
        data={k: str(v) for k, v in form.items()},
        headers=headers,
    )


def test_preview_nao_salva_e_detecta_formato(client, tenant_factory):
    t = tenant_factory("a@a.com")
    r = client.post("/importacoes/preview", files={"arquivo": ("n.csv", NUBANK_CARTAO, "text/csv")}, headers=t.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["formato"] == "nubank_cartao"
    assert body["total_linhas"] == 4
    assert body["conta_sugerida"] == "Nubank - Cartão"
    assert body["amostra"][0] == {"date": "2026-10-02", "title": "Uber *Trip", "amount": "23.50"}
    assert client.get("/transacoes", headers=t.headers).json()["total"] == 0


def test_importa_nubank_cria_conta_categoriza_e_resume_o_mes(client, tenant_factory):
    t = tenant_factory("a@a.com")
    r = _importar(client, t.headers, NUBANK_CONTA, conta_nome="Nubank - Conta")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["importacao"]["importadas"] == 3
    assert body["importacao"]["conta_nome"] == "Nubank - Conta"
    assert body["meses"] == ["2026-10"]

    r = _importar(client, t.headers, NUBANK_CARTAO, conta_nome="Nubank - Cartão")
    assert r.json()["importacao"]["importadas"] == 4

    contas = {c["nome"]: c["tipo"] for c in client.get("/contas", headers=t.headers).json()}
    assert contas == {"Nubank - Conta": "corrente", "Nubank - Cartão": "cartao_credito"}

    resumo = client.get("/resumo", params={"mes": "2026-10"}, headers=t.headers).json()
    # Despesas: padaria 45,90 + uber 23,50 + 2x ifood 58,00 = 185,40
    # Pagamento de fatura (1.234,56 na conta e 500,00 no cartão) fica FORA dos totais.
    assert resumo["total_despesas_centavos"] == 4590 + 2350 + 5800 * 2
    assert resumo["total_receitas_centavos"] == 350000
    assert resumo["saldo_centavos"] == 350000 - 18540
    assert resumo["fora_do_resumo_centavos"] == 123456 + 50000
    por_cat = {c["nome"]: c["total_centavos"] for c in resumo["despesas_por_categoria"]}
    assert por_cat == {"Alimentação": 4590 + 11600, "Transporte": 2350}
    assert resumo["despesas_por_categoria"][0]["nome"] == "Alimentação"  # maior primeiro
    por_destino = [(d["nome"], d["total_centavos"], d["quantidade"]) for d in resumo["despesas_por_destino"]]
    assert por_destino == [("iFood", 11600, 2), ("Padaria do Zé", 4590, 1), ("Uber", 2350, 1)]

    ifood = client.get("/transacoes", params={"destino": "ifood", "limit": 1}, headers=t.headers).json()
    assert ifood["total"] == 2 and len(ifood["items"]) == 1
    assert client.get("/resumo/meses", headers=t.headers).json() == ["2026-10"]


def test_reimportar_nao_duplica(client, tenant_factory):
    t = tenant_factory("a@a.com")
    _importar(client, t.headers, NUBANK_CARTAO, conta_nome="Cartão")
    r = _importar(client, t.headers, NUBANK_CARTAO, conta_nome="Cartão")
    assert r.json()["importacao"]["importadas"] == 0
    assert r.json()["importacao"]["duplicadas"] == 4
    assert client.get("/transacoes", headers=t.headers).json()["total"] == 4

    # arquivo do mês seguinte que repete parte do anterior: só o novo entra
    novo = NUBANK_CARTAO + b"2026-11-01,Netflix.com,55.90\n"
    r = _importar(client, t.headers, novo, conta_nome="Cartão")
    assert r.json()["importacao"]["importadas"] == 1
    assert r.json()["meses"] == ["2026-11"]


def test_generico_exige_colunas_e_importa_com_mapeamento(client, tenant_factory):
    t = tenant_factory("a@a.com")
    csv = "Data;Histórico;Valor\n02/10/2026;SUPERMERCADO X;150,30\n03/10/2026;linha ruim;abc\n".encode("cp1252")
    r = _importar(client, t.headers, csv, conta_nome="Banco X")
    assert r.status_code == 422

    r = _importar(
        client, t.headers, csv, conta_nome="Banco X",
        coluna_data="Data", coluna_descricao="Histórico", coluna_valor="Valor", gastos_positivos="true",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["importacao"]["importadas"] == 1 and body["importacao"]["com_erro"] == 1
    assert body["erros"] == [{"linha": 3, "motivo": "valor inválido: 'abc'"}]
    tx = client.get("/transacoes", params={"data_inicio": "2026-10-01", "data_fim": "2026-10-31"}, headers=t.headers).json()["items"][0]
    assert tx["tipo"] == "despesa" and tx["valor_centavos"] == 15030


def test_desfazer_importacao_remove_so_os_lancamentos_dela(client, tenant_factory):
    t = tenant_factory("a@a.com")
    a = _importar(client, t.headers, NUBANK_CONTA, conta_nome="Conta").json()["importacao"]["id"]
    _importar(client, t.headers, NUBANK_CARTAO, conta_nome="Cartão")
    assert client.delete(f"/importacoes/{a}", headers=t.headers).status_code == 204
    assert client.get("/transacoes", headers=t.headers).json()["total"] == 4
    assert [i["conta_nome"] for i in client.get("/importacoes", headers=t.headers).json()] == ["Cartão"]


def test_recategorizar_muda_o_resumo(client, tenant_factory):
    t = tenant_factory("a@a.com")
    _importar(client, t.headers, NUBANK_CARTAO, conta_nome="Cartão")
    cats = {c["nome"]: c["id"] for c in client.get("/categorias", headers=t.headers).json()}
    uber = next(tx for tx in client.get("/transacoes", headers=t.headers).json()["items"] if "Uber" in tx["descricao"])
    r = client.patch(f"/transacoes/{uber['id']}", json={"categoria_id": cats["Lazer"]}, headers=t.headers)
    assert r.status_code == 200
    por_cat = {c["nome"] for c in client.get("/resumo", params={"mes": "2026-10"}, headers=t.headers).json()["despesas_por_categoria"]}
    assert "Lazer" in por_cat and "Transporte" not in por_cat


def test_isolamento_de_importacoes_e_resumo_entre_tenants(client, tenant_factory):
    a = tenant_factory("a@a.com")
    b = tenant_factory("b@b.com")
    imp_b = _importar(client, b.headers, NUBANK_CONTA, conta_nome="Conta B").json()["importacao"]
    conta_b = imp_b["conta_id"]

    # A não vê o resumo, os meses nem as importações de B
    resumo_a = client.get("/resumo", params={"mes": "2026-10"}, headers=a.headers).json()
    assert resumo_a["quantidade_transacoes"] == 0 and resumo_a["despesas_por_categoria"] == []
    assert client.get("/resumo/meses", headers=a.headers).json() == []
    assert client.get("/importacoes", headers=a.headers).json() == []
    # A não desfaz importação de B nem importa para a conta de B
    assert client.delete(f"/importacoes/{imp_b['id']}", headers=a.headers).status_code == 404
    assert _importar(client, a.headers, NUBANK_CONTA, conta_id=conta_b).status_code == 422
    # Mesmo arquivo com os mesmos IDs do banco importa normalmente para A (dedupe é por tenant/conta)
    assert _importar(client, a.headers, NUBANK_CONTA, conta_nome="Conta A").json()["importacao"]["importadas"] == 3
    # B continua intacto
    assert client.get("/transacoes", headers=b.headers).json()["total"] == 3


def test_arquivo_invalido_ou_grande(client, tenant_factory):
    t = tenant_factory("a@a.com")
    assert _importar(client, t.headers, b"", conta_nome="X").status_code == 422
    assert _importar(client, t.headers, b"\x00\xff\xfe" * 10, conta_nome="X").status_code == 422
    grande = b"Data,Valor,Identificador,Descri\xc3\xa7\xc3\xa3o\n" + b"x" * (5 * 1024 * 1024)
    assert _importar(client, t.headers, grande, conta_nome="X").status_code == 413
    assert client.post("/importacoes/preview", files={"arquivo": ("x.csv", b"", "text/csv")}).status_code == 401
