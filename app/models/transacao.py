from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, TenantScopedMixin, TimestampMixin
from app.models.categoria import Categoria
from app.models.conta import Conta
from app.models.enums import TipoTransacao


class Transacao(TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "transacoes"
    __table_args__ = (
        # valor é sempre positivo; o sinal vem de `tipo`.
        CheckConstraint("valor_centavos > 0", name="valor_positivo"),
        Index("ix_transacoes_tenant_competencia", "tenant_id", "data_competencia"),
        Index("ix_transacoes_tenant_lancamento", "tenant_id", "data_lancamento"),
        # Reimportar o mesmo extrato não duplica: um lançamento externo entra uma vez por conta.
        UniqueConstraint("tenant_id", "conta_id", "id_externo"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conta_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("contas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    categoria_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("categorias.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    tipo: Mapped[TipoTransacao] = mapped_column(
        Enum(TipoTransacao, native_enum=False, length=20, validate_strings=True), nullable=False
    )
    # Dinheiro em centavos, inteiro. Nunca float.
    valor_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Competência: a que mês/dia o gasto "pertence" (regime de competência).
    data_competencia: Mapped[date] = mapped_column(Date, nullable=False)
    # Lançamento: quando o dinheiro efetivamente saiu/entrou (ex.: fatura do cartão).
    data_lancamento: Mapped[date] = mapped_column(Date, nullable=False)

    # Origem quando veio de um extrato: ID do banco (ex.: "nu:<uuid>") ou uma
    # impressão digital do conteúdo ("fp:<hash>"). Nulo para lançamentos manuais.
    id_externo: Mapped[str | None] = mapped_column(String(64), nullable=True)
    importacao_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("importacoes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    conta: Mapped[Conta] = relationship()
    categoria: Mapped[Categoria | None] = relationship()
