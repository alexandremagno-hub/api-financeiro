import enum


class Role(str, enum.Enum):
    admin = "admin"
    usuario = "usuario"


class TipoConta(str, enum.Enum):
    carteira = "carteira"
    corrente = "corrente"
    cartao_credito = "cartao_credito"


class TipoTransacao(str, enum.Enum):
    receita = "receita"
    despesa = "despesa"
