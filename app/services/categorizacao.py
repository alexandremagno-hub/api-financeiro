"""Categorização automática de lançamentos importados, por palavras-chave.

As regras são propositalmente simples: a pessoa corrige a categoria na tela, e
o resumo do mês reflete a correção. A primeira regra que casa vence.
"""

import re
import unicodedata

from sqlalchemy import select

from app.db.tenant import TenantSession
from app.models import Categoria

OUTROS = "Outros"
PAGAMENTO_FATURA = "Pagamento de fatura"

# (categoria, fora_do_resumo)
CATEGORIAS_PADRAO: list[tuple[str, bool]] = [
    ("Alimentação", False),
    ("Mercado", False),
    ("Transporte", False),
    ("Moradia", False),
    ("Saúde", False),
    ("Lazer", False),
    ("Compras", False),
    ("Assinaturas e serviços", False),
    ("Educação", False),
    ("Transferências", False),
    ("Salário e rendimentos", False),
    # Pagar a fatura do cartão não é um gasto novo: os gastos já aparecem, um a
    # um, no extrato do cartão. Contar os dois duplicaria a despesa do mês.
    (PAGAMENTO_FATURA, True),
    (OUTROS, False),
]

_REGRAS: list[tuple[str, tuple[str, ...]]] = [
    (PAGAMENTO_FATURA, ("pagamento de fatura", "pagamento recebido", "pagto fatura", "pag fatura")),
    ("Salário e rendimentos", ("salario", "rendimento", "proventos", "pagamento de salario", "remuneracao")),
    ("Mercado", ("supermercado", "mercado", "carrefour", "pao de acucar", "assai", "atacadao", "extra ", "hortifruti", "sacolao")),
    ("Alimentação", ("ifood", "restaurante", "lanchonete", "padaria", "rappi", "burger", "pizza", "mcdonald", "bk ", "cafe", "bar ", "acai")),
    ("Transporte", ("uber", "99app", "99 pop", "99*", "taxi", "posto", "combustivel", "shell", "ipiranga", "petrobras", "estacionamento", "metro", "bilhete unico", "sem parar", "pedagio")),
    ("Assinaturas e serviços", ("netflix", "spotify", "amazon prime", "prime video", "disney", "hbo", "max.com", "youtube", "google one", "icloud", "apple.com", "vivo", "claro", "tim ", "oi ", "internet")),
    ("Moradia", ("aluguel", "condominio", "energia", "enel", "light", "cemig", "copel", "sabesp", "agua", "gas ")),
    ("Saúde", ("farmacia", "drogaria", "droga raia", "drogasil", "pague menos", "hospital", "clinica", "laboratorio", "unimed", "amil", "dentista")),
    ("Educação", ("escola", "faculdade", "universidade", "curso", "udemy", "alura", "livraria")),
    ("Lazer", ("cinema", "ingresso", "show", "steam", "playstation", "xbox", "viagem", "hotel", "airbnb")),
    ("Compras", ("mercado livre", "mercadolivre", "amazon", "shopee", "magalu", "magazine", "americanas", "aliexpress", "shein", "renner", "c&a", "riachuelo")),
    ("Transferências", ("transferencia", "pix", "ted ", "doc ")),
]


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s) + " "  # espaço final: casa palavras-chave como "bar "


def sugerir_categoria(descricao: str) -> str:
    texto = _normalizar(descricao)
    for categoria, palavras in _REGRAS:
        if any(p in texto for p in palavras):
            return categoria
    return OUTROS


def garantir_categorias_padrao(tdb: TenantSession) -> dict[str, Categoria]:
    """Cria (uma vez por tenant) as categorias padrão. Retorna todas por nome."""
    existentes = {c.nome: c for c in tdb.scalars(select(Categoria).where(Categoria.categoria_pai_id.is_(None)))}
    for nome, fora in CATEGORIAS_PADRAO:
        if nome not in existentes:
            existentes[nome] = tdb.add(Categoria(nome=nome, fora_do_resumo=fora))
    tdb.flush()
    return existentes
