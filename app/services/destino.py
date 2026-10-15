"""Para onde foi o dinheiro: o destino (loja, app, pessoa) a partir da descrição.

O extrato da conta Nubank descreve a operação e depois o destino, seguido de
documento e banco:

    Transferência enviada pelo Pix - FULANO DE TAL - •••.123.456-•• - BANCO (0001) ...
    Compra no débito - DL*99 99
    Pagamento de boleto efetuado - G3 TELECOM LTDA

Na fatura do cartão a descrição já é o estabelecimento ("Uber *Trip"). O
destino é agrupado por uma chave normalizada, para que "DL*99 99" e
"DL          *99 99" (ou o mesmo nome em maiúsculas e minúsculas) somem juntos.
"""

import re
import unicodedata
from dataclasses import dataclass

# Primeiro trecho de descrições no formato "<operação> - <destino> - ...".
_OPERACAO = re.compile(
    r"^(compra|transferencia|pagamento|pix|ted|doc|debito|saque|estorno|reembolso|resgate|aplicacao)\b"
)
_SUFIXO_EMPRESA = re.compile(r"[\s,.-]+(ltda|s\.a|s/a|epp|eireli)\.?$", re.IGNORECASE)
_MINUSCULAS = {"da", "de", "do", "das", "dos", "e"}

# Nomes conhecidos que aparecem de várias formas no extrato.
_APELIDOS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(dl ?\* ?)?99( |\*|$)|^99 ?(app|pop|tecnologia)"), "99"),
    (re.compile(r"^uber\b"), "Uber"),
    (re.compile(r"^ifood\b"), "iFood"),
]


@dataclass(frozen=True)
class Destino:
    chave: str
    nome: str


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _titulo(nome: str) -> str:
    # Só reescreve nomes todos em maiúsculas; "PostoImperador" fica como veio.
    if nome != nome.upper():
        return nome
    palavras = nome.lower().split(" ")
    return " ".join(p if i and p in _MINUSCULAS else p[:1].upper() + p[1:] for i, p in enumerate(palavras))


def destino(descricao: str) -> Destino:
    partes = [p.strip() for p in re.split(r"\s+-\s+", descricao.strip())]
    nome = partes[1] if len(partes) > 1 and _OPERACAO.match(_ascii(partes[0])) else descricao
    nome = re.sub(r"\s*\*\s*", "*", re.sub(r"\s+", " ", nome)).strip()
    nome = _SUFIXO_EMPRESA.sub("", nome).strip() or nome

    normalizado = _ascii(nome)
    for padrao, apelido in _APELIDOS:
        if padrao.search(normalizado):
            return Destino(chave=_ascii(apelido), nome=apelido)
    if not normalizado:
        return Destino(chave="", nome="Sem descrição")
    return Destino(chave=re.sub(r"[^a-z0-9*]+", " ", normalizado).strip(), nome=_titulo(nome))
