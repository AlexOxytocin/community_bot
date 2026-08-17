"""Managed asynchronous database lifecycle and unit of work."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from community_bot.application.member_foundation import FoundationUnitOfWork, UpdateReceipt
from community_bot.application.tasks import AdministratorOption
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.infrastructure.db import assignments as assignment_store
from community_bot.infrastructure.db import catalog as catalog_store
from community_bot.infrastructure.db import conversations as conversation_store
from community_bot.infrastructure.db import moderation as moderation_store
from community_bot.infrastructure.db import registration as registration_store
from community_bot.infrastructure.db import reputation as reputation_store
from community_bot.infrastructure.db import task_cancellations as cancellation_store
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
from community_bot.infrastructure.db.initial_admin import (
    SqlAlchemyInitialAdministratorUnitOfWork,
)
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    MemberModel,
    ProcessedTelegramUpdateModel,
    TestRunParticipantModel,
    WebSessionModel,
)
from community_bot.infrastructure.db.moderation import SqlAlchemyModerationMutation

_UPDATE_LOCK_NAMESPACE = "telegram_update"

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Sequence
    from types import TracebackType
    from uuid import UUID

    from community_bot.application.assignments import AssignmentCard
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
    from community_bot.application.reputation import (
        KarmaAggregate,
        KarmaDraft,
        KarmaVoteResult,
        LeaderboardCursor,
        LeaderboardPage,
        MemberCatalogCursor,
        MemberCatalogPage,
        PersonalStatistics,
        RawKarmaVote,
        SafeProfile,
    )
    from community_bot.application.tasks import (
        CommunityPublicationRequest,
        OwnedTaskCard,
        PublishedTask,
        TaskCancellationResponse,
        TaskCategoryOption,
        TaskDraft,
    )
    from community_bot.domain.assignments import (
        Assignment,
        AssignmentStatus,
        ResultVersion,
        SubmissionDraft,
    )
    from community_bot.domain.catalog import TemplateDraft
    from community_bot.domain.economy import ProductConfigCandidate, ResolvedLevel
    from community_bot.domain.moderation import RestrictedAction
    from community_bot.domain.registration import (
        ModerationDecision,
        ProfileField,
        RegistrationStep,
    )
    from community_bot.domain.reputation import KarmaStep
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
        after_assignment_inserted: Callable[[], None] | None = None,
        after_assignment_result_staged: Callable[[], None] | None = None,
        after_assignment_outbox_staged: Callable[[], None] | None = None,
        after_assignment_receipt_staged: Callable[[], None] | None = None,
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
            after_assignment_inserted=after_assignment_inserted,
            after_assignment_result_staged=after_assignment_result_staged,
            after_assignment_outbox_staged=after_assignment_outbox_staged,
            after_assignment_receipt_staged=after_assignment_receipt_staged,
        )

    def initial_administrator_unit_of_work(
        self,
        *,
        after_member_flushed: Callable[[], None] | None = None,
        after_audit_flushed: Callable[[], None] | None = None,
    ) -> SqlAlchemyInitialAdministratorUnitOfWork:
        """Create a fresh transaction for one-time administrator bootstrap."""
        return SqlAlchemyInitialAdministratorUnitOfWork(
            self._sessions,
            after_member_flushed=after_member_flushed,
            after_audit_flushed=after_audit_flushed,
        )

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Expose isolated sessions to infrastructure adapters in the same process."""
        return self._sessions

    async def dispose(self) -> None:
        """Release all engine resources."""
        await self.engine.dispose()

    async def create_web_session(
        self,
        *,
        telegram_user_id: int,
        token_digest: bytes,
        authenticated_at: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> UUID | None:
        """Persist one session for an existing Telegram identity."""
        async with self._sessions.begin() as session:
            member_id = await session.scalar(
                select(MemberModel.id).where(MemberModel.telegram_user_id == telegram_user_id)
            )
            if member_id is None:
                return None
            session.add(
                WebSessionModel(
                    token_digest=token_digest,
                    member_id=member_id,
                    authenticated_at=authenticated_at,
                    expires_at=expires_at,
                )
            )
        return member_id

    async def web_session_member_id(
        self, *, token_digest: bytes, now: datetime.datetime
    ) -> tuple[UUID, datetime.datetime] | None:
        """Resolve one live, unrevoked session to internal identity."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(WebSessionModel.member_id, WebSessionModel.authenticated_at).where(
                        WebSessionModel.token_digest == token_digest,
                        WebSessionModel.revoked_at.is_(None),
                        WebSessionModel.expires_at > now,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            return row.member_id, row.authenticated_at

    async def revoke_web_session(self, *, token_digest: bytes, now: datetime.datetime) -> None:
        """Atomically revoke a currently live session, if any."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(WebSessionModel)
                .where(
                    WebSessionModel.token_digest == token_digest,
                    WebSessionModel.revoked_at.is_(None),
                    WebSessionModel.expires_at > now,
                )
                .values(revoked_at=now)
            )


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
        after_assignment_inserted: Callable[[], None] | None = None,
        after_assignment_result_staged: Callable[[], None] | None = None,
        after_assignment_outbox_staged: Callable[[], None] | None = None,
        after_assignment_receipt_staged: Callable[[], None] | None = None,
    ) -> None:
        """Configure an isolated session factory."""
        self._sessions = sessions
        self._after_ledger_flushed = after_ledger_flushed
        self._after_economy_cache_flushed = after_economy_cache_flushed
        self._after_product_config_pointer_switched = after_product_config_pointer_switched
        self._after_task_inserted = after_task_inserted
        self._after_task_outbox_staged = after_task_outbox_staged
        self._after_task_receipt_staged = after_task_receipt_staged
        self._after_assignment_inserted = after_assignment_inserted
        self._after_assignment_result_staged = after_assignment_result_staged
        self._after_assignment_outbox_staged = after_assignment_outbox_staged
        self._after_assignment_receipt_staged = after_assignment_receipt_staged
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

    async def acquire_reputation_pair_gate(self, first_id: UUID, second_id: UUID) -> None:
        """Serialize all reputation mutations for one unordered member pair."""
        await reputation_store.acquire_pair_gate(self._require_session(), first_id, second_id)

    async def get_text_flow(self, member_id: UUID, *, for_update: bool = False):  # noqa: ANN201
        """Read or lock the member's one free-text owner."""
        return await conversation_store.get_text_flow(
            self._require_session(), member_id, for_update=for_update
        )

    async def claim_text_flow(  # noqa: ANN201, PLR0913
        self,
        *,
        member_id: UUID,
        flow_type: str,
        step: str,
        reference_id: UUID | None,
        revision: int,
        payload: dict[str, object] | None = None,
    ):
        """Select the only free-text owner in the current transaction."""
        return await conversation_store.claim_text_flow(
            self._require_session(),
            member_id=member_id,
            flow_type=flow_type,
            step=step,
            reference_id=reference_id,
            revision=revision,
            payload=payload,
        )

    async def clear_text_flow(
        self,
        *,
        member_id: UUID,
        flow_type: str,
        reference_id: UUID | None = None,
    ) -> bool:
        """Clear only the selected free-text owner."""
        return await conversation_store.clear_text_flow(
            self._require_session(),
            member_id=member_id,
            flow_type=flow_type,
            reference_id=reference_id,
        )

    @property
    def economy(self) -> SqlAlchemyEconomyMutation:
        """Return the economy adapter bound to this transaction."""
        return SqlAlchemyEconomyMutation(
            self._require_session(),
            after_ledger_flushed=self._after_ledger_flushed,
            after_cache_flushed=self._after_economy_cache_flushed,
        )

    @property
    def moderation(self) -> SqlAlchemyModerationMutation:
        """Return the moderation adapter bound to this transaction."""
        return SqlAlchemyModerationMutation(
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

    async def acquire_assignment_task_gate(self, task_id: UUID) -> None:
        """Serialize assignment mutations of one task aggregate."""
        await assignment_store.acquire_task_gate(self._require_session(), task_id)

    async def acquire_assignment_limit_gate(self, member_id: UUID) -> None:
        """Serialize active-limit decisions for one performer."""
        await assignment_store.acquire_active_limit_gate(self._require_session(), member_id)

    async def count_active_assignments(self, performer_id: UUID) -> int:
        """Count assignments occupying the active limit."""
        return await assignment_store.count_active(self._require_session(), performer_id)

    async def create_assignment(
        self, *, task_id: UUID, performer_id: UUID, slots: int
    ) -> Assignment:
        """Claim the lowest free task slot."""
        assignment = await assignment_store.create_assignment(
            self._require_session(), task_id=task_id, performer_id=performer_id, slots=slots
        )
        if self._after_assignment_inserted is not None:
            self._after_assignment_inserted()
        return assignment

    async def lock_assignment(self, assignment_id: UUID) -> Assignment | None:
        """Lock one assignment."""
        return await assignment_store.lock_assignment(self._require_session(), assignment_id)

    async def get_assignment(self, assignment_id: UUID) -> Assignment | None:
        """Read one assignment without locking it."""
        return await assignment_store.get_assignment(self._require_session(), assignment_id)

    async def list_assignments(self, performer_id: UUID) -> tuple[Assignment, ...]:
        """List one performer's assignments."""
        return await assignment_store.list_assignments(self._require_session(), performer_id)

    async def list_assignment_cards(  # noqa: PLR0913
        self,
        performer_id: UUID,
        *,
        limit: int = 50,
        statuses: tuple[str, ...] | None = None,
        before_order_at: datetime.datetime | None = None,
        before_id: UUID | None = None,
        order_by_reviewed_at: bool = False,
    ) -> tuple[AssignmentCard, ...]:
        """List performer assignment cards."""
        return await assignment_store.list_assignment_cards(
            self._require_session(),
            performer_id,
            limit=limit,
            statuses=statuses,
            before_order_at=before_order_at,
            before_id=before_id,
            order_by_reviewed_at=order_by_reviewed_at,
        )

    async def get_assignment_card(
        self, performer_id: UUID, assignment_id: UUID
    ) -> AssignmentCard | None:
        """Return one exact performer assignment card."""
        return await assignment_store.get_assignment_card(
            self._require_session(), performer_id, assignment_id
        )

    async def list_review_cards(self, actor_id: UUID):  # noqa: ANN201
        """List reviewable assignment cards for one actor."""
        return await assignment_store.list_review_cards(self._require_session(), actor_id)

    async def list_task_assignments(
        self, task_id: UUID, *, for_update: bool = False
    ) -> tuple[Assignment, ...]:
        """List or lock all assignment history of one task."""
        return await assignment_store.list_task_assignments(
            self._require_session(), task_id, for_update=for_update
        )

    async def cancel_assignment(self, assignment_id: UUID, reason: str) -> Assignment:
        """Cancel an accepted assignment."""
        return await assignment_store.cancel_assignment(
            self._require_session(), assignment_id, reason
        )

    async def mark_reviewer_required(self, assignment_id: UUID) -> Assignment:
        """Pause a submitted community result until reviewer replacement."""
        return await assignment_store.mark_reviewer_required(self._require_session(), assignment_id)

    async def append_assignment_result(
        self,
        *,
        assignment_id: UUID,
        command_id: UUID,
        payload: dict[str, object],
        now: datetime.datetime,
    ) -> ResultVersion:
        """Append one immutable result version."""
        result = await assignment_store.append_result(
            self._require_session(),
            assignment_id=assignment_id,
            command_id=command_id,
            payload=payload,
            now=now,
        )
        if self._after_assignment_result_staged is not None:
            self._after_assignment_result_staged()
        return result

    async def get_assignment_result(self, result_id: UUID) -> ResultVersion | None:
        """Read one immutable assignment result."""
        return await assignment_store.get_result(self._require_session(), result_id)

    async def get_submission_draft(
        self, draft_id: UUID, *, for_update: bool = False
    ) -> SubmissionDraft | None:
        """Read or lock one durable result-input draft."""
        return await assignment_store.get_submission_draft(
            self._require_session(), draft_id, for_update=for_update
        )

    async def delete_submission_draft(self, draft_id: UUID) -> None:
        """Delete one unsubmitted result-input draft."""
        await assignment_store.delete_submission_draft(self._require_session(), draft_id)

    async def create_or_get_submission_draft(
        self, *, assignment_id: UUID, performer_id: UUID
    ) -> SubmissionDraft:
        """Create or resume one assignment result-input draft."""
        return await assignment_store.create_or_get_submission_draft(
            self._require_session(), assignment_id=assignment_id, performer_id=performer_id
        )

    async def save_submission_draft_payload(
        self,
        *,
        draft_id: UUID,
        expected_revision: int,
        payload: dict[str, object],
    ) -> SubmissionDraft:
        """Persist a validated preview payload."""
        return await assignment_store.save_submission_draft_payload(
            self._require_session(),
            draft_id=draft_id,
            expected_revision=expected_revision,
            payload=payload,
        )

    async def complete_submission_draft(
        self, *, draft_id: UUID, result_id: UUID
    ) -> SubmissionDraft:
        """Mark a result-input draft as confirmed."""
        return await assignment_store.complete_submission_draft(
            self._require_session(), draft_id=draft_id, result_id=result_id
        )

    async def set_assignment_decision(
        self,
        *,
        assignment_id: UUID,
        status: AssignmentStatus,
        command_id: UUID,
        outcome: str,
        now: datetime.datetime,
    ) -> Assignment:
        """Persist one assignment review transition."""
        return await assignment_store.set_decision(
            self._require_session(),
            assignment_id=assignment_id,
            status=status,
            command_id=command_id,
            outcome=outcome,
            now=now,
        )

    async def open_assignment_dispute(
        self,
        *,
        assignment_id: UUID,
        performer_id: UUID,
        command_id: UUID,
        comment: str,
    ) -> UUID:
        """Insert one immutable private dispute opening."""
        return await assignment_store.open_dispute(
            self._require_session(),
            assignment_id=assignment_id,
            performer_id=performer_id,
            command_id=command_id,
            comment=comment,
        )

    async def append_assignment_reliability(
        self,
        assignment_id: UUID,
        event_type: str,
        actor_id: UUID | None,
        reason: str | None,
    ) -> None:
        """Append an assignment reliability fact."""
        await assignment_store.append_reliability(
            self._require_session(), assignment_id, event_type, actor_id, reason
        )

    async def recompute_interaction_alert(self, assignment_id: UUID) -> None:
        """Refresh one pair alert after a settlement effect."""
        await moderation_store.recompute_interaction_alert(self._require_session(), assignment_id)

    async def add_assignment_outbox(
        self, *, assignment: Assignment, event_type: str, business_key: str
    ) -> None:
        """Stage a privacy-minimal assignment event."""
        await assignment_store.add_outbox(
            self._require_session(),
            assignment=assignment,
            event_type=event_type,
            business_key=business_key,
        )
        if self._after_assignment_outbox_staged is not None:
            self._after_assignment_outbox_staged()

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

    async def list_task_categories(
        self, *, actor_role: MemberRole
    ) -> tuple[TaskCategoryOption, ...]:
        """Return active free-form categories visible to the actor."""
        return await task_store.list_task_categories(self._require_session(), actor_role=actor_role)

    async def task_category_for_creation(
        self, *, category_id: UUID, actor_role: MemberRole
    ) -> TaskCategoryOption | None:
        """Read one free-form category only if the actor may use it."""
        return await task_store.task_category_for_creation(
            self._require_session(),
            category_id=category_id,
            actor_role=actor_role,
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

    async def create_task_draft(
        self, *, creator_id: UUID, template_id: UUID | None, origin: str = "member"
    ) -> TaskDraft:
        """Create a new current persistent task draft."""
        return await task_store.create_task_draft(
            self._require_session(),
            creator_id=creator_id,
            template_id=template_id,
            origin=origin,
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

    async def list_active_administrators(
        self, *, exclude_id: UUID, test_run_id: UUID | None
    ) -> tuple[AdministratorOption, ...]:
        """Return active administrators except one creator."""
        statement = select(MemberModel).where(
            MemberModel.role == MemberRole.ADMINISTRATOR.value,
            MemberModel.status == MemberStatus.ACTIVE.value,
            MemberModel.id != exclude_id,
        )
        if test_run_id is not None:
            statement = statement.join(
                TestRunParticipantModel,
                TestRunParticipantModel.member_id == MemberModel.id,
            ).where(
                TestRunParticipantModel.run_id == test_run_id,
                TestRunParticipantModel.is_active.is_(True),
            )
        models = (
            await self._require_session().scalars(
                statement.order_by(MemberModel.display_name, MemberModel.id)
            )
        ).all()
        return tuple(AdministratorOption(model.id, model.display_name) for model in models)

    async def list_pending_community_publications(
        self, *, actor_id: UUID, limit: int
    ) -> tuple[CommunityPublicationRequest, ...]:
        """Return community drafts awaiting superadministrator confirmation."""
        return await task_store.list_pending_community_publications(
            self._require_session(),
            actor_id=actor_id,
            limit=limit,
        )

    async def delete_task_draft(self, draft_id: UUID) -> None:
        """Delete one unfinished task creation draft."""
        await task_store.delete_task_draft(self._require_session(), draft_id)

    async def task_by_publish_command(self, command_id: UUID) -> PublishedTask | None:
        """Read the task created by one publish command."""
        return await task_store.task_by_publish_command(self._require_session(), command_id)

    async def insert_published_task(
        self, *, draft: TaskDraft, template: CatalogTemplate | None
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

    async def member_display_name(self, member_id: UUID) -> str:
        """Return the current profile label used by an author preview."""
        return await task_store.member_display_name(self._require_session(), member_id)

    async def lock_task(self, task_id: UUID) -> PublishedTask | None:
        """Lock one task snapshot."""
        return await task_store.lock_task(self._require_session(), task_id)

    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask:
        """Persist a creation-owned task status transition."""
        return await task_store.save_task_status(
            self._require_session(), task_id=task_id, status=status
        )

    async def close_task_for_new_performers(
        self, *, task_id: UUID, now: datetime.datetime
    ) -> PublishedTask:
        """Persist that creator closed intake for new performers."""
        return await task_store.close_task_for_new_performers(
            self._require_session(),
            task_id=task_id,
            now=now,
        )

    async def save_community_reviewer(
        self,
        *,
        task_id: UUID,
        reviewer_id: UUID,
        now: datetime.datetime,
    ) -> PublishedTask:
        """Replace a community reviewer and reopen assignments waiting for one."""
        return await task_store.save_community_reviewer(
            self._require_session(),
            task_id=task_id,
            reviewer_id=reviewer_id,
            now=now,
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

    async def list_owned_task_cards(  # noqa: PLR0913
        self,
        *,
        creator_id: UUID,
        limit: int,
        status: TaskStatus | None,
        before_created_at: datetime.datetime | None,
        before_id: UUID | None,
        creator_only: bool = False,
        order_by_updated_at: bool = False,
    ) -> tuple[OwnedTaskCard, ...]:
        """Return owned tasks with occupancy and cancellation context."""
        return await cancellation_store.list_owned_task_cards(
            self._require_session(),
            creator_id=creator_id,
            limit=limit,
            status=status,
            before_created_at=before_created_at,
            before_id=before_id,
            creator_only=creator_only,
            order_by_updated_at=order_by_updated_at,
        )

    async def get_owned_task_card(self, *, task_id: UUID, owner_id: UUID) -> OwnedTaskCard | None:
        """Return one exact owned card without page-size coupling."""
        return await cancellation_store.get_owned_task_card(
            self._require_session(), task_id=task_id, owner_id=owner_id
        )

    async def get_pending_task_cancellation(self, task_id: UUID) -> UUID | None:
        """Return the pending request identity for one task."""
        return await cancellation_store.get_pending_request(self._require_session(), task_id)

    async def obsolete_pending_task_cancellation(
        self, task_id: UUID, reason: str, now: datetime.datetime
    ) -> bool:
        """Make an active request obsolete after work starts or the deadline passes."""
        return await cancellation_store.obsolete_pending_request(
            self._require_session(), task_id, reason, now
        )

    async def has_declined_task_cancellation(self, task_id: UUID) -> bool:
        """Return whether cancellation was already declined for this task."""
        return await cancellation_store.has_declined_request(self._require_session(), task_id)

    async def create_task_cancellation(
        self, *, task_id: UUID, creator_id: UUID, assignments: Sequence[Assignment]
    ) -> UUID:
        """Create a request and one durable response per active assignment."""
        return await cancellation_store.create_request(
            self._require_session(),
            task_id=task_id,
            creator_id=creator_id,
            assignments=tuple(assignments),
        )

    async def get_task_cancellation_response(
        self, response_id: UUID, *, for_update: bool = False
    ) -> TaskCancellationResponse | None:
        """Read or lock one cancellation response context."""
        return await cancellation_store.get_response(
            self._require_session(), response_id, for_update=for_update
        )

    async def answer_task_cancellation(
        self, *, response_id: UUID, accepted: bool, now: datetime.datetime
    ) -> TaskCancellationResponse:
        """Persist one performer's response."""
        return await cancellation_store.answer_response(
            self._require_session(), response_id=response_id, accepted=accepted, now=now
        )

    async def task_cancellation_all_accepted(self, request_id: UUID) -> bool:
        """Return whether all response rows accepted cancellation."""
        return await cancellation_store.all_accepted(self._require_session(), request_id)

    async def task_cancellation_all_answered(self, request_id: UUID) -> bool:
        """Return whether no cancellation response is still pending."""
        return await cancellation_store.all_answered(self._require_session(), request_id)

    async def resolve_task_cancellation(
        self, *, request_id: UUID, status: str, reason: str, now: datetime.datetime
    ) -> None:
        """Resolve a cancellation request and remaining response rows."""
        await cancellation_store.resolve_request(
            self._require_session(),
            request_id=request_id,
            status=status,
            reason=reason,
            now=now,
        )

    async def cancel_assignment_by_creator(
        self, assignment_id: UUID, creator_id: UUID, reason: str
    ) -> None:
        """Cancel an assignment without penalizing performer reliability."""
        await cancellation_store.cancel_assignment_by_creator(
            self._require_session(), assignment_id, creator_id, reason
        )

    async def add_task_cancellation_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
        business_key: str,
    ) -> None:
        """Stage a cancellation-specific notification event."""
        await cancellation_store.add_outbox(
            self._require_session(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            business_key=business_key,
        )

    async def list_available_tasks(
        self,
        *,
        performer_id: UUID,
        level: int,
        limit: int,
        cursor_task_id: UUID | None,
        now: datetime.datetime,
    ) -> tuple[PublishedTask, ...]:
        """Return the stable discovery page for one performer."""
        return await task_store.list_available_tasks(
            self._require_session(),
            performer_id=performer_id,
            level=level,
            limit=limit,
            cursor_task_id=cursor_task_id,
            now=now,
        )

    async def ensure_task_test_access(self, *, task_id: UUID, member_id: UUID) -> None:
        """Enforce the test-scope boundary for direct task commands."""
        await task_store.ensure_test_access(
            self._require_session(), task_id=task_id, member_id=member_id
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

    async def add_registration_approved_outbox(self, member_id: UUID) -> None:
        """Stage one durable notification for a newly approved member."""
        await registration_store.add_registration_approved_outbox(
            self._require_session(), member_id
        )

    async def list_submitted_registrations(self, limit: int) -> tuple[RegistrationContext, ...]:
        """Return submitted registrations for the moderation queue."""
        return await registration_store.list_submitted_registrations(self._require_session(), limit)

    async def get_own_profile(self, member_id: UUID) -> ProfileData | None:
        """Return one active member's own profile."""
        return await registration_store.get_own_profile(self._require_session(), member_id)

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
        if model is None:
            return None
        status = await moderation_store.effective_member_status(
            self._require_session(), model, materialize=True
        )
        return _to_domain(model, status=status)

    async def get_member(self, member_id: UUID) -> Member | None:
        """Read one security snapshot by member UUID."""
        model = await self._require_session().get(MemberModel, member_id)
        if model is None:
            return None
        status = await moderation_store.effective_member_status(
            self._require_session(), model, materialize=True
        )
        return _to_domain(model, status=status)

    async def ensure_moderation_action_allowed(
        self, member_id: UUID, action: RestrictedAction
    ) -> None:
        """Enforce current action restrictions under the member sanction gate."""
        await moderation_store.ensure_action_allowed(self._require_session(), member_id, action)

    async def karma_eligible(self, first_id: UUID, second_id: UUID) -> bool:
        """Return permanent eligibility derived from paid member work."""
        return await reputation_store.karma_eligible(self._require_session(), first_id, second_id)

    async def get_karma_draft(self, member_id: UUID, *, for_update: bool) -> KarmaDraft | None:
        """Read or lock one resumable karma conversation."""
        return await reputation_store.get_draft(
            self._require_session(), member_id, for_update=for_update
        )

    async def begin_karma_draft(self, member_id: UUID, target_id: UUID) -> KarmaDraft:
        """Create or resume a karma conversation."""
        return await reputation_store.begin_draft(self._require_session(), member_id, target_id)

    async def save_karma_draft(
        self,
        *,
        member_id: UUID,
        expected_revision: int,
        value: int | None,
        comment: str | None,
        step: KarmaStep,
    ) -> KarmaDraft:
        """Advance an exact karma conversation revision."""
        return await reputation_store.save_draft(
            self._require_session(),
            member_id=member_id,
            expected_revision=expected_revision,
            value=value,
            comment=comment,
            step=step,
        )

    async def delete_karma_draft(self, member_id: UUID, expected_revision: int) -> None:
        """Delete only an exact karma flow revision."""
        await reputation_store.delete_draft(self._require_session(), member_id, expected_revision)

    async def upsert_karma_vote(
        self,
        *,
        rater_id: UUID,
        target_id: UUID,
        value: int,
        comment: str,
        command_id: UUID,
    ) -> KarmaVoteResult:
        """Persist one current vote and immutable revision."""
        return await reputation_store.upsert_vote(
            self._require_session(),
            rater_id=rater_id,
            target_id=target_id,
            value=value,
            comment=comment,
            command_id=command_id,
        )

    async def generate_karma_signals(self, vote_id: UUID) -> None:
        """Create idempotent private signals after one vote revision."""
        await moderation_store.generate_karma_signals(self._require_session(), vote_id)

    async def karma_vote_by_command(self, command_id: UUID) -> KarmaVoteResult | None:
        """Read a vote revision by immutable command identity."""
        return await reputation_store.vote_by_command(self._require_session(), command_id)

    async def karma_aggregate(self, target_id: UUID) -> KarmaAggregate:
        """Return anonymous current karma aggregate."""
        return await reputation_store.karma_aggregate(self._require_session(), target_id)

    async def safe_profile(self, member_id: UUID) -> SafeProfile | None:
        """Return one privacy-safe profile projection."""
        return await reputation_store.safe_profile(self._require_session(), member_id)

    async def member_catalog_cursor(
        self, member_id: UUID, *, query: str | None
    ) -> MemberCatalogCursor | None:
        """Resolve one active member into the catalog keyset position."""
        return await reputation_store.member_catalog_cursor(
            self._require_session(), member_id, query=query
        )

    async def safe_profiles(
        self, *, limit: int, cursor: MemberCatalogCursor | None, query: str | None
    ) -> MemberCatalogPage:
        """Return the stable safe catalog of active profiles."""
        return await reputation_store.safe_profiles(
            self._require_session(), limit=limit, cursor=cursor, query=query
        )

    async def personal_statistics(self, member_id: UUID) -> PersonalStatistics:
        """Return personal contribution aggregates."""
        return await reputation_store.personal_statistics(self._require_session(), member_id)

    async def raw_karma(self, target_id: UUID) -> tuple[RawKarmaVote, ...]:
        """Return current raw karma after application authorization."""
        return await reputation_store.raw_karma(self._require_session(), target_id)

    async def leaderboard(self, *, limit: int, cursor: LeaderboardCursor | None) -> LeaderboardPage:
        """Return a ledger-authoritative leaderboard page."""
        return await reputation_store.leaderboard(
            self._require_session(), limit=limit, cursor=cursor
        )

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
        """Persist the member security state in the locked row."""
        model = await self._require_session().get(MemberModel, member.id)
        if model is None:
            msg = "Member record does not exist."
            raise LookupError(msg)
        model.role = member.role.value
        model.status = member.status.value
        model.permissions_json = sorted(member.permissions)

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
        if (
            update_type == "assignment_workflow"
            and self._after_assignment_receipt_staged is not None
        ):
            self._after_assignment_receipt_staged()

    async def commit(self) -> None:
        """Commit all staged effects and mark the context complete."""
        await self._require_session().commit()
        self._committed = True

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            msg = "Unit of work has not been entered."
            raise RuntimeError(msg)
        return self._session


def _to_domain(model: MemberModel, *, status: MemberStatus | None = None) -> Member:
    return Member(
        id=model.id,
        telegram_user_id=model.telegram_user_id,
        role=MemberRole(model.role),
        status=status or MemberStatus(model.status),
        permissions=frozenset(model.permissions_json),
    )


def _member_security_json(member: Member) -> dict[str, object]:
    return {
        "id": str(member.id),
        "role": member.role.value,
        "status": member.status.value,
        "permissions": sorted(member.permissions),
    }
