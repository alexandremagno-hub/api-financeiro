from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TenantScopedMixin, TimestampMixin
from app.models.enums import Role


class Usuario(TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # E-mail é único globalmente: o login não pede tenant, ele é inferido do usuário.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=Role.usuario,
    )
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
