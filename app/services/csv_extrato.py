"""Leitura de extratos CSV (sem acesso a banco de dados).

Formatos reconhecidos automaticamente:
- nubank_conta:  Data,Valor,Identificador,Descrição   (Data dd/mm/aaaa; Valor -45.90;
                 negativo = saída). O Identificador é um UUID estável por lançamento.
- nubank_cartao: date,title,amount  (ou date,category,title,amount nos arquivos antigos;
                 date aaaa-mm-dd; amount positivo = compra, negativo = pagamento/estorno).
- generico:      qualquer CSV; quem chama informa as colunas de data, descrição e valor.

Valores viram centavos inteiros via Decimal; float nunca é usado.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

MAX_LINHAS = 50_000


class Formato(str, Enum):
    nubank_conta = "nubank_conta"
    nubank_cartao = "nubank_cartao"
    generico = "generico"


class ExtratoInvalido(ValueError):
    """Arquivo que não dá para ler como CSV de extrato (mensagem vai para o usuário)."""


@dataclass(frozen=True)
class Mapeamento:
    coluna_data: str
    coluna_descricao: str
    coluna_valor: str
    # True quando o arquivo traz gastos como valores POSITIVOS (comum em faturas de cartão).
    gastos_positivos: bool = False


@dataclass(frozen=True)
class Lancamento:
    linha: int  # número da linha no arquivo (1 = cabeçalho)
    data: date
    descricao: str
    valor_centavos: int  # com sinal: negativo = saída de dinheiro
    id_externo: str


@dataclass
class Resultado:
    lancamentos: list[Lancamento] = field(default_factory=list)
    erros: list[tuple[int, str]] = field(default_factory=list)  # (linha, motivo)


@dataclass(frozen=True)
class Tabela:
    colunas: list[str]
    linhas: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Leitura bruta
# ---------------------------------------------------------------------------


def _decodificar(conteudo: bytes) -> str:
    # Bancos brasileiros exportam em UTF-8 (com ou sem BOM) ou Windows-1252.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtratoInvalido("Não foi possível ler o arquivo: codificação de texto desconhecida")


def ler_tabela(conteudo: bytes) -> Tabela:
    if not conteudo.strip():
        raise ExtratoInvalido("O arquivo está vazio")
    texto = _decodificar(conteudo)
    amostra = texto[:8192]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t")
        delimitador = dialeto.delimiter
    except csv.Error:
        # Sniffer falha com uma coluna só ou arquivos irregulares; vírgula é o padrão.
        delimitador = ";" if amostra.count(";") > amostra.count(",") else ","

    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise ExtratoInvalido("O arquivo está vazio") from None
    colunas = [c.strip() for c in cabecalho]
    if len(colunas) < 2 or len(set(colunas)) != len(colunas) or any(not c for c in colunas):
        raise ExtratoInvalido(
            "Cabeçalho inválido: a primeira linha precisa ter nomes de colunas únicos"
        )

    linhas: list[dict[str, str]] = []
    try:
        for valores in leitor:
            if not any(v.strip() for v in valores):
                linhas.append({})  # linha em branco: mantém a numeração
                continue
            linhas.append({c: (valores[i].strip() if i < len(valores) else "") for i, c in enumerate(colunas)})
            if len(linhas) > MAX_LINHAS:
                raise ExtratoInvalido(f"O arquivo tem mais de {MAX_LINHAS} linhas")
    except csv.Error as exc:
        raise ExtratoInvalido(f"CSV malformado: {exc}") from None
    return Tabela(colunas=colunas, linhas=linhas)


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def detectar_formato(colunas: list[str]) -> Formato:
    norm = [_normalizar(c) for c in colunas]
    if norm == ["data", "valor", "identificador", "descricao"]:
        return Formato.nubank_conta
    if norm in (["date", "title", "amount"], ["date", "category", "title", "amount"]):
        return Formato.nubank_cartao
    return Formato.generico


def sugerir_mapeamento(colunas: list[str]) -> dict[str, str | None]:
    """Palpite de colunas para o modo genérico (a tela deixa a pessoa corrigir)."""
    def achar(*candidatos: str) -> str | None:
        for c in colunas:
            n = _normalizar(c)
            if any(k in n for k in candidatos):
                return c
        return None

    return {
        "coluna_data": achar("data", "date", "dt"),
        "coluna_descricao": achar("descricao", "historico", "lancamento", "title", "memo", "estabelecimento"),
        "coluna_valor": achar("valor", "amount", "quantia", "montante"),
    }


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------

_FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")


def parse_data(texto: str) -> date:
    texto = texto.strip().split(" ")[0]  # descarta hora, se houver
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {texto!r}")


def parse_valor_centavos(texto: str) -> int:
    """'-45.90' | '1.234,56' | 'R$ -1.234,56' | '(45,90)' | '45' -> centavos com sinal."""
    s = texto.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo, s = True, s[1:-1]
    if s.startswith("-"):
        negativo, s = not negativo, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if s.endswith("-"):  # alguns bancos: "45,90-"
        negativo, s = not negativo, s[:-1]
    if not s:
        raise ValueError("valor vazio")

    if "," in s and "." in s:
        # O separador que aparece por último é o decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")  # só pontos de milhar: "1.234.567"

    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        raise ValueError(f"valor inválido: {texto!r}")
    try:
        centavos = int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError(f"valor inválido: {texto!r}") from None
    return -centavos if negativo else centavos


def _impressao_digital(d: date, centavos: int, descricao: str, ocorrencia: int) -> str:
    # Sem ID do banco, identifica o lançamento pelo conteúdo. `ocorrencia` diferencia
    # lançamentos idênticos no mesmo arquivo (dois cafés iguais no mesmo dia) e é
    # estável ao reimportar o mesmo arquivo, então a deduplicação continua funcionando.
    base = f"{d.isoformat()}|{centavos}|{_normalizar(descricao)}|{ocorrencia}"
    return "fp:" + hashlib.sha256(base.encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Interpretação
# ---------------------------------------------------------------------------


def _mapeamento_do_formato(formato: Formato, colunas: list[str], mapeamento: Mapeamento | None) -> Mapeamento:
    por_nome = {_normalizar(c): c for c in colunas}
    if formato == Formato.nubank_conta:
        return Mapeamento(por_nome["data"], por_nome["descricao"], por_nome["valor"])
    if formato == Formato.nubank_cartao:
        return Mapeamento(por_nome["date"], por_nome["title"], por_nome["amount"], gastos_positivos=True)
    if mapeamento is None:
        raise ExtratoInvalido("Para este formato, informe as colunas de data, descrição e valor")
    for nome in (mapeamento.coluna_data, mapeamento.coluna_descricao, mapeamento.coluna_valor):
        if nome not in colunas:
            raise ExtratoInvalido(f"Coluna não encontrada no arquivo: {nome!r}")
    return mapeamento


def interpretar(tabela: Tabela, formato: Formato, mapeamento: Mapeamento | None = None) -> Resultado:
    m = _mapeamento_do_formato(formato, tabela.colunas, mapeamento)
    coluna_id = next(
        (c for c in tabela.colunas if _normalizar(c) == "identificador"), None
    ) if formato == Formato.nubank_conta else None

    resultado = Resultado()
    ocorrencias: Counter[tuple[date, int, str]] = Counter()
    for i, linha in enumerate(tabela.linhas, start=2):
        if not linha:
            continue
        try:
            d = parse_data(linha[m.coluna_data])
            centavos = parse_valor_centavos(linha[m.coluna_valor])
        except ValueError as exc:
            resultado.erros.append((i, str(exc)))
            continue
        if centavos == 0:
            resultado.erros.append((i, "valor zero"))
            continue
        if m.gastos_positivos:
            centavos = -centavos
        descricao = linha[m.coluna_descricao][:255]

        if coluna_id and linha.get(coluna_id):
            id_externo = "nu:" + linha[coluna_id][:60]
        else:
            chave = (d, centavos, _normalizar(descricao))
            ocorrencias[chave] += 1
            id_externo = _impressao_digital(d, centavos, descricao, ocorrencias[chave])
        resultado.lancamentos.append(Lancamento(i, d, descricao, centavos, id_externo))
    return resultado
