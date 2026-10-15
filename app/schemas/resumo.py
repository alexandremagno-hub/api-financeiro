from app.schemas.common import OutputModel


class CategoriaResumo(OutputModel):
    categoria_id: int | None
    nome: str
    total_centavos: int
    quantidade: int


class DestinoResumo(OutputModel):
    # Chave normalizada do destino; serve de filtro em GET /transacoes?destino=.
    chave: str
    nome: str
    total_centavos: int
    quantidade: int


class ResumoMesOut(OutputModel):
    mes: str  # AAAA-MM
    total_despesas_centavos: int
    total_receitas_centavos: int
    saldo_centavos: int
    # Movimentações excluídas dos totais (ex.: pagamento de fatura), para transparência.
    fora_do_resumo_centavos: int
    despesas_por_categoria: list[CategoriaResumo]
    despesas_por_destino: list[DestinoResumo]
    quantidade_transacoes: int
