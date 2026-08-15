"""Application workflows for persistent task creation and reservation."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from community_bot.domain.assignments import AssignmentStatus
from community_bot.domain.catalog import TaskFormat, validate_payload
from community_bot.domain.economy import ResolvedLevel, refund_reward, reserve_reward
from community_bot.domain.members import Member, MemberRole, MemberStatus, is_superadministrator
from community_bot.domain.moderation import RestrictedAction
from community_bot.domain.tasks import (
    AcceptanceTaskSnapshot,
    StaleTaskDraftError,
    TaskDraftStep,
    TaskError,
    TaskStatus,
    validate_acceptance_actor,
    validate_deadline,
    validate_materials,
    validate_public_text_uris,
    validate_slots,
    validate_task_format,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from community_bot.application.catalog import CatalogTemplate
    from community_bot.application.economy import ActiveProductConfig, EconomyMutationPort
    from community_bot.domain.assignments import Assignment

_MAX_OWNED_TASKS = 20
_MAX_AVAILABLE_TASKS = 10
_MAX_COMMUNITY_PUBLICATION_REQUESTS = 20
_FORMAT_VALUE_SIZE = 2


@dataclass(frozen=True, slots=True)
class TaskDraft:
    """Persistent resumable task creation draft."""

    id: UUID
    creator_id: UUID
    origin: str
    reviewer_admin_id: UUID | None
    community_approval_requested_at: datetime.datetime | None
    community_approved_by_admin_id: UUID | None
    community_approved_at: datetime.datetime | None
    template_id: UUID
    input_payload: dict[str, object] | None
    deadline_at: datetime.datetime | None
    format: TaskFormat | None
    city: str | None
    materials: dict[str, object] | None
    performer_slots: int | None
    current_step: TaskDraftStep
    revision: int
    is_current: bool
    publish_command_id: UUID
    test_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TaskPreview:
    """Read-only publication preview with the exact reserve amount."""

    draft: TaskDraft
    author_display_name: str
    template_name: str
    template_description: str
    performer_instructions: str
    public_input_keys: tuple[str, ...]
    completion_criteria: str
    credit_reward_per_performer: int
    reserved_credit_total: int


@dataclass(frozen=True, slots=True)
class PublishedTask:
    """Immutable public task snapshot plus creation-owned lifecycle state."""

    id: UUID
    creator_id: UUID | None
    created_by_admin_id: UUID | None
    reviewer_admin_id: UUID | None
    origin: str
    author_display_name: str
    template_id: UUID
    template_version: int
    title: str
    description: str
    performer_instructions: str
    public_input_keys: tuple[str, ...]
    completion_criteria: str
    input_payload: dict[str, object]
    materials: dict[str, object]
    credit_reward_per_performer: int
    performer_slots: int
    reserved_credit_total: int
    minimum_level: int
    format: TaskFormat
    city: str | None
    deadline_at: datetime.datetime
    status: TaskStatus
    publish_command_id: UUID
    created_at: datetime.datetime
    test_run_id: UUID | None = None

    def acceptance_snapshot(self) -> AcceptanceTaskSnapshot:
        """Return the transport-neutral static acceptance input."""
        return AcceptanceTaskSnapshot(self.creator_id, self.status, self.minimum_level)


@dataclass(frozen=True, slots=True)
class AvailableTaskPage:
    """One stable page of tasks visible to an active performer."""

    items: tuple[PublishedTask, ...]
    next_cursor_task_id: UUID | None


@dataclass(frozen=True, slots=True)
class OwnedTaskAssignee:
    """Public assignee label and lifecycle state for an owned task."""

    assignment_id: UUID
    display_name: str
    status: str


@dataclass(frozen=True, slots=True)
class OwnedTaskCard:
    """Owned task plus occupancy and cancellation-request context."""

    task: PublishedTask
    assignees: tuple[OwnedTaskAssignee, ...]
    cancellation_status: str | None


@dataclass(frozen=True, slots=True)
class TaskCancellationResponse:
    """One durable performer decision context."""

    id: UUID
    request_id: UUID
    task_id: UUID
    assignment_id: UUID
    performer_id: UUID
    request_status: str
    request_resolution_reason: str | None
    response_status: str


@dataclass(frozen=True, slots=True)
class TaskCancellationOutcome:
    """Result of an immediate cancellation or a negotiated request."""

    task: PublishedTask
    request_id: UUID | None
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AdministratorOption:
    """Safe administrator choice shown during community task creation."""

    id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class CommunityPublicationRequest:
    """Pending community task release visible only to a superadministrator."""

    draft_id: UUID
    revision: int
    creator_display_name: str
    reviewer_display_name: str
    template_name: str
    requested_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class AdvanceDraftCommand:
    """Advance one expected draft step with untrusted transport data."""

    update_id: int
    actor_telegram_user_id: int
    draft_id: UUID
    expected_step: TaskDraftStep
    expected_revision: int
    value: object


@dataclass(frozen=True, slots=True)
class PublishTaskCommand:
    """Publish one preview revision exactly once."""

    update_id: int
    actor_telegram_user_id: int
    draft_id: UUID
    expected_revision: int


class TaskUnitOfWork(Protocol):  # pragma: no cover - structural typing contract.
    """Caller-owned transaction contract for task workflows."""

    @property
    def economy(self) -> EconomyMutationPort: ...
    async def acquire_update_gate(self, update_id: int) -> None: ...
    async def get_receipt_outcome(self, update_id: int) -> str | None: ...
    async def acquire_task_identity_gate(self, telegram_user_id: int) -> None: ...
    async def acquire_task_command_gate(self, command_id: UUID) -> None: ...
    async def acquire_assignment_task_gate(self, task_id: UUID) -> None: ...
    async def acquire_catalog_mutation_gate(self) -> None: ...
    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...
    async def ensure_moderation_action_allowed(
        self, member_id: UUID, action: RestrictedAction
    ) -> None: ...
    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]: ...
    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel: ...
    async def get_active_product_config(self) -> ActiveProductConfig | None: ...
    async def count_active_assignments(self, performer_id: UUID) -> int: ...
    async def template_for_creation(
        self, *, template_id: UUID, level: int
    ) -> CatalogTemplate | None: ...
    async def catalog_template(self, template_id: UUID) -> CatalogTemplate | None: ...
    async def member_display_name(self, member_id: UUID) -> str: ...
    async def create_task_draft(
        self, *, creator_id: UUID, template_id: UUID, origin: str = "member"
    ) -> TaskDraft: ...
    async def get_current_task_draft(self, creator_id: UUID) -> TaskDraft | None: ...
    async def get_task_draft(self, draft_id: UUID) -> TaskDraft | None: ...
    async def lock_task_draft(self, draft_id: UUID) -> TaskDraft | None: ...
    async def select_task_draft(self, *, creator_id: UUID, draft_id: UUID) -> TaskDraft: ...
    async def save_task_draft(self, draft: TaskDraft) -> TaskDraft: ...
    async def list_active_administrators(
        self, *, exclude_id: UUID, test_run_id: UUID | None
    ) -> tuple[AdministratorOption, ...]: ...
    async def list_pending_community_publications(
        self, *, actor_id: UUID, limit: int
    ) -> tuple[CommunityPublicationRequest, ...]: ...
    async def claim_text_flow(  # noqa: PLR0913
        self,
        *,
        member_id: UUID,
        flow_type: str,
        step: str,
        reference_id: UUID | None,
        revision: int,
        payload: dict[str, object] | None = None,
    ) -> object: ...
    async def clear_text_flow(
        self, *, member_id: UUID, flow_type: str, reference_id: UUID | None = None
    ) -> bool: ...
    async def delete_task_draft(self, draft_id: UUID) -> None: ...
    async def task_by_publish_command(self, command_id: UUID) -> PublishedTask | None: ...
    async def insert_published_task(
        self, *, draft: TaskDraft, template: CatalogTemplate
    ) -> PublishedTask: ...
    async def get_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def lock_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def list_task_assignments(
        self, task_id: UUID, *, for_update: bool = False
    ) -> tuple[Assignment, ...]: ...
    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask: ...
    async def save_community_reviewer(
        self, *, task_id: UUID, reviewer_id: UUID, now: datetime.datetime
    ) -> PublishedTask: ...
    async def list_owned_tasks(
        self,
        *,
        creator_id: UUID,
        limit: int,
        status: TaskStatus | None,
        before_created_at: datetime.datetime | None,
        before_id: UUID | None,
    ) -> tuple[PublishedTask, ...]: ...
    async def list_owned_task_cards(
        self,
        *,
        creator_id: UUID,
        limit: int,
        status: TaskStatus | None,
        before_created_at: datetime.datetime | None,
        before_id: UUID | None,
    ) -> tuple[OwnedTaskCard, ...]: ...
    async def get_owned_task_card(
        self, *, task_id: UUID, owner_id: UUID
    ) -> OwnedTaskCard | None: ...
    async def get_pending_task_cancellation(self, task_id: UUID) -> UUID | None: ...
    async def has_declined_task_cancellation(self, task_id: UUID) -> bool: ...
    async def create_task_cancellation(
        self, *, task_id: UUID, creator_id: UUID, assignments: Sequence[Assignment]
    ) -> UUID: ...
    async def get_task_cancellation_response(
        self, response_id: UUID, *, for_update: bool = False
    ) -> TaskCancellationResponse | None: ...
    async def answer_task_cancellation(
        self, *, response_id: UUID, accepted: bool, now: datetime.datetime
    ) -> TaskCancellationResponse: ...
    async def task_cancellation_all_accepted(self, request_id: UUID) -> bool: ...
    async def resolve_task_cancellation(
        self, *, request_id: UUID, status: str, reason: str, now: datetime.datetime
    ) -> None: ...
    async def cancel_assignment_by_creator(
        self, assignment_id: UUID, creator_id: UUID, reason: str
    ) -> None: ...
    async def add_task_cancellation_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
        business_key: str,
    ) -> None: ...
    async def list_available_tasks(
        self,
        *,
        performer_id: UUID,
        level: int,
        limit: int,
        cursor_task_id: UUID | None,
        now: datetime.datetime,
    ) -> tuple[PublishedTask, ...]: ...
    async def ensure_task_test_access(self, *, task_id: UUID, member_id: UUID) -> None: ...
    async def add_task_outbox(
        self, *, event_type: str, task: PublishedTask, business_key: str
    ) -> None: ...
    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None: ...
    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None: ...
    async def commit(self) -> None: ...


class TaskUnitOfWorkFactory(Protocol):  # pragma: no cover - structural typing contract.
    """Create isolated task transactions."""

    def __call__(self) -> AbstractAsyncContextManager[TaskUnitOfWork]: ...


class TaskService:
    """Coordinate persistent drafts, publication, ownership, and cancellation."""

    def __init__(self, unit_of_work_factory: TaskUnitOfWorkFactory) -> None:
        """Configure the shared caller-owned transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def start(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        template_id: UUID | None,
        origin: str = "member",
    ) -> TaskDraft | None:
        """Create a new current draft or resume the existing current draft."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _draft_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.CREATE_TASK)
            if template_id is None:
                draft = await uow.get_current_task_draft(actor.id)
                outcome = "task_draft:none" if draft is None else f"task_draft:{draft.id}"
            else:
                await uow.acquire_catalog_mutation_gate()
                actor = (await uow.lock_members((actor.id,)))[actor.id]
                _require_active(actor)
                level = await uow.resolve_member_level(actor.id)
                template = await uow.template_for_creation(
                    template_id=template_id, level=level.level_number
                )
                if template is None:
                    raise PermissionError("Task template is unavailable to this member.")
                if origin not in {"member", "community"}:
                    raise TaskError("Task origin is invalid.")
                if origin == "community" and actor.role is not MemberRole.ADMINISTRATOR:
                    raise PermissionError("Only an administrator may create a community task.")
                draft = await uow.create_task_draft(
                    creator_id=actor.id,
                    template_id=template.id,
                    origin=origin,
                )
                outcome = f"task_draft:{draft.id}"
            if draft is not None:
                await uow.claim_text_flow(
                    member_id=actor.id,
                    flow_type="task",
                    step=draft.current_step.value,
                    reference_id=draft.id,
                    revision=draft.revision,
                )
            await _finish(uow, update_id, actor, outcome, "task_draft")
            return draft

    async def community_reviewers(
        self, actor_telegram_user_id: int
    ) -> tuple[AdministratorOption, ...]:
        """List independent active administrators available for a community draft."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            if actor.role is not MemberRole.ADMINISTRATOR:
                raise PermissionError("Only an administrator may select a community reviewer.")
            draft = await uow.get_current_task_draft(actor.id)
            return await uow.list_active_administrators(
                exclude_id=actor.id,
                test_run_id=None if draft is None else draft.test_run_id,
            )

    async def pending_community_publications(
        self, *, actor_telegram_user_id: int, limit: int = 10
    ) -> tuple[CommunityPublicationRequest, ...]:
        """List community publication requests awaiting superadministrator approval."""
        if not 1 <= limit <= _MAX_COMMUNITY_PUBLICATION_REQUESTS:
            raise TaskError("Community publication request page size is invalid.")
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            _require_superadministrator(actor)
            return await uow.list_pending_community_publications(actor_id=actor.id, limit=limit)

    async def select_community_reviewer(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        reviewer_id: UUID,
    ) -> TaskDraft:
        """Assign another active administrator to the current community draft."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                draft = await _draft_from_outcome(uow, replay)
                if draft is None:
                    raise TaskError("Stored community draft does not exist.")
                return draft
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            draft = await uow.get_current_task_draft(actor.id)
            if draft is None or draft.origin != "community":
                raise TaskError("Current community draft does not exist.")
            locked = await uow.lock_members((actor.id, reviewer_id))
            actor, reviewer = locked[actor.id], locked[reviewer_id]
            if (
                actor.role is not MemberRole.ADMINISTRATOR
                or reviewer.role is not MemberRole.ADMINISTRATOR
                or reviewer.status is not MemberStatus.ACTIVE
                or reviewer.id == actor.id
            ):
                raise PermissionError("Community reviewer must be another active administrator.")
            current = await uow.lock_task_draft(draft.id)
            if current is None or current.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this administrator.")
            updated = await uow.save_task_draft(
                _replace_draft(
                    current,
                    reviewer_admin_id=reviewer.id,
                    revision=current.revision + 1,
                )
            )
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="task",
                step=updated.current_step.value,
                reference_id=updated.id,
                revision=updated.revision,
            )
            await _finish(uow, update_id, actor, f"task_draft:{updated.id}", "task_draft")
            return updated

    async def resume(
        self, *, update_id: int, actor_telegram_user_id: int, draft_id: UUID
    ) -> TaskDraft:
        """Select one owned unfinished draft as current."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                draft = await _draft_from_outcome(uow, replay)
                if draft is None:
                    raise TaskError("Stored task draft does not exist.")
                return draft
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            draft = await uow.select_task_draft(creator_id=actor.id, draft_id=draft_id)
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="task",
                step=draft.current_step.value,
                reference_id=draft.id,
                revision=draft.revision,
            )
            await _finish(uow, update_id, actor, f"task_draft:{draft.id}", "task_draft")
            return draft

    async def current(self, *, actor_telegram_user_id: int) -> TaskDraft | None:
        """Read the selected unfinished draft without changing state."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            return await uow.get_current_task_draft(actor.id)

    async def cancel_draft(
        self, *, update_id: int, actor_telegram_user_id: int, draft_id: UUID
    ) -> None:
        """Delete one owned unfinished draft without touching the economy."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                if replay != f"task_draft_cancelled:{draft_id}":
                    raise TaskError("Telegram update was already used by another operation.")
                return
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            actor = (await uow.lock_members((actor.id,)))[actor.id]
            draft = await uow.lock_task_draft(draft_id)
            if draft is None:
                raise LookupError("Task draft does not exist.")
            if draft.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this member.")
            if draft.current_step is TaskDraftStep.PUBLISHED:
                raise TaskError("Published task draft cannot be deleted.")
            await uow.delete_task_draft(draft.id)
            await uow.clear_text_flow(member_id=actor.id, flow_type="task", reference_id=draft.id)
            await _finish(
                uow,
                update_id,
                actor,
                f"task_draft_cancelled:{draft.id}",
                "task_draft",
            )

    async def advance(self, command: AdvanceDraftCommand) -> TaskDraft:
        """Validate and persist one expected draft step."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, command.update_id)
            if replay is not None:
                draft = await _draft_from_outcome(uow, replay)
                if draft is None:
                    raise TaskError("Stored task draft does not exist.")
                return draft
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            actor = await _active_actor(uow, command.actor_telegram_user_id)
            actor = (await uow.lock_members((actor.id,)))[actor.id]
            _require_active(actor)
            draft = await uow.lock_task_draft(command.draft_id)
            if draft is None or draft.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this member.")
            _expect(draft, command.expected_step, command.expected_revision)
            template = await uow.catalog_template(draft.template_id)
            if template is None:
                raise TaskError("Task template version does not exist.")
            updated = _advance_draft(draft, template, command.value)
            updated = await uow.save_task_draft(updated)
            await uow.claim_text_flow(
                member_id=actor.id,
                flow_type="task",
                step=updated.current_step.value,
                reference_id=updated.id,
                revision=updated.revision,
            )
            await _finish(uow, command.update_id, actor, f"task_draft:{updated.id}", "task_draft")
            return updated

    async def preview(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        draft_id: UUID,
        expected_revision: int,
    ) -> TaskPreview:
        """Move a complete draft to preview without an economy effect."""
        draft = await self.advance(
            AdvanceDraftCommand(
                update_id,
                actor_telegram_user_id,
                draft_id,
                TaskDraftStep.SLOTS,
                expected_revision,
                None,
            )
        )
        async with self._unit_of_work_factory() as uow:
            template = await uow.catalog_template(draft.template_id)
            if template is None or draft.performer_slots is None:
                raise TaskError("Task preview is incomplete.")
            return TaskPreview(
                draft,
                (
                    "Сообщество"
                    if draft.origin == "community"
                    else await uow.member_display_name(draft.creator_id)
                ),
                template.name,
                template.description,
                template.performer_instructions,
                _schema_property_keys(template.input_schema),
                template.completion_criteria,
                template.credit_reward,
                0
                if draft.origin == "community"
                else template.credit_reward * draft.performer_slots,
            )

    async def publish(self, command: PublishTaskCommand) -> PublishedTask | TaskDraft:  # noqa: PLR0915
        """Atomically reserve credits and publish one exact preview revision."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, command.update_id)
            if replay is not None:
                return await _publication_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            preliminary = await uow.get_task_draft(command.draft_id)
            if preliminary is None:
                raise TaskError("Task draft does not exist.")
            await uow.acquire_task_command_gate(preliminary.publish_command_id)
            await uow.acquire_catalog_mutation_gate()
            template_before = await uow.catalog_template(preliminary.template_id)
            if template_before is None or preliminary.performer_slots is None:
                raise TaskError("Task draft is incomplete.")
            await uow.ensure_moderation_action_allowed(
                preliminary.creator_id, RestrictedAction.CREATE_TASK
            )
            prepared = None
            if preliminary.origin == "community":
                if preliminary.reviewer_admin_id is None:
                    raise TaskError("Community task reviewer is required.")
                locked = await uow.lock_members(
                    (preliminary.creator_id, preliminary.reviewer_admin_id)
                )
                actor = locked[preliminary.creator_id]
                reviewer = locked[preliminary.reviewer_admin_id]
                if (
                    actor.role is not MemberRole.ADMINISTRATOR
                    or reviewer.role is not MemberRole.ADMINISTRATOR
                    or reviewer.status is not MemberStatus.ACTIVE
                    or reviewer.id == actor.id
                ):
                    raise PermissionError("Community reviewer is no longer independent.")
                reserve_total = 0
            else:
                reserve_total = template_before.credit_reward * preliminary.performer_slots
                prepared = await uow.economy.prepare_batch(
                    (
                        reserve_reward(
                            member_id=preliminary.creator_id,
                            amount=reserve_total,
                            idempotency_key=(
                                f"task_publish:{preliminary.publish_command_id}:reserve"
                            ),
                        ),
                    )
                )
                actor = prepared.members[preliminary.creator_id]
            if actor.telegram_user_id != command.actor_telegram_user_id:
                raise PermissionError("Task draft is not owned by this member.")
            _require_active(actor)
            draft = await uow.lock_task_draft(command.draft_id)
            if draft is None:
                raise TaskError("Task draft does not exist.")
            existing = await uow.task_by_publish_command(preliminary.publish_command_id)
            if existing is not None:
                if (
                    draft.current_step is not TaskDraftStep.PUBLISHED
                    or (
                        draft.origin != "community"
                        and draft.revision != command.expected_revision + 1
                    )
                    or (
                        draft.origin == "community"
                        and draft.revision < command.expected_revision + 1
                    )
                ):
                    raise StaleTaskDraftError("Task publication identity is conflicting.")
                if prepared is not None:
                    await prepared.apply()
                await _finish_receipt(uow, command.update_id, actor, f"task:{existing.id}")
                return existing
            if (
                draft.origin == "community"
                and not is_superadministrator(actor)
                and draft.community_approval_requested_at is not None
                and draft.current_step is TaskDraftStep.PREVIEW
                and draft.revision >= command.expected_revision
            ):
                await _finish_receipt(
                    uow,
                    command.update_id,
                    actor,
                    f"task_approval_pending:{draft.id}",
                )
                return draft
            _expect(draft, TaskDraftStep.PREVIEW, command.expected_revision)
            level = await uow.resolve_member_level(actor.id)
            template = await uow.template_for_creation(
                template_id=draft.template_id, level=level.level_number
            )
            if template is None:
                raise PermissionError("Task template is no longer publishable.")
            _validate_publishable(draft, template)
            expected_reserve = (
                0
                if draft.origin == "community"
                else template.credit_reward * (draft.performer_slots or 0)
            )
            if expected_reserve != reserve_total:
                raise TaskError("Task reserve changed after preview.")
            if draft.origin == "community" and not is_superadministrator(actor):
                return await _request_community_publication(
                    uow=uow,
                    update_id=command.update_id,
                    actor=actor,
                    draft=draft,
                )
            if prepared is not None:
                await prepared.apply()
            if draft.origin == "community":
                draft = _replace_draft(
                    draft,
                    community_approved_by_admin_id=actor.id,
                    community_approved_at=_utc_now(),
                )
            return await _publish_locked_draft(
                uow=uow,
                update_id=command.update_id,
                actor=actor,
                draft=draft,
                template=template,
            )

    async def confirm_community_publication(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        draft_id: UUID,
        expected_revision: int,
    ) -> PublishedTask:
        """Publish one pending community draft after superadministrator confirmation."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _task_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            _require_superadministrator(actor)
            preliminary = await uow.get_task_draft(draft_id)
            if preliminary is None:
                raise TaskError("Task draft does not exist.")
            if preliminary.origin != "community":
                raise TaskError("Only community task drafts require approval.")
            await uow.acquire_task_command_gate(preliminary.publish_command_id)
            await uow.acquire_catalog_mutation_gate()
            draft = await uow.lock_task_draft(draft_id)
            if draft is None:
                raise TaskError("Task draft does not exist.")
            existing = await uow.task_by_publish_command(preliminary.publish_command_id)
            if existing is not None:
                if draft.current_step is not TaskDraftStep.PUBLISHED:
                    raise StaleTaskDraftError("Task publication identity is conflicting.")
                await _finish_receipt(uow, update_id, actor, f"task:{existing.id}")
                return existing
            _expect(draft, TaskDraftStep.PREVIEW, expected_revision)
            if (
                draft.reviewer_admin_id is None
                or draft.community_approval_requested_at is None
                or draft.community_approved_by_admin_id is not None
            ):
                raise TaskError("Community task publication request is not pending.")
            await uow.ensure_moderation_action_allowed(
                draft.creator_id, RestrictedAction.CREATE_TASK
            )
            locked = await uow.lock_members(
                tuple(dict.fromkeys((actor.id, draft.creator_id, draft.reviewer_admin_id)))
            )
            actor = locked[actor.id]
            creator = locked[draft.creator_id]
            reviewer = locked[draft.reviewer_admin_id]
            _require_superadministrator(actor)
            if (
                creator.role is not MemberRole.ADMINISTRATOR
                or creator.status is not MemberStatus.ACTIVE
                or reviewer.role is not MemberRole.ADMINISTRATOR
                or reviewer.status is not MemberStatus.ACTIVE
                or reviewer.id == creator.id
            ):
                raise PermissionError("Community reviewer is no longer independent.")
            level = await uow.resolve_member_level(creator.id)
            template = await uow.template_for_creation(
                template_id=draft.template_id, level=level.level_number
            )
            if template is None:
                raise PermissionError("Task template is no longer publishable.")
            _validate_publishable(draft, template)
            approved = _replace_draft(
                draft,
                community_approved_by_admin_id=actor.id,
                community_approved_at=_utc_now(),
            )
            return await _publish_locked_draft(
                uow=uow,
                update_id=update_id,
                actor=actor,
                draft=approved,
                template=template,
            )

    async def list_owned(
        self,
        *,
        actor_telegram_user_id: int,
        limit: int = 20,
        status: TaskStatus | None = None,
        cursor: tuple[datetime.datetime, UUID] | None = None,
    ) -> tuple[PublishedTask, ...]:
        """Return only tasks created by one active actor."""
        if not 1 <= limit <= _MAX_OWNED_TASKS:
            raise TaskError("Owned task page size must be between 1 and 20.")
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            return await uow.list_owned_tasks(
                creator_id=actor.id,
                limit=limit,
                status=status,
                before_created_at=None if cursor is None else cursor[0],
                before_id=None if cursor is None else cursor[1],
            )

    async def list_owned_cards(
        self,
        *,
        actor_telegram_user_id: int,
        limit: int = 20,
        status: TaskStatus | None = None,
        cursor: tuple[datetime.datetime, UUID] | None = None,
    ) -> tuple[OwnedTaskCard, ...]:
        """Return compact-card context for tasks visible to one owner or reviewer."""
        if not 1 <= limit <= _MAX_OWNED_TASKS:
            raise TaskError("Owned task page size must be between 1 and 20.")
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            return await uow.list_owned_task_cards(
                creator_id=actor.id,
                limit=limit,
                status=status,
                before_created_at=None if cursor is None else cursor[0],
                before_id=None if cursor is None else cursor[1],
            )

    async def owned_card(self, *, actor_telegram_user_id: int, task_id: UUID) -> OwnedTaskCard:
        """Return one owned card while enforcing the same visibility boundary."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            card = await uow.get_owned_task_card(task_id=task_id, owner_id=actor.id)
            if card is None:
                raise PermissionError("Task is not visible to this member.")
            return card

    async def list_available(
        self,
        *,
        actor_telegram_user_id: int,
        cursor_task_id: UUID | None = None,
    ) -> AvailableTaskPage:
        """Return tasks the actor may attempt to accept right now."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.ACCEPT_TASK)
            active = await uow.get_active_product_config()
            limit = 3 if active is None else active.maximum_active_assignments
            if await uow.count_active_assignments(actor.id) >= limit:
                return AvailableTaskPage(items=(), next_cursor_task_id=None)
            level = await uow.resolve_member_level(actor.id)
            tasks = await uow.list_available_tasks(
                performer_id=actor.id,
                level=level.level_number,
                limit=_MAX_AVAILABLE_TASKS + 1,
                cursor_task_id=cursor_task_id,
                now=datetime.datetime.now(datetime.UTC),
            )
        items = tasks[:_MAX_AVAILABLE_TASKS]
        return AvailableTaskPage(
            items=items,
            next_cursor_task_id=items[-1].id if len(tasks) > _MAX_AVAILABLE_TASKS else None,
        )

    async def cancel(
        self, *, update_id: int, actor_telegram_user_id: int, task_id: UUID
    ) -> PublishedTask:
        """Atomically refund and cancel one creation-owned published task."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _task_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            preliminary = await uow.get_task(task_id)
            if preliminary is None:
                raise TaskError("Task does not exist.")
            if preliminary.creator_id is None:
                raise PermissionError("Community tasks are managed only by administrators.")
            await uow.acquire_assignment_task_gate(task_id)
            await uow.acquire_task_command_gate(task_id)
            task = await uow.lock_task(task_id)
            if task is None:
                raise TaskError("Task does not exist.")
            if task.status is TaskStatus.CANCELLED:
                raise TaskError("Task is already cancelled.")
            if task.status is not TaskStatus.PUBLISHED:
                raise TaskError("Task cannot be cancelled from its current state.")
            if _utc_now() >= task.deadline_at:
                raise TaskError("Task cancellation deadline has passed.")
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            active = [item for item in assignments if item.status is not AssignmentStatus.CANCELLED]
            if active:
                raise TaskError("Task has an active performer; send a cancellation request.")
            prepared = await uow.economy.prepare_batch(
                (
                    refund_reward(
                        member_id=preliminary.creator_id,
                        amount=preliminary.reserved_credit_total,
                        idempotency_key=f"task_cancel:{task_id}:refund",
                    ),
                )
            )
            actor = prepared.members[preliminary.creator_id]
            if actor.telegram_user_id != actor_telegram_user_id:
                raise PermissionError("Only the task creator can cancel this task.")
            _require_active(actor)
            await prepared.apply()
            task = await uow.save_task_status(task_id=task.id, status=TaskStatus.CANCELLED)
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="task_cancelled",
                entity_type="task",
                entity_id=str(task.id),
                reason=None,
            )
            await uow.add_task_outbox(
                event_type="task.cancelled",
                task=task,
                business_key=f"task.cancelled:{task.id}",
            )
            await _finish_receipt(uow, update_id, actor, f"task:{task.id}")
            return task

    async def request_cancellation(
        self, *, update_id: int, actor_telegram_user_id: int, task_id: UUID
    ) -> TaskCancellationOutcome:
        """Cancel a free task or ask every accepted performer for consent."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _cancellation_outcome_from_receipt(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            preliminary = await uow.get_task(task_id)
            if preliminary is None:
                raise TaskError("Task does not exist.")
            await uow.acquire_assignment_task_gate(task_id)
            await uow.acquire_task_command_gate(task_id)
            task = await uow.lock_task(task_id)
            if task is None or task.creator_id is None:
                raise PermissionError("Only the member task creator can cancel this task.")
            actor = await _active_actor(uow, actor_telegram_user_id)
            if actor.id != task.creator_id:
                raise PermissionError("Only the task creator can cancel this task.")
            if task.status is not TaskStatus.PUBLISHED:
                raise TaskError("Task cannot be cancelled from its current state.")
            if _utc_now() >= task.deadline_at:
                raise TaskError("Task cancellation deadline has passed.")
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            active = [item for item in assignments if item.status is not AssignmentStatus.CANCELLED]
            if not active:
                prepared = await uow.economy.prepare_batch(
                    (
                        refund_reward(
                            member_id=actor.id,
                            amount=task.reserved_credit_total,
                            idempotency_key=f"task_cancel:{task.id}:refund",
                        ),
                    )
                )
                await prepared.apply()
                task = await uow.save_task_status(task_id=task.id, status=TaskStatus.CANCELLED)
                await uow.add_task_outbox(
                    event_type="task.cancelled",
                    task=task,
                    business_key=f"task.cancelled:{task.id}",
                )
                await uow.append_audit_event(
                    actor_member_id=actor.id,
                    action="task_cancelled",
                    entity_type="task",
                    entity_id=str(task.id),
                    reason="assignment_slots_released",
                )
                await _finish_receipt(uow, update_id, actor, f"task_cancelled:{task.id}")
                return TaskCancellationOutcome(task, None, "cancelled")
            if any(item.status is not AssignmentStatus.ACCEPTED for item in active):
                raise TaskError("Cancellation is unavailable because work has already started.")
            pending = await uow.get_pending_task_cancellation(task.id)
            if pending is not None:
                raise TaskError("A cancellation request is already awaiting performer responses.")
            if await uow.has_declined_task_cancellation(task.id):
                raise TaskError("A performer has already declined cancellation for this task.")
            request_id = await uow.create_task_cancellation(
                task_id=task.id, creator_id=actor.id, assignments=active
            )
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="task_cancellation_requested",
                entity_type="task",
                entity_id=str(task.id),
                reason=None,
            )
            await _finish_receipt(
                uow, update_id, actor, f"task_cancel_request:{task.id}:{request_id}"
            )
            return TaskCancellationOutcome(task, request_id, "pending")

    async def respond_cancellation(  # noqa: PLR0911 - explicit cancellation state machine.
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        response_id: UUID,
        accepted: bool,
    ) -> TaskCancellationOutcome:
        """Record one performer's decision and finalize only unanimous consent."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _cancellation_outcome_from_receipt(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            preliminary = await uow.get_task_cancellation_response(response_id)
            if preliminary is None:
                raise TaskError("Cancellation response does not exist.")
            await uow.acquire_assignment_task_gate(preliminary.task_id)
            task = await uow.lock_task(preliminary.task_id)
            response = await uow.get_task_cancellation_response(response_id, for_update=True)
            actor = await _active_actor(uow, actor_telegram_user_id)
            if task is None or response is None:
                raise TaskError("Cancellation request is no longer available.")
            if task.creator_id is None:
                raise PermissionError("Community tasks do not support member cancellation.")
            if response.performer_id != actor.id:
                raise PermissionError("This cancellation request belongs to another performer.")
            now = _utc_now()
            if (
                task.status is TaskStatus.PUBLISHED
                and response.request_status == "pending"
                and response.response_status == "pending"
                and now >= task.deadline_at
            ):
                await uow.resolve_task_cancellation(
                    request_id=response.request_id,
                    status="obsolete",
                    reason="deadline_passed",
                    now=now,
                )
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"task_cancel_obsolete:{task.id}:{response.request_id}:deadline_passed",
                )
                return TaskCancellationOutcome(
                    task, response.request_id, "obsolete", "deadline_passed"
                )
            if response.request_status == "obsolete":
                reason = response.request_resolution_reason or "state_changed"
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"task_cancel_obsolete:{task.id}:{response.request_id}:{reason}",
                )
                return TaskCancellationOutcome(task, response.request_id, "obsolete", reason)
            if (
                task.status is not TaskStatus.PUBLISHED
                or response.request_status != "pending"
                or response.response_status != "pending"
            ):
                raise TaskError("Cancellation request is no longer active.")
            response = await uow.answer_task_cancellation(
                response_id=response.id, accepted=accepted, now=now
            )
            if not accepted:
                await uow.resolve_task_cancellation(
                    request_id=response.request_id,
                    status="declined",
                    reason="performer_started",
                    now=now,
                )
                await uow.add_task_cancellation_outbox(
                    event_type="task.cancellation_declined",
                    aggregate_type="task_cancellation_request",
                    aggregate_id=response.request_id,
                    payload={"task_id": str(task.id), "title": task.title},
                    business_key=f"task_cancel_request:{response.request_id}:declined",
                )
                await uow.append_audit_event(
                    actor_member_id=actor.id,
                    action="task_cancellation_declined",
                    entity_type="task",
                    entity_id=str(task.id),
                    reason="performer_started",
                )
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"task_cancel_declined:{task.id}:{response.request_id}",
                )
                return TaskCancellationOutcome(task, response.request_id, "declined")
            if not await uow.task_cancellation_all_accepted(response.request_id):
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"task_cancel_pending:{task.id}:{response.request_id}",
                )
                return TaskCancellationOutcome(task, response.request_id, "pending")
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            started = any(
                item.status is not AssignmentStatus.ACCEPTED
                for item in assignments
                if item.status is not AssignmentStatus.CANCELLED
            )
            if started:
                await uow.resolve_task_cancellation(
                    request_id=response.request_id,
                    status="obsolete",
                    reason="work_started",
                    now=now,
                )
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"task_cancel_obsolete:{task.id}:{response.request_id}:work_started",
                )
                return TaskCancellationOutcome(
                    task, response.request_id, "obsolete", "work_started"
                )
            for assignment in assignments:
                if assignment.status is AssignmentStatus.ACCEPTED:
                    await uow.cancel_assignment_by_creator(
                        assignment.id,
                        task.creator_id,
                        "creator_cancellation_approved",
                    )
            prepared = await uow.economy.prepare_batch(
                (
                    refund_reward(
                        member_id=task.creator_id,
                        amount=task.reserved_credit_total,
                        idempotency_key=f"task_cancel:{task.id}:refund",
                    ),
                )
            )
            await prepared.apply()
            task = await uow.save_task_status(task_id=task.id, status=TaskStatus.CANCELLED)
            await uow.resolve_task_cancellation(
                request_id=response.request_id, status="completed", reason="unanimous", now=now
            )
            await uow.add_task_outbox(
                event_type="task.cancelled",
                task=task,
                business_key=f"task.cancelled:{task.id}",
            )
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="task_cancelled_by_consent",
                entity_type="task",
                entity_id=str(task.id),
                reason="unanimous_performer_consent",
            )
            await _finish_receipt(
                uow,
                update_id,
                actor,
                f"task_cancelled:{task.id}:{response.request_id}",
            )
            return TaskCancellationOutcome(task, response.request_id, "cancelled")

    async def replace_community_reviewer(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        task_id: UUID,
        reviewer_id: UUID,
    ) -> PublishedTask:
        """Replace a community reviewer without exposing member identifiers to users."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _task_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            await uow.acquire_assignment_task_gate(task_id)
            task = await uow.lock_task(task_id)
            assignments = await uow.list_task_assignments(task_id, for_update=True)
            locked = await uow.lock_members((actor.id, reviewer_id))
            actor, reviewer = locked[actor.id], locked[reviewer_id]
            if (
                task is None
                or task.origin != "community"
                or actor.role is not MemberRole.ADMINISTRATOR
                or actor.status is not MemberStatus.ACTIVE
                or reviewer.role is not MemberRole.ADMINISTRATOR
                or reviewer.status is not MemberStatus.ACTIVE
                or reviewer.id == task.created_by_admin_id
                or any(item.performer_id == reviewer.id for item in assignments)
            ):
                raise PermissionError("Community reviewer replacement is unavailable.")
            updated = await uow.save_community_reviewer(
                task_id=task.id,
                reviewer_id=reviewer.id,
                now=datetime.datetime.now(datetime.UTC),
            )
            await _finish(uow, update_id, actor, f"task:{updated.id}", "task_reviewer")
            return updated

    async def validate_acceptance(
        self, *, task_id: UUID, actor_telegram_user_id: int
    ) -> PublishedTask:
        """Validate static acceptance eligibility for future CB-11 composition."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            level = await uow.resolve_member_level(actor.id)
            task = await uow.get_task(task_id)
            if task is None:
                raise TaskError("Task does not exist.")
            validate_acceptance_actor(task.acceptance_snapshot(), actor, resolved_level=level)
            return task


async def _begin_update(uow: TaskUnitOfWork, update_id: int) -> str | None:
    await uow.acquire_update_gate(update_id)
    return await uow.get_receipt_outcome(update_id)


async def _cancellation_outcome_from_receipt(
    uow: TaskUnitOfWork, outcome: str
) -> TaskCancellationOutcome:
    statuses = {
        "task_cancelled:": "cancelled",
        "task_cancel_pending:": "pending",
        "task_cancel_declined:": "declined",
        "task_cancel_obsolete:": "obsolete",
    }
    for prefix, status in statuses.items():
        if outcome.startswith(prefix):
            task_value, *metadata = outcome.removeprefix(prefix).split(":", 2)
            task = await uow.get_task(UUID(task_value))
            if task is None:
                raise TaskError("Stored cancellation task no longer exists.")
            request_id = UUID(metadata[0]) if metadata else None
            reason = metadata[1] if len(metadata) > 1 else None
            return TaskCancellationOutcome(task, request_id, status, reason)
    if outcome.startswith("task_cancel_request:"):
        task_value, request_value = outcome.removeprefix("task_cancel_request:").split(":", 1)
        task = await uow.get_task(UUID(task_value))
        if task is None:
            raise TaskError("Stored cancellation task no longer exists.")
        return TaskCancellationOutcome(task, UUID(request_value), "pending")
    raise TaskError("Telegram update belongs to another operation.")


async def _active_actor(uow: TaskUnitOfWork, telegram_user_id: int) -> Member:
    actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None:
        raise PermissionError("Task actor is not a registered member.")
    _require_active(actor)
    return actor


def _require_active(actor: Member) -> None:
    if actor.status is not MemberStatus.ACTIVE:
        raise PermissionError("Task workflow requires an active member.")


def _require_superadministrator(actor: Member) -> None:
    if actor.status is not MemberStatus.ACTIVE or not is_superadministrator(actor):
        raise PermissionError("Only a superadministrator may perform this action.")


def _expect(draft: TaskDraft, step: TaskDraftStep, revision: int) -> None:
    if draft.current_step is not step or draft.revision != revision:
        raise StaleTaskDraftError("Task draft step or revision is stale.")


def _advance_draft(draft: TaskDraft, template: CatalogTemplate, value: object) -> TaskDraft:
    changes: dict[str, object]
    if draft.current_step is TaskDraftStep.INPUT:
        if not isinstance(value, Mapping):
            raise TaskError("Task input must be an object.")
        normalized = (
            _plain_input_payload(template.input_schema, str(value["_plain_text"]))
            if set(value) == {"_plain_text"}
            else value
        )
        changes = {
            "input_payload": validate_payload(template.input_schema, normalized),
            "current_step": TaskDraftStep.DEADLINE,
        }
    elif draft.current_step is TaskDraftStep.DEADLINE:
        if not isinstance(value, datetime.datetime):
            raise TaskError("Task deadline must be a datetime.")
        changes = {
            "deadline_at": validate_deadline(value, now=_utc_now()),
            "current_step": TaskDraftStep.FORMAT,
        }
    elif draft.current_step is TaskDraftStep.FORMAT:
        if not isinstance(value, tuple) or len(value) != _FORMAT_VALUE_SIZE:
            raise TaskError("Task format value must include format and city.")
        task_format, city = value
        if not isinstance(task_format, TaskFormat) or not (isinstance(city, str) or city is None):
            raise TaskError("Task format value is invalid.")
        selected, normalized_city = validate_task_format(
            task_format, template_format=template.format, city=city
        )
        changes = {
            "format": selected,
            "city": normalized_city,
            "current_step": TaskDraftStep.MATERIALS,
        }
    elif draft.current_step is TaskDraftStep.MATERIALS:
        if not isinstance(value, Mapping):
            raise TaskError("Task materials must be an object.")
        changes = {"materials": validate_materials(value), "current_step": TaskDraftStep.SLOTS}
    elif draft.current_step is TaskDraftStep.SLOTS:
        if value is None:
            if draft.performer_slots is None:
                raise TaskError("Task performer slots are missing.")
            changes = {"current_step": TaskDraftStep.PREVIEW}
        else:
            if not isinstance(value, int) or isinstance(value, bool):
                raise TaskError("Task performer slots must be an integer.")
            changes = {
                "performer_slots": validate_slots(value, maximum=template.maximum_performers)
            }
    else:
        raise TaskError("Task draft cannot advance from its current step.")
    changes["revision"] = draft.revision + 1
    return _replace_draft(draft, **changes)


def _validate_publishable(draft: TaskDraft, template: CatalogTemplate) -> None:
    if draft.input_payload is None or draft.deadline_at is None or draft.format is None:
        raise TaskError("Task draft is incomplete.")
    if draft.materials is None or draft.performer_slots is None:
        raise TaskError("Task draft is incomplete.")
    validate_payload(template.input_schema, draft.input_payload)
    validate_public_text_uris(draft.input_payload)
    validate_materials(draft.materials)
    validate_deadline(draft.deadline_at, now=_utc_now())
    validate_task_format(draft.format, template_format=template.format, city=draft.city)
    validate_slots(draft.performer_slots, maximum=template.maximum_performers)


def _plain_input_payload(schema: Mapping[str, object], text: str) -> dict[str, object]:
    """Map one human description to a template's required fields without JSON input."""
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise TaskError("Task input schema is invalid.")
    payload: dict[str, object] = {}
    for key in required:
        if not isinstance(key, str) or not isinstance(properties.get(key), Mapping):
            raise TaskError("Task input schema is invalid.")
        field_type = properties[key].get("type")
        if field_type == "array":
            payload[key] = [text]
        elif field_type == "integer":
            payload[key] = 1
        elif field_type == "number":
            payload[key] = 1.0
        elif field_type == "boolean":
            payload[key] = True
        else:
            payload[key] = text
    return payload


def _schema_property_keys(schema: Mapping[str, object]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise TaskError("Task input schema is invalid.")
    return tuple(key for key in properties if isinstance(key, str))


def _replace_draft(draft: TaskDraft, **changes: object) -> TaskDraft:
    values = {field: getattr(draft, field) for field in draft.__dataclass_fields__}
    values.update(changes)
    return TaskDraft(**values)


async def _request_community_publication(
    *,
    uow: TaskUnitOfWork,
    update_id: int,
    actor: Member,
    draft: TaskDraft,
) -> TaskDraft:
    new_request = draft.community_approval_requested_at is None
    updated = (
        await uow.save_task_draft(
            _replace_draft(
                draft,
                community_approval_requested_at=_utc_now(),
                community_approved_by_admin_id=None,
                community_approved_at=None,
                revision=draft.revision + 1,
            )
        )
        if new_request
        else draft
    )
    if new_request:
        await uow.claim_text_flow(
            member_id=actor.id,
            flow_type="task",
            step=updated.current_step.value,
            reference_id=updated.id,
            revision=updated.revision,
        )
        await uow.append_audit_event(
            actor_member_id=actor.id,
            action="community_task_publication_requested",
            entity_type="task_draft",
            entity_id=str(updated.id),
            reason=None,
        )
    await _finish_receipt(uow, update_id, actor, f"task_approval_pending:{updated.id}")
    return updated


async def _publish_locked_draft(
    *,
    uow: TaskUnitOfWork,
    update_id: int,
    actor: Member,
    draft: TaskDraft,
    template: CatalogTemplate,
) -> PublishedTask:
    task = await uow.insert_published_task(draft=draft, template=template)
    await uow.save_task_draft(
        _replace_draft(
            draft,
            current_step=TaskDraftStep.PUBLISHED,
            is_current=False,
            revision=draft.revision + 1,
        )
    )
    await uow.clear_text_flow(member_id=draft.creator_id, flow_type="task", reference_id=draft.id)
    await uow.append_audit_event(
        actor_member_id=actor.id,
        action="task_published",
        entity_type="task",
        entity_id=str(task.id),
        reason=None,
    )
    await uow.add_task_outbox(
        event_type="task.published",
        task=task,
        business_key=f"task.published:{task.id}",
    )
    await _finish_receipt(uow, update_id, actor, f"task:{task.id}")
    return task


async def _finish(
    uow: TaskUnitOfWork,
    update_id: int,
    actor: Member,
    outcome: str,
    entity_type: str,
) -> None:
    await uow.append_audit_event(
        actor_member_id=actor.id,
        action="task_draft_changed",
        entity_type=entity_type,
        entity_id=outcome.split(":", 1)[-1],
        reason=outcome,
    )
    await _finish_receipt(uow, update_id, actor, outcome)


async def _finish_receipt(uow: TaskUnitOfWork, update_id: int, actor: Member, outcome: str) -> None:
    await uow.add_receipt(
        update_id=update_id,
        update_type="task_workflow",
        actor_id=actor.id,
        outcome_code=outcome,
    )
    await uow.commit()


async def _draft_from_outcome(uow: TaskUnitOfWork, outcome: str) -> TaskDraft | None:
    if outcome == "task_draft:none":
        return None
    if not outcome.startswith("task_draft:"):
        raise TaskError("Telegram update was already used by another operation.")
    return await uow.get_task_draft(UUID(outcome.split(":", 1)[1]))


async def _publication_from_outcome(uow: TaskUnitOfWork, outcome: str) -> PublishedTask | TaskDraft:
    if outcome.startswith("task_approval_pending:"):
        draft = await uow.get_task_draft(UUID(outcome.split(":", 1)[1]))
        if draft is None:
            raise TaskError("Stored community approval request no longer exists.")
        return draft
    return await _task_from_outcome(uow, outcome)


async def _task_from_outcome(uow: TaskUnitOfWork, outcome: str) -> PublishedTask:
    if not outcome.startswith("task:"):
        raise TaskError("Telegram update was already used by another operation.")
    task = await uow.get_task(UUID(outcome.split(":", 1)[1]))
    if task is None:
        raise TaskError("Stored task outcome no longer exists.")
    return task


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
