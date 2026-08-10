"""Managed asynchronous database lifecycle and unit of work."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from community_bot.application.member_foundation import FoundationUnitOfWork, UpdateReceipt
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.infrastructure.db.economy import (
    SqlAlchemyEconomyMutation,
    acquire_product_config_mutation_gate,
    activate_product_config_locked,
    get_active_product_config,
    ingest_product_config_locked,
    read_ledger_history,
    reconcile_economy,
    resolve_member_level,
)
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
)

_UPDATE_LOCK_NAMESPACE = "telegram_update"

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import TracebackType
    from uuid import UUID

    from community_bot.application.economy import (
        ActiveProductConfig,
        LedgerHistoryCursor,
        LedgerHistoryPage,
        ProductConfigActivationCommand,
        ProductConfigActivationResult,
        ProductConfigVersion,
        ReconciliationMismatch,
    )
    from community_bot.domain.economy import ProductConfigCandidate, ResolvedLevel


class Database:
    """Own the process-level async engine and isolated session factory."""

    def __init__(self, database_url: str) -> None:
        """Create an engine without opening a connection eagerly."""
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def unit_of_work(
        self,
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_economy_cache_flushed: Callable[[], None] | None = None,
        after_product_config_pointer_switched: Callable[[], None] | None = None,
    ) -> SqlAlchemyUnitOfWork:
        """Create a fresh transactional unit of work."""
        return SqlAlchemyUnitOfWork(
            self._sessions,
            after_ledger_flushed=after_ledger_flushed,
            after_economy_cache_flushed=after_economy_cache_flushed,
            after_product_config_pointer_switched=after_product_config_pointer_switched,
        )

    async def dispose(self) -> None:
        """Release all engine resources."""
        await self.engine.dispose()


class SqlAlchemyUnitOfWork(FoundationUnitOfWork):
    """PostgreSQL implementation of the member-foundation transaction."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_economy_cache_flushed: Callable[[], None] | None = None,
        after_product_config_pointer_switched: Callable[[], None] | None = None,
    ) -> None:
        """Configure an isolated session factory."""
        self._sessions = sessions
        self._after_ledger_flushed = after_ledger_flushed
        self._after_economy_cache_flushed = after_economy_cache_flushed
        self._after_product_config_pointer_switched = after_product_config_pointer_switched
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        """Open a fresh session and transaction."""
        self._session = self._sessions()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback unfinished work and close the isolated session."""
        session = self._require_session()
        if not self._committed:
            await session.rollback()
        await session.close()

    async def acquire_update_gate(self, update_id: int) -> None:
        """Serialize one exact update ID for the current transaction."""
        await self._require_session().execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:namespace, :update_id))"),
            {"namespace": _UPDATE_LOCK_NAMESPACE, "update_id": update_id},
        )

    @property
    def economy(self) -> SqlAlchemyEconomyMutation:
        """Return the economy adapter bound to this transaction."""
        return SqlAlchemyEconomyMutation(
            self._require_session(),
            after_ledger_flushed=self._after_ledger_flushed,
            after_cache_flushed=self._after_economy_cache_flushed,
        )

    async def acquire_product_config_mutation_gate(self) -> None:
        """Serialize every product configuration mutation."""
        await acquire_product_config_mutation_gate(self._require_session())

    async def get_receipt(self, update_id: int) -> UpdateReceipt | None:
        """Read a complete receipt by exact update ID."""
        model = await self._require_session().get(ProcessedTelegramUpdateModel, update_id)
        if model is None:
            return None
        return UpdateReceipt(update_id=model.update_id, outcome_code=model.outcome_code)

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        """Resolve a member by the immutable Telegram identity."""
        model = await self._require_session().scalar(
            select(MemberModel).where(MemberModel.telegram_user_id == telegram_user_id)
        )
        return None if model is None else _to_domain(model)

    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]:
        """Lock requested members in deterministic UUID order."""
        ordered_ids = sorted(set(member_ids), key=str)
        models = (
            await self._require_session().scalars(
                select(MemberModel)
                .where(MemberModel.id.in_(ordered_ids))
                .order_by(MemberModel.id)
                .with_for_update()
            )
        ).all()
        members = {model.id: _to_domain(model) for model in models}
        missing = set(ordered_ids) - members.keys()
        if missing:
            msg = "One or more member records do not exist."
            raise LookupError(msg)
        return members

    async def lock_all_members(self) -> dict[UUID, Member]:
        """Lock all members in deterministic UUID order."""
        models = (
            await self._require_session().scalars(
                select(MemberModel).order_by(MemberModel.id).with_for_update()
            )
        ).all()
        return {model.id: _to_domain(model) for model in models}

    async def get_active_product_config(self) -> ActiveProductConfig | None:
        """Read the complete active product configuration."""
        return await get_active_product_config(self._require_session())

    async def ingest_product_config_locked(
        self, *, candidate: ProductConfigCandidate, actor_id: UUID
    ) -> ProductConfigVersion:
        """Persist a candidate after application-level locking and authorization."""
        return await ingest_product_config_locked(
            self._require_session(), candidate=candidate, actor_id=actor_id
        )

    async def activate_product_config_locked(
        self, command: ProductConfigActivationCommand
    ) -> ProductConfigActivationResult:
        """Activate a stored configuration inside this transaction."""
        return await activate_product_config_locked(
            self._require_session(),
            command,
            after_pointer_switched=self._after_product_config_pointer_switched,
        )

    async def read_ledger_history(
        self,
        *,
        member_id: UUID,
        limit: int,
        cursor: LedgerHistoryCursor | None,
    ) -> LedgerHistoryPage:
        """Read an immutable ledger page."""
        return await read_ledger_history(
            self._require_session(), member_id=member_id, limit=limit, cursor=cursor
        )

    async def set_repeatable_read(self) -> None:
        """Set repeatable-read isolation before the first transaction query."""
        await self._require_session().execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )

    async def reconcile_economy(self) -> tuple[ReconciliationMismatch, ...]:
        """Return cache-to-ledger mismatches without modifying state."""
        return await reconcile_economy(self._require_session())

    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel:
        """Resolve a member against the current product configuration."""
        return await resolve_member_level(self._require_session(), member_id)

    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None:
        """Append a workflow marker without exposing the SQLAlchemy session."""
        self._require_session().add(
            AuditEventModel(
                actor_member_id=actor_member_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_json=None,
                after_json=None,
                reason=reason,
            )
        )

    async def save_member(self, member: Member) -> None:
        """Persist the member role and status in the locked row."""
        model = await self._require_session().get(MemberModel, member.id)
        if model is None:
            msg = "Member record does not exist."
            raise LookupError(msg)
        model.role = member.role.value
        model.status = member.status.value

    async def flush_member_changes(self) -> None:
        """Flush the member UPDATE while retaining the open transaction."""
        await self._require_session().flush()

    async def append_member_audit(
        self,
        *,
        actor_id: UUID,
        before: Member,
        after: Member,
        reason: str | None,
    ) -> None:
        """Append a security-state audit event."""
        self._require_session().add(
            AuditEventModel(
                actor_member_id=actor_id,
                action="member_access_changed",
                entity_type="member",
                entity_id=str(after.id),
                before_json=_member_security_json(before),
                after_json=_member_security_json(after),
                reason=reason,
            )
        )

    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None:
        """Stage a fully populated update receipt."""
        self._require_session().add(
            ProcessedTelegramUpdateModel(
                update_id=update_id,
                update_type=update_type,
                actor_member_id=actor_id,
                outcome_code=outcome_code,
            )
        )

    async def commit(self) -> None:
        """Commit all staged effects and mark the context complete."""
        await self._require_session().commit()
        self._committed = True

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            msg = "Unit of work has not been entered."
            raise RuntimeError(msg)
        return self._session


def _to_domain(model: MemberModel) -> Member:
    return Member(
        id=model.id,
        telegram_user_id=model.telegram_user_id,
        role=MemberRole(model.role),
        status=MemberStatus(model.status),
    )


def _member_security_json(member: Member) -> dict[str, str]:
    return {"id": str(member.id), "role": member.role.value, "status": member.status.value}
