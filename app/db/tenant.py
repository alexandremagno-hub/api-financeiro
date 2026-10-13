"""Isolamento de tenant centralizado.

Como funciona:

1. `TenantSession` envolve uma `Session` do SQLAlchemy e grava o tenant_id em
   `session.info`. É a única forma que as rotas de domínio têm de acessar o banco
   (injetada pela dependency `get_tenant_db`).

2. Um listener `do_orm_execute` aplica `with_loader_criteria(TenantScopedMixin, ...)`
   a TODO SELECT/UPDATE/DELETE ORM executado por essa sessão. Isso cobre também
   `session.get()`, lazy loads de relacionamentos e subqueries com aliases —
   esquecer um `.where(tenant_id == ...)` deixa de ser possível.

3. Um listener `before_flush` preenche tenant_id em objetos novos e impede que
   um objeto seja gravado/alterado/deletado com tenant_id diferente do da sessão.

Sessões sem tenant em `info` (ex.: login, CLI de bootstrap) não são filtradas.
"""

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, event, func, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import TenantScopedMixin

TENANT_KEY = "tenant_id"

M = TypeVar("M")


class TenantViolationError(RuntimeError):
    pass


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state: ORMExecuteState) -> None:
    tenant_id = state.session.info.get(TENANT_KEY)
    if tenant_id is None:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.execution_options.get("skip_tenant_filter"):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScopedMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
            track_closure_variables=False,
        )
    )


@event.listens_for(Session, "before_flush")
def _enforce_tenant_on_write(session: Session, flush_context: Any, instances: Any) -> None:
    tenant_id = session.info.get(TENANT_KEY)
    if tenant_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScopedMixin):
            if obj.tenant_id is None:
                obj.tenant_id = tenant_id
            elif obj.tenant_id != tenant_id:
                raise TenantViolationError("Tentativa de criar registro em outro tenant")
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, TenantScopedMixin) and obj.tenant_id != tenant_id:
            raise TenantViolationError("Tentativa de alterar registro de outro tenant")


class TenantSession:
    """Wrapper de acesso a dados com escopo de tenant.

    Todas as consultas passam pela Session subjacente, que filtra
    automaticamente qualquer model com tenant_id (ver listeners acima).
    """

    def __init__(self, session: Session, tenant_id: int) -> None:
        if tenant_id is None:
            raise ValueError("tenant_id é obrigatório")
        self.session = session
        self.tenant_id = tenant_id
        session.info[TENANT_KEY] = tenant_id

    # --- leitura ---------------------------------------------------------
    def get(self, model: type[M], id_: Any) -> M | None:
        # session.get consultaria o identity map antes do banco, sem passar pelo
        # filtro; por isso usamos um SELECT explícito (sempre filtrado).
        return self.session.scalars(select(model).where(model.id == id_)).first()  # type: ignore[attr-defined]

    def scalars(self, stmt: Select[Any]) -> Sequence[Any]:
        return self.session.scalars(stmt).all()

    def scalar(self, stmt: Select[Any]) -> Any:
        return self.session.scalar(stmt)

    def count(self, stmt: Select[Any]) -> int:
        return self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ) or 0

    # --- escrita ---------------------------------------------------------
    def add(self, obj: M) -> M:
        if isinstance(obj, TenantScopedMixin):
            if obj.tenant_id is not None and obj.tenant_id != self.tenant_id:
                raise TenantViolationError("Tentativa de criar registro em outro tenant")
            obj.tenant_id = self.tenant_id
        self.session.add(obj)
        return obj

    def delete(self, obj: Any) -> None:
        self.session.delete(obj)

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def refresh(self, obj: Any) -> None:
        self.session.refresh(obj)
