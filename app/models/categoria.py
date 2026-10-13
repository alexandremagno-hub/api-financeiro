from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, TenantScopedMixin, TimestampMixin


class Categoria(TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "categorias"
    __table_args__ = (UniqueConstraint("tenant_id", "categoria_pai_id", "nome"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    categoria_pai_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("categorias.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    # Movimentações que não são gasto nem receita de verdade (ex.: pagamento da
    # fatura do cartão) ficam fora dos totais do resumo para não contar em dobro.
    fora_do_resumo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    pai: Mapped["Categoria | None"] = relationship(remote_side=[id], back_populates="filhas")
    filhas: Mapped[list["Categoria"]] = relationship(back_populates="pai")
