from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigIntPK, TenantScopedMixin, TimestampMixin
from app.models.conta import Conta


class Importacao(TenantScopedMixin, TimestampMixin, Base):
    """Registro de um arquivo de extrato importado (permite desfazer a importação)."""

    __tablename__ = "importacoes"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conta_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("contas.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    formato: Mapped[str] = mapped_column(String(30), nullable=False)
    total_linhas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    importadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    com_erro: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    conta: Mapped[Conta] = relationship()
