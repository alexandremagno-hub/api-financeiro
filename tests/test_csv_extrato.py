from datetime import date

import pytest

from app.services.categorizacao import sugerir_categoria
from app.services.csv_extrato import (
    ExtratoInvalido,
    Formato,
    Mapeamento,
    detectar_formato,
    interpretar,
    ler_tabela,
    parse_data,
    parse_valor_centavos,
    sugerir_mapeamento,
)
from app.services.destino import destino

NUBANK_CONTA = (
    "Data,Valor,Identificador,Descrição\n"
    "01/10/2026,-45.90,6a1b2c3d-0000-4000-8000-000000000001,Compra no débito - PADARIA DO ZÉ\n"
    "05/10/2026,3500.00,6a1b2c3d-0000-4000-8000-000000000002,Transferência recebida - SALARIO EMPRESA\n"
    "10/10/2026,-1234.56,6a1b2c3d-0000-4000-8000-000000000003,Pagamento de fatura\n"
).encode()

NUBANK_CARTAO = (
    "date,title,amount\n"
    "2026-10-02,Uber *Trip,23.50\n"
    "2026-10-03,Ifood *Restaurante,58.00\n"
    "2026-10-03,Ifood *Restaurante,58.00\n"  # dois pedidos iguais no mesmo dia
    "2026-10-08,Pagamento recebido,-500.00\n"
).encode()


@pytest.mark.parametrize(
    ("texto", "centavos"),
    [
        ("-45.90", -4590),
        ("45.9", 4590),
        ("1.234,56", 123456),
        ("-1.234,56", -123456),
        ("R$ 1.234,56", 123456),
        ("1,234.56", 123456),
        ("(45,90)", -4590),
        ("45,90-", -4590),
        ("0.10", 10),
        ("1.234.567", 123456700),
        ("10", 1000),
    ],
)
def test_parse_valor_centavos(texto, centavos):
    assert parse_valor_centavos(texto) == centavos


@pytest.mark.parametrize("texto", ["", "abc", "10,555", "1.2.3,4.5", "--"])
def test_parse_valor_invalido(texto):
    with pytest.raises(ValueError):
        parse_valor_centavos(texto)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("01/10/2026", date(2026, 10, 1)), ("2026-10-01", date(2026, 10, 1)), ("01/10/26", date(2026, 10, 1)), ("01/10/2026 13:45", date(2026, 10, 1))],
)
def test_parse_data(texto, esperado):
    assert parse_data(texto) == esperado


def test_detecta_nubank_conta_e_interpreta():
    tabela = ler_tabela(NUBANK_CONTA)
    assert detectar_formato(tabela.colunas) == Formato.nubank_conta
    r = interpretar(tabela, Formato.nubank_conta)
    assert r.erros == []
    assert [(lc.data, lc.valor_centavos) for lc in r.lancamentos] == [
        (date(2026, 10, 1), -4590),
        (date(2026, 10, 5), 350000),
        (date(2026, 10, 10), -123456),
    ]
    assert r.lancamentos[0].id_externo == "nu:6a1b2c3d-0000-4000-8000-000000000001"
    assert r.lancamentos[0].descricao == "Compra no débito - PADARIA DO ZÉ"


def test_detecta_nubank_cartao_inverte_sinal_e_diferencia_repetidos():
    tabela = ler_tabela(NUBANK_CARTAO)
    assert detectar_formato(tabela.colunas) == Formato.nubank_cartao
    r = interpretar(tabela, Formato.nubank_cartao)
    # compra (positivo no arquivo) vira saída (negativo); pagamento vira entrada
    assert [lc.valor_centavos for lc in r.lancamentos] == [-2350, -5800, -5800, 50000]
    ids = [lc.id_externo for lc in r.lancamentos]
    assert len(set(ids)) == 4  # os dois iFood idênticos não colidem
    # e o resultado é estável: reler o mesmo arquivo gera os mesmos IDs
    assert ids == [lc.id_externo for lc in interpretar(ler_tabela(NUBANK_CARTAO), Formato.nubank_cartao).lancamentos]


def test_cp1252_ponto_e_virgula_e_mapeamento_generico():
    conteudo = "Data;Histórico;Valor (R$)\n02/10/2026;SUPERMERCADO BOM PREÇO;-150,30\n03/10/2026;linha ruim;abc\n".encode("cp1252")
    tabela = ler_tabela(conteudo)
    assert tabela.colunas == ["Data", "Histórico", "Valor (R$)"]
    assert detectar_formato(tabela.colunas) == Formato.generico
    assert sugerir_mapeamento(tabela.colunas) == {
        "coluna_data": "Data",
        "coluna_descricao": "Histórico",
        "coluna_valor": "Valor (R$)",
    }
    r = interpretar(tabela, Formato.generico, Mapeamento("Data", "Histórico", "Valor (R$)"))
    assert [(lc.descricao, lc.valor_centavos) for lc in r.lancamentos] == [("SUPERMERCADO BOM PREÇO", -15030)]
    assert r.erros == [(3, "valor inválido: 'abc'")]


def test_generico_sem_mapeamento_e_arquivos_invalidos():
    tabela = ler_tabela(b"a,b\n1,2\n")
    with pytest.raises(ExtratoInvalido):
        interpretar(tabela, Formato.generico)
    with pytest.raises(ExtratoInvalido):
        interpretar(tabela, Formato.generico, Mapeamento("x", "a", "b"))
    for ruim in (b"", b"   \n", b"so_uma_coluna\n1\n", b"a,a\n1,2\n"):
        with pytest.raises(ExtratoInvalido):
            ler_tabela(ruim)


@pytest.mark.parametrize(
    ("descricao", "categoria"),
    [
        ("Uber *Trip", "Transporte"),
        ("Compra no débito - PADARIA DO ZÉ", "Alimentação"),
        ("IFOOD *RESTAURANTE", "Alimentação"),
        ("SUPERMERCADO BOM PREÇO", "Mercado"),
        ("Netflix.com", "Assinaturas e serviços"),
        ("Pagamento de fatura", "Pagamento de fatura"),
        ("Pagamento recebido", "Pagamento de fatura"),
        ("Transferência enviada pelo Pix - FULANO", "Transferências"),
        ("DROGARIA SAO PAULO", "Saúde"),
        ("XPTO LTDA", "Outros"),
    ],
)
def test_sugerir_categoria(descricao, categoria):
    assert sugerir_categoria(descricao) == categoria


@pytest.mark.parametrize(
    ("descricao", "nome"),
    [
        ("Compra no débito - DL*99 99", "99"),
        ("Compra no débito - DL          *99 99", "99"),
        ("Transferência enviada pelo Pix - FULANO DE TAL - •••.123.456-•• - NU PAGAMENTOS - IP (0260) Agência: 1", "Fulano de Tal"),
        ("Transferência enviada pelo Pix - Dhenice Vitoria Alves Sa - •••.284.273-•• - BANCO INTER (0077)", "Dhenice Vitoria Alves Sa"),
        ("Transferência enviada pelo Pix - IFOOD.COM AGENCIA DE RESTAURANTES ONLINE S.A. - 14.380.200/0001-21", "iFood"),
        ("Pagamento de boleto efetuado - G3 TELECOM LTDA", "G3 Telecom"),
        ("Uber *Trip", "Uber"),
        ("Loja X - Centro", "Loja X - Centro"),
    ],
)
def test_destino(descricao, nome):
    assert destino(descricao).nome == nome


def test_destino_agrupa_maiusculas_e_espacos():
    assert destino("Transferência enviada pelo Pix - FULANO DE TAL - x").chave == destino("Pix - Fulano de  Tal").chave
