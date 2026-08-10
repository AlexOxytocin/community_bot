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
from community_bot.infrastructure.db import registration as registration_store
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
    import datetime
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
    from community_bot.application.registration import (
        InvitationSnapshot,
        ProfileData,
        RegistrationContext,
    )
    from community_bot.domain.economy import ProductConfigCandidate, ResolvedLevel
    from community_bot.domain.registration import (
        ModerationDecision,
        ProfileField,
        RegistrationStep,
    )


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

    async def acquire_registration_identity_gate(self, telegram_user_id: int) -> None:
        """Serialize registration and profile mutations for one Telegram identity."""
        await registration_store.acquire_registration_identity_gate(
            self._require_session(),
            telegram_user_id,
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

    async def get_receipt_outcome(self, update_id: int) -> str | None:
        """Return the exact stored outcome for one Telegram update."""
        receipt = await self.get_receipt(update_id)
        return None if receipt is None else receipt.outcome_code

    async def add_registration_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None:
        """Stage a complete receipt for a registration transport update."""
        await self.add_receipt(
            update_id=update_id,
            update_type=update_type,
            actor_id=actor_id,
            outcome_code=outcome_code,
        )

    async def create_invitation(
        self,
        *,
        code_hash: str,
        created_by_member_id: UUID,
        intended_telegram_user_id: int | None,
        max_uses: int,
        expires_at: datetime.datetime | None,
    ) -> UUID:
        """Insert one hashed invitation."""
        return await registration_store.create_invitation(
            self._require_session(),
            code_hash=code_hash,
            created_by_member_id=created_by_member_id,
            intended_telegram_user_id=intended_telegram_user_id,
            max_uses=max_uses,
            expires_at=expires_at,
        )

    async def revoke_invitation(self, invitation_id: UUID) -> bool:
        """Revoke one invitation under row lock."""
        return await registration_store.revoke_invitation(self._require_session(), invitation_id)

    async def lock_invitation_by_hash(self, code_hash: str) -> InvitationSnapshot | None:
        """Lock one invitation by its irreversible token hash."""
        return await registration_store.lock_invitation_by_hash(self._require_session(), code_hash)

    async def get_registration_context(
        self,
        telegram_user_id: int,
        *,
        for_update: bool,
    ) -> RegistrationContext | None:
        """Read one complete registration context."""
        return await registration_store.get_registration_context(
            self._require_session(),
            telegram_user_id,
            for_update=for_update,
        )

    async def create_pending_registration(
        self,
        *,
        invitation: InvitationSnapshot,
        telegram_user_id: int,
        telegram_username: str | None,
        telegram_display_name: str,
    ) -> RegistrationContext:
        """Consume an invitation and create a pending registration."""
        return await registration_store.create_pending_registration(
            self._require_session(),
            invitation=invitation,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            telegram_display_name=telegram_display_name,
        )

    async def update_registration_username(
        self,
        *,
        member_id: UUID,
        telegram_username: str | None,
    ) -> None:
        """Update a member's mutable Telegram username."""
        await registration_store.update_registration_username(
            self._require_session(),
            member_id=member_id,
            telegram_username=telegram_username,
        )

    async def resume_registration_conversation(self, member_id: UUID) -> None:
        """Resume a registration draft paused by the Telegram user."""
        await registration_store.resume_registration_conversation(
            self._require_session(), member_id
        )

    async def cancel_conversation(self, member_id: UUID) -> bool:
        """Pause or discard the current conversation without deleting profile data."""
        return await registration_store.cancel_conversation(self._require_session(), member_id)

    async def save_registration_answer(
        self,
        *,
        member_id: UUID,
        field: str,
        value: object,
        next_step: RegistrationStep,
    ) -> RegistrationContext:
        """Save one registration answer and advance the state."""
        return await registration_store.save_registration_answer(
            self._require_session(),
            member_id=member_id,
            field=field,
            value=value,
            next_step=next_step,
        )

    async def submit_registration(self, member_id: UUID) -> RegistrationContext:
        """Submit one complete registration draft."""
        return await registration_store.submit_registration(self._require_session(), member_id)

    async def reopen_rejected_registration(self, member_id: UUID) -> RegistrationContext:
        """Reopen one rejected registration."""
        return await registration_store.reopen_rejected_registration(
            self._require_session(), member_id
        )

    async def lock_registration_application(self, member_id: UUID) -> RegistrationContext:
        """Lock one complete registration application."""
        return await registration_store.lock_registration_application(
            self._require_session(), member_id
        )

    async def decide_registration(
        self,
        *,
        member_id: UUID,
        actor_member_id: UUID,
        decision: ModerationDecision,
        comment: str | None,
    ) -> RegistrationContext:
        """Persist one registration moderation decision."""
        return await registration_store.decide_registration(
            self._require_session(),
            member_id=member_id,
            actor_member_id=actor_member_id,
            decision=decision,
            comment=comment,
        )

    async def list_submitted_registrations(self, limit: int) -> tuple[RegistrationContext, ...]:
        """Return submitted registrations for the moderation queue."""
        return await registration_store.list_submitted_registrations(self._require_session(), limit)

    async def get_own_profile(self, telegram_user_id: int) -> ProfileData | None:
        """Return one active member's own profile."""
        return await registration_store.get_own_profile(self._require_session(), telegram_user_id)

    async def get_conversation_expectation(self, telegram_user_id: int) -> tuple[str, str] | None:
        """Return the flow and step expected from the next text update."""
        return await registration_store.get_conversation_expectation(
            self._require_session(), telegram_user_id
        )

    async def begin_profile_edit(self, member_id: UUID, field: ProfileField) -> None:
        """Persist the expected profile edit field."""
        await registration_store.begin_profile_edit(self._require_session(), member_id, field)

    async def save_profile_edit(
        self,
        *,
        member_id: UUID,
        expected_field: ProfileField,
        value: object,
    ) -> None:
        """Save one owned profile field through the expected-step gate."""
        await registration_store.save_profile_edit(
            self._require_session(),
            member_id=member_id,
            expected_field=expected_field,
            value=value,
        )

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
