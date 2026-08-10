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
from community_bot.infrastructure.db import catalog as catalog_store
from community_bot.infrastructure.db import registration as registration_store
from community_bot.infrastructure.db import tasks as task_store
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

    from community_bot.application.catalog import CatalogPage, CatalogQuery, CatalogTemplate
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
    from community_bot.application.tasks import PublishedTask, TaskDraft
    from community_bot.domain.catalog import TemplateDraft
    from community_bot.domain.economy import ProductConfigCandidate, ResolvedLevel
    from community_bot.domain.registration import (
        ModerationDecision,
        ProfileField,
        RegistrationStep,
    )
    from community_bot.domain.tasks import TaskStatus


class Database:
    """Own the process-level async engine and isolated session factory."""

    def __init__(self, database_url: str) -> None:
        """Create an engine without opening a connection eagerly."""
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def unit_of_work(  # noqa: PLR0913 - explicit fault checkpoints stay independently injectable.
        self,
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_economy_cache_flushed: Callable[[], None] | None = None,
        after_product_config_pointer_switched: Callable[[], None] | None = None,
        after_task_inserted: Callable[[], None] | None = None,
        after_task_outbox_staged: Callable[[], None] | None = None,
        after_task_receipt_staged: Callable[[], None] | None = None,
    ) -> SqlAlchemyUnitOfWork:
        """Create a fresh transactional unit of work."""
        return SqlAlchemyUnitOfWork(
            self._sessions,
            after_ledger_flushed=after_ledger_flushed,
            after_economy_cache_flushed=after_economy_cache_flushed,
            after_product_config_pointer_switched=after_product_config_pointer_switched,
            after_task_inserted=after_task_inserted,
            after_task_outbox_staged=after_task_outbox_staged,
            after_task_receipt_staged=after_task_receipt_staged,
        )

    async def dispose(self) -> None:
        """Release all engine resources."""
        await self.engine.dispose()


class SqlAlchemyUnitOfWork(FoundationUnitOfWork):
    """PostgreSQL implementation of the member-foundation transaction."""

    def __init__(  # noqa: PLR0913 - mirrors the explicit unit-of-work fault checkpoints.
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        after_ledger_flushed: Callable[[], None] | None = None,
        after_economy_cache_flushed: Callable[[], None] | None = None,
        after_product_config_pointer_switched: Callable[[], None] | None = None,
        after_task_inserted: Callable[[], None] | None = None,
        after_task_outbox_staged: Callable[[], None] | None = None,
        after_task_receipt_staged: Callable[[], None] | None = None,
    ) -> None:
        """Configure an isolated session factory."""
        self._sessions = sessions
        self._after_ledger_flushed = after_ledger_flushed
        self._after_economy_cache_flushed = after_economy_cache_flushed
        self._after_product_config_pointer_switched = after_product_config_pointer_switched
        self._after_task_inserted = after_task_inserted
        self._after_task_outbox_staged = after_task_outbox_staged
        self._after_task_receipt_staged = after_task_receipt_staged
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

    async def acquire_catalog_mutation_gate(self) -> None:
        """Serialize catalog mutations after the exact update gate."""
        await catalog_store.acquire_catalog_mutation_gate(self._require_session())

    async def acquire_task_identity_gate(self, telegram_user_id: int) -> None:
        """Serialize task mutations for one Telegram identity."""
        await task_store.acquire_task_identity_gate(self._require_session(), telegram_user_id)

    async def acquire_task_command_gate(self, command_id: UUID) -> None:
        """Serialize one task publication or cancellation command."""
        await task_store.acquire_task_command_gate(self._require_session(), command_id)

    async def catalog_page(self, *, query: CatalogQuery, level: int) -> CatalogPage:
        """Return one level-aware keyset catalog page."""
        return await catalog_store.catalog_page(self._require_session(), query=query, level=level)

    async def catalog_template(self, template_id: UUID) -> CatalogTemplate | None:
        """Read one exact historical template version."""
        return await catalog_store.catalog_template(self._require_session(), template_id)

    async def template_for_creation(
        self, *, template_id: UUID, level: int
    ) -> CatalogTemplate | None:
        """Read one currently available exact template version."""
        return await catalog_store.template_for_creation(
            self._require_session(), template_id=template_id, level=level
        )

    async def lock_template_versions(self, code: str) -> tuple[CatalogTemplate, ...]:
        """Lock all versions of a logical template."""
        return await catalog_store.lock_template_versions(self._require_session(), code)

    async def insert_template_version(
        self, *, draft: TemplateDraft, version: int
    ) -> CatalogTemplate:
        """Insert one immutable active template version."""
        return await catalog_store.insert_template_version(
            self._require_session(), draft=draft, version=version
        )

    async def set_catalog_category_active(self, *, code: str, enabled: bool) -> UUID:
        """Toggle one catalog category."""
        return await catalog_store.set_catalog_category_active(
            self._require_session(), code=code, enabled=enabled
        )

    async def set_catalog_template_active(self, *, code: str, enabled: bool) -> CatalogTemplate:
        """Toggle the latest version of one logical template."""
        return await catalog_store.set_catalog_template_active(
            self._require_session(), code=code, enabled=enabled
        )

    async def create_task_draft(self, *, creator_id: UUID, template_id: UUID) -> TaskDraft:
        """Create a new current persistent task draft."""
        return await task_store.create_task_draft(
            self._require_session(), creator_id=creator_id, template_id=template_id
        )

    async def get_current_task_draft(self, creator_id: UUID) -> TaskDraft | None:
        """Read the selected unfinished task draft."""
        return await task_store.get_current_task_draft(self._require_session(), creator_id)

    async def get_task_draft(self, draft_id: UUID) -> TaskDraft | None:
        """Read one persistent task draft."""
        return await task_store.get_task_draft(self._require_session(), draft_id)

    async def lock_task_draft(self, draft_id: UUID) -> TaskDraft | None:
        """Lock one task draft."""
        return await task_store.lock_task_draft(self._require_session(), draft_id)

    async def select_task_draft(self, *, creator_id: UUID, draft_id: UUID) -> TaskDraft:
        """Select one owned unfinished draft as current."""
        return await task_store.select_task_draft(
            self._require_session(), creator_id=creator_id, draft_id=draft_id
        )

    async def save_task_draft(self, draft: TaskDraft) -> TaskDraft:
        """Persist one validated task draft snapshot."""
        return await task_store.save_task_draft(self._require_session(), draft)

    async def delete_task_draft(self, draft_id: UUID) -> None:
        """Delete one unfinished task creation draft."""
        await task_store.delete_task_draft(self._require_session(), draft_id)

    async def task_by_publish_command(self, command_id: UUID) -> PublishedTask | None:
        """Read the task created by one publish command."""
        return await task_store.task_by_publish_command(self._require_session(), command_id)

    async def insert_published_task(
        self, *, draft: TaskDraft, template: CatalogTemplate
    ) -> PublishedTask:
        """Insert one immutable member task snapshot."""
        task = await task_store.insert_published_task(
            self._require_session(), draft=draft, template=template
        )
        if self._after_task_inserted is not None:
            self._after_task_inserted()
        return task

    async def get_task(self, task_id: UUID) -> PublishedTask | None:
        """Read one task snapshot."""
        return await task_store.get_task(self._require_session(), task_id)

    async def lock_task(self, task_id: UUID) -> PublishedTask | None:
        """Lock one task snapshot."""
        return await task_store.lock_task(self._require_session(), task_id)

    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask:
        """Persist a creation-owned task status transition."""
        return await task_store.save_task_status(
            self._require_session(), task_id=task_id, status=status
        )

    async def list_owned_tasks(
        self,
        *,
        creator_id: UUID,
        limit: int,
        status: TaskStatus | None,
        before_created_at: datetime.datetime | None,
        before_id: UUID | None,
    ) -> tuple[PublishedTask, ...]:
        """Return only tasks created by one member."""
        return await task_store.list_owned_tasks(
            self._require_session(),
            creator_id=creator_id,
            limit=limit,
            status=status,
            before_created_at=before_created_at,
            before_id=before_id,
        )

    async def add_task_outbox(
        self, *, event_type: str, task: PublishedTask, business_key: str
    ) -> None:
        """Stage one task lifecycle outbox event."""
        await task_store.add_task_outbox(
            self._require_session(),
            event_type=event_type,
            task=task,
            business_key=business_key,
        )
        await self._require_session().flush()
        if self._after_task_outbox_staged is not None:
            self._after_task_outbox_staged()

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
        await self._require_session().flush()

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
        await self._require_session().flush()

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
        await self._require_session().flush()
        if update_type == "task_workflow" and self._after_task_receipt_staged is not None:
            self._after_task_receipt_staged()

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
