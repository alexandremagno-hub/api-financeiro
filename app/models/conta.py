from sqlalchemy import BigInteger, Boolean, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TenantScopedMixin, TimestampMixin
from app.models.enums import TipoConta


class Conta(TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "contas"
    __table_args__ = (UniqueConstraint("tenant_id", "nome"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[TipoConta] = mapped_column(
        Enum(TipoConta, native_enum=False, length=20, validate_strings=True), nullable=False
    )
    saldo_inicial_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ativa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
