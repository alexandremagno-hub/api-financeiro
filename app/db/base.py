from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# BIGINT no MySQL; INTEGER no SQLite (necessário para autoincrement nos testes).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin:
    """Marca um model como pertencente a um tenant.

    Qualquer model que herde deste mixin é filtrado automaticamente por
    `app.db.tenant` em toda consulta feita por uma sessão com tenant definido.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        return mapped_column(
            BigIntPK,
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
