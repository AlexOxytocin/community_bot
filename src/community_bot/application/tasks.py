"""Application workflows for persistent task creation and reservation."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import UUID

from community_bot.application.cities import canonical_task_city
from community_bot.domain.assignments import AssignmentStatus
from community_bot.domain.catalog import TaskFormat, validate_payload
from community_bot.domain.economy import ResolvedLevel, refund_reward, reserve_reward
from community_bot.domain.members import (
    Member,
    MemberRole,
    MemberStatus,
    can_create_community_task,
    is_superadministrator,
)
from community_bot.domain.moderation import RestrictedAction
from community_bot.domain.tasks import (
    TASK_TIME_SIZE_SPECS,
    AcceptanceTaskSnapshot,
    StaleTaskDraftError,
    TaskDraftStep,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
    validate_acceptance_actor,
    validate_deadline,
    validate_freeform_materials,
    validate_freeform_reward,
    validate_freeform_slots,
    validate_freeform_text,
    validate_materials,
    validate_public_text_uris,
    validate_slots,
    validate_task_format,
    validate_task_kind,
    validate_time_size,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from community_bot.application.catalog import CatalogTemplate
    from community_bot.application.economy import ActiveProductConfig, EconomyMutationPort
    from community_bot.application.identity import ActorContext
    from community_bot.domain.assignments import Assignment

_MAX_OWNED_TASKS = 20
_MAX_AVAILABLE_TASKS = 10
_MAX_COMMUNITY_PUBLICATION_REQUESTS = 20
_MAX_CANCELLATION_RESPONSES = 50
_FORMAT_VALUE_SIZE = 2
_COMMUNITY_CATEGORY_CODE = "community_development"
_COMMUNITY_TASK_MAX_REWARD = 10
TaskCancellationStatus = Literal["cancelled", "pending", "closed", "declined", "obsolete"]


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
    template_id: UUID | None
    category_id: UUID | None
    task_kind: TaskKind | None
    time_size: TaskTimeSize | None
    title: str | None
    description: str | None
    completion_criteria: str | None
    credit_reward_per_performer: int | None
    estimated_minutes: int | None
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
    category_name: str | None
    category_icon: str | None
    task_kind: TaskKind | None
    time_size: TaskTimeSize | None
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
    template_id: UUID | None
    template_version: int | None
    category_name: str | None
    category_icon: str | None
    task_kind: TaskKind | None
    time_size: TaskTimeSize | None
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
    updated_at: datetime.datetime
    closed_for_new_performers_at: datetime.datetime | None = None
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
    member_id: UUID
    display_name: str
    status: str


@dataclass(frozen=True, slots=True)
class OwnedTaskCard:
    """Owned task plus occupancy and cancellation-request context."""

    task: PublishedTask
    assignees: tuple[OwnedTaskAssignee, ...]
    cancellation_status: str | None
    cancellation_action: Literal["cancel", "request"] | None = None


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
    status: TaskCancellationStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AdministratorOption:
    """Safe administrator choice shown during community task creation."""

    id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class TaskCategoryOption:
    """Creator-facing task category available in the current role."""

    id: UUID
    code: str
    name: str
    description: str
    icon: str
    visibility: str


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
    actor_telegram_user_id: int | None
    draft_id: UUID
    expected_revision: int
    actor_member_id: UUID | None = None
    replay_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class SaveWebTaskDraftCommand:
    """Atomically persist one complete Mini App task form as a preview."""

    update_id: int
    actor_member_id: UUID
    draft_id: UUID
    expected_revision: int
    category_id: UUID
    task_kind: TaskKind
    time_size: TaskTimeSize
    title: str
    description: str
    completion_criteria: str
    credit_reward_per_performer: int
    deadline_at: datetime.datetime
    format: TaskFormat
    city: str | None
    materials: Mapping[str, object]
    performer_slots: int
    replay_fingerprint: str


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
    async def get_member(self, member_id: UUID) -> Member | None: ...
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
    async def list_task_categories(
        self, *, actor_role: MemberRole
    ) -> tuple[TaskCategoryOption, ...]: ...
    async def task_category_for_creation(
        self, *, category_id: UUID, actor_role: MemberRole
    ) -> TaskCategoryOption | None: ...
    async def member_display_name(self, member_id: UUID) -> str: ...
    async def create_task_draft(
        self, *, creator_id: UUID, template_id: UUID | None, origin: str = "member"
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
        self, *, draft: TaskDraft, template: CatalogTemplate | None
    ) -> PublishedTask: ...
    async def get_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def lock_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def list_task_assignments(
        self, task_id: UUID, *, for_update: bool = False
    ) -> tuple[Assignment, ...]: ...
    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask: ...
    async def close_task_for_new_performers(
        self, *, task_id: UUID, now: datetime.datetime
    ) -> PublishedTask: ...
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
    async def list_pending_task_cancellation_responses(
        self, *, performer_id: UUID, limit: int
    ) -> tuple[TaskCancellationResponse, ...]: ...
    async def answer_task_cancellation(
        self, *, response_id: UUID, accepted: bool, now: datetime.datetime
    ) -> TaskCancellationResponse: ...
    async def task_cancellation_all_accepted(self, request_id: UUID) -> bool: ...
    async def task_cancellation_all_answered(self, request_id: UUID) -> bool: ...
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
    async def ensure_task_test_access(
        self, *, member_id: UUID, task_id: UUID | None = None, draft_id: UUID | None = None
    ) -> None: ...
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


def _owned_cancellation_action(
    card: OwnedTaskCard, now: datetime.datetime
) -> Literal["cancel", "request"] | None:
    """Project the existing cancellation command selected by the task engine."""
    task = card.task
    if (
        card.cancellation_status == "pending"
        or task.deadline_at <= now
        or task.status not in {TaskStatus.PUBLISHED, TaskStatus.PARTIALLY_COMPLETED}
    ):
        return None
    occupied = len(card.assignees)
    if task.status is TaskStatus.PARTIALLY_COMPLETED and occupied >= task.performer_slots:
        return None
    return "request" if occupied else "cancel"


class TaskService:
    """Coordinate persistent drafts, publication, ownership, and cancellation."""

    def __init__(self, unit_of_work_factory: TaskUnitOfWorkFactory) -> None:
        """Configure the shared caller-owned transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def start(  # noqa: PLR0913, PLR0915
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int | None,
        template_id: UUID | None,
        origin: str = "member",
        actor_member_id: UUID | None = None,
        replay_fingerprint: str | None = None,
        replace_current: tuple[UUID, int] | None = None,
    ) -> TaskDraft | None:
        """Create a new current draft or resume the existing current draft."""
        async with self._unit_of_work_factory() as uow:
            if actor_member_id is None:
                replay = await _begin_update(uow, update_id)
                if replay is not None:
                    return await _draft_from_outcome(uow, replay)
                if actor_telegram_user_id is None:
                    raise PermissionError("Task actor identity is missing.")
                await uow.acquire_task_identity_gate(actor_telegram_user_id)
                actor = await _active_actor(uow, actor_telegram_user_id)
            else:
                actor = await _active_context_actor(uow, actor_member_id)
                await uow.acquire_task_identity_gate(actor.telegram_user_id)
                replay = await _begin_update(uow, update_id)
                if replay is not None:
                    return await _web_draft_replay(uow, replay, actor.id, replay_fingerprint or "")
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.CREATE_TASK)
            if template_id is None:
                if replace_current is not None:
                    source_id, source_revision = replace_current
                    source = await uow.lock_task_draft(source_id)
                    if (
                        source is None
                        or source.creator_id != actor.id
                        or source.template_id is not None
                        or source.origin not in {"member", "community"}
                    ):
                        raise PermissionError("Task draft is unavailable.")
                    await uow.ensure_task_test_access(draft_id=source.id, member_id=actor.id)
                    if not source.is_current or source.revision != source_revision:
                        raise StaleTaskDraftError("Task draft step or revision is stale.")
                    draft = None
                else:
                    draft = await uow.get_current_task_draft(actor.id)
                if draft is not None and actor_member_id is not None:
                    draft = None if draft.template_id is not None else draft
                if draft is not None and actor_member_id is not None:
                    try:
                        await uow.ensure_task_test_access(draft_id=draft.id, member_id=actor.id)
                    except PermissionError:
                        draft = None
                if draft is None:
                    if origin != "member":
                        raise TaskError("Free-form community task creation is unavailable.")
                    draft = await uow.create_task_draft(
                        creator_id=actor.id,
                        template_id=None,
                        origin=origin,
                    )
                    if actor_member_id is not None:
                        draft = await uow.save_task_draft(
                            _replace_draft(draft, format=TaskFormat.ONLINE)
                        )
                outcome = f"task_draft:{draft.id}"
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
                if origin == "community" and not can_create_community_task(actor):
                    raise PermissionError("Community task creation permission is required.")
                draft = await uow.create_task_draft(
                    creator_id=actor.id,
                    template_id=template.id,
                    origin=origin,
                )
                outcome = f"task_draft:{draft.id}"
            if draft is not None and actor_member_id is None:
                await uow.claim_text_flow(
                    member_id=actor.id,
                    flow_type="task",
                    step=draft.current_step.value,
                    reference_id=draft.id,
                    revision=draft.revision,
                )
            if actor_member_id is None:
                await _finish(uow, update_id, actor, outcome, "task_draft")
            else:
                await _finish_receipt(
                    uow,
                    update_id,
                    actor,
                    f"web_task_draft:{draft.id}:{replay_fingerprint}",
                )
            return draft

    async def web_state(  # noqa: PLR0911
        self, actor_member_id: UUID
    ) -> tuple[tuple[TaskCategoryOption, ...], TaskDraft | None, TaskPreview | None, bool]:
        """Return the actor's scoped free-form draft and valid preview, if any."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_context_actor(uow, actor_member_id)
            categories = _categories_for_actor(
                await uow.list_task_categories(actor_role=actor.role), actor
            )
            draft = await uow.get_current_task_draft(actor.id)
            if draft is None:
                return categories, None, None, False
            try:
                await uow.ensure_task_test_access(draft_id=draft.id, member_id=actor.id)
            except PermissionError:
                return categories, None, None, False
            if draft.template_id is not None:
                return categories, None, None, False
            if draft.origin == "community" and not can_create_community_task(actor):
                return categories, draft, None, True
            if draft.current_step is not TaskDraftStep.PREVIEW:
                return categories, draft, None, False
            category = next((item for item in categories if item.id == draft.category_id), None)
            try:
                return categories, draft, await _freeform_preview(uow, draft, category), False
            except TaskError:
                return categories, draft, None, True

    async def save_web(self, command: SaveWebTaskDraftCommand) -> TaskDraft:
        """Validate and save the complete fixed form under one draft lock."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_context_actor(uow, command.actor_member_id)
            await uow.acquire_task_identity_gate(actor.telegram_user_id)
            replay = await _begin_update(uow, command.update_id)
            if replay is not None:
                return await _web_draft_replay(uow, replay, actor.id, command.replay_fingerprint)
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.CREATE_TASK)
            draft = await uow.lock_task_draft(command.draft_id)
            if (
                draft is None
                or draft.creator_id != actor.id
                or draft.template_id is not None
                or draft.origin not in {"member", "community"}
            ):
                raise PermissionError("Task draft is unavailable.")
            await uow.ensure_task_test_access(draft_id=draft.id, member_id=actor.id)
            _expect(draft, draft.current_step, command.expected_revision)
            category = await uow.task_category_for_creation(
                category_id=command.category_id, actor_role=actor.role
            )
            category = _category_for_actor(category, actor)
            if category is None:
                raise PermissionError("Task category is unavailable to this administrator.")
            draft_origin = "community" if category.code == _COMMUNITY_CATEGORY_CODE else "member"
            requested_city = (
                canonical_task_city(command.city) if command.format is TaskFormat.OFFLINE else None
            )
            task_format, city = validate_task_format(
                command.format, template_format=TaskFormat.ANY, city=requested_city
            )
            candidate = _replace_draft(
                draft,
                category_id=command.category_id,
                task_kind=command.task_kind,
                time_size=command.time_size,
                title=validate_freeform_text(command.title, field="title"),
                description=validate_freeform_text(command.description, field="description"),
                completion_criteria=validate_freeform_text(
                    command.completion_criteria, field="completion_criteria"
                ),
                credit_reward_per_performer=command.credit_reward_per_performer,
                estimated_minutes=TASK_TIME_SIZE_SPECS[command.time_size].estimated_minutes,
                deadline_at=validate_deadline(command.deadline_at, now=_utc_now()),
                format=task_format,
                city=city,
                materials=validate_freeform_materials(command.materials),
                performer_slots=command.performer_slots,
                origin=draft_origin,
                reviewer_admin_id=None,
                community_approval_requested_at=None,
                community_approved_by_admin_id=None,
                community_approved_at=None,
                current_step=TaskDraftStep.PREVIEW,
                revision=draft.revision + 1,
            )
            _validate_freeform_publishable(candidate, category)
            saved = await uow.save_task_draft(candidate)
            await _finish_receipt(
                uow,
                command.update_id,
                actor,
                f"web_task_draft:{saved.id}:{command.replay_fingerprint}",
            )
            return saved

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

    async def task_categories(self, actor_telegram_user_id: int) -> tuple[TaskCategoryOption, ...]:
        """List free-form categories visible to the active creator."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            return _categories_for_actor(
                await uow.list_task_categories(actor_role=actor.role), actor
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

    async def edit_draft_step(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        draft_id: UUID,
        expected_revision: int,
        step: TaskDraftStep,
    ) -> TaskDraft:
        """Move a preview draft back to one editable step."""
        editable = {
            TaskDraftStep.TASK_KIND,
            TaskDraftStep.CATEGORY,
            TaskDraftStep.TIME_SIZE,
            TaskDraftStep.SLOTS,
            TaskDraftStep.REWARD,
            TaskDraftStep.TITLE,
            TaskDraftStep.DESCRIPTION,
            TaskDraftStep.COMPLETION_CRITERIA,
            TaskDraftStep.INPUT,
            TaskDraftStep.MATERIALS,
            TaskDraftStep.DEADLINE,
            TaskDraftStep.FORMAT,
        }
        if step not in editable:
            raise TaskError("Task draft step is not editable.")
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                draft = await _draft_from_outcome(uow, replay)
                if draft is None:
                    raise TaskError("Stored task draft does not exist.")
                return draft
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            draft = await uow.lock_task_draft(draft_id)
            if draft is None or draft.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this member.")
            if draft.current_step is not TaskDraftStep.PREVIEW:
                raise StaleTaskDraftError("Task draft step or revision is stale.")
            if expected_revision > draft.revision:
                raise StaleTaskDraftError("Task draft step or revision is stale.")
            if draft.template_id is None and step is TaskDraftStep.INPUT:
                raise TaskError("Free-form task input is not editable.")
            if draft.template_id is not None and step not in {
                TaskDraftStep.INPUT,
                TaskDraftStep.MATERIALS,
                TaskDraftStep.DEADLINE,
                TaskDraftStep.FORMAT,
                TaskDraftStep.SLOTS,
            }:
                raise TaskError("Legacy task step is not editable.")
            if (
                draft.template_id is None
                and step is TaskDraftStep.SLOTS
                and draft.task_kind is TaskKind.SOLO
            ):
                raise TaskError("Solo task performer count is fixed.")
            updated = await uow.save_task_draft(
                _replace_draft(draft, current_step=step, revision=draft.revision + 1)
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

    async def adjust_draft_slots(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        draft_id: UUID,
        expected_revision: int,
        delta: int,
    ) -> TaskDraft:
        """Adjust a free-form group slot counter without leaving its draft step."""
        if delta not in {-5, -1, 1, 5}:
            raise TaskError("Task performer slot adjustment is invalid.")
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                draft = await _draft_from_outcome(uow, replay)
                if draft is None:
                    raise TaskError("Stored task draft does not exist.")
                return draft
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
            draft = await uow.lock_task_draft(draft_id)
            if draft is None or draft.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this member.")
            _expect(draft, TaskDraftStep.SLOTS, expected_revision)
            if draft.template_id is not None or draft.task_kind is not TaskKind.GROUP:
                raise TaskError("Task performer slot counter is unavailable.")
            current = validate_freeform_slots(draft.performer_slots or 2, kind=draft.task_kind)
            updated = await uow.save_task_draft(
                _replace_draft(
                    draft,
                    performer_slots=max(2, current + delta),
                    revision=draft.revision + 1,
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
            if draft.template_id is None:
                if draft.current_step is TaskDraftStep.CATEGORY:
                    if not isinstance(command.value, UUID):
                        raise TaskError("Task category is invalid.")
                    category = await uow.task_category_for_creation(
                        category_id=command.value,
                        actor_role=actor.role,
                    )
                    if category is None:
                        raise PermissionError("Task category is unavailable.")
                updated = _advance_freeform_draft(draft, command.value)
            else:
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
        async with self._unit_of_work_factory() as uow:
            actor = await _active_actor(uow, actor_telegram_user_id)
            draft = await uow.get_task_draft(draft_id)
            if draft is None or draft.creator_id != actor.id:
                raise PermissionError("Task draft is not owned by this member.")
        if draft.template_id is not None and draft.current_step is TaskDraftStep.SLOTS:
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
        elif draft.current_step is not TaskDraftStep.PREVIEW or draft.revision != expected_revision:
            raise StaleTaskDraftError("Task draft step or revision is stale.")
        async with self._unit_of_work_factory() as uow:
            category = (
                None
                if draft.category_id is None
                else await uow.task_category_for_creation(
                    category_id=draft.category_id,
                    actor_role=(await _active_actor(uow, actor_telegram_user_id)).role,
                )
            )
            if draft.template_id is None:
                return await _freeform_preview(uow, draft, category)
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
                None,
                None,
                None,
                None,
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
            if command.actor_member_id is None:
                replay = await _begin_update(uow, command.update_id)
                if replay is not None:
                    return await _publication_from_outcome(uow, replay)
                if command.actor_telegram_user_id is None:
                    raise PermissionError("Task actor identity is missing.")
                await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
                web_actor = None
            else:
                web_actor = await _active_context_actor(uow, command.actor_member_id)
                await uow.acquire_task_identity_gate(web_actor.telegram_user_id)
                replay = await _begin_update(uow, command.update_id)
                if replay is not None:
                    return await _web_publication_replay(
                        uow,
                        replay,
                        web_actor.id,
                        command.draft_id,
                        command.replay_fingerprint or "",
                    )
            preliminary = await uow.get_task_draft(command.draft_id)
            if preliminary is None or (
                web_actor is not None
                and (
                    preliminary.creator_id != web_actor.id
                    or preliminary.template_id is not None
                    or preliminary.origin not in {"member", "community"}
                )
            ):
                raise TaskError("Task draft does not exist.")
            if web_actor is not None:
                await uow.ensure_task_test_access(draft_id=preliminary.id, member_id=web_actor.id)
            await uow.acquire_task_command_gate(preliminary.publish_command_id)
            await uow.acquire_catalog_mutation_gate()
            template_before = (
                None
                if preliminary.template_id is None
                else await uow.catalog_template(preliminary.template_id)
            )
            actor_snapshot = (
                web_actor
                if web_actor is not None
                else await _active_actor(uow, command.actor_telegram_user_id or 0)
            )
            if preliminary.origin == "community" and not can_create_community_task(actor_snapshot):
                raise PermissionError("Community task creation permission is required.")
            category_before = (
                None
                if preliminary.category_id is None
                else await uow.task_category_for_creation(
                    category_id=preliminary.category_id,
                    actor_role=actor_snapshot.role,
                )
            )
            if preliminary.template_id is None:
                _validate_freeform_publishable(preliminary, category_before)
            elif template_before is None or preliminary.performer_slots is None:
                raise TaskError("Task draft is incomplete.")
            await uow.ensure_moderation_action_allowed(
                preliminary.creator_id, RestrictedAction.CREATE_TASK
            )
            prepared = None
            if preliminary.origin == "community" and preliminary.template_id is not None:
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
            elif preliminary.origin == "community":
                actor = (await uow.lock_members((preliminary.creator_id,)))[preliminary.creator_id]
                if not can_create_community_task(actor):
                    raise PermissionError("Community task creation permission is required.")
                reserve_total = 0
            else:
                if preliminary.template_id is None:
                    if (
                        preliminary.credit_reward_per_performer is None
                        or preliminary.performer_slots is None
                    ):
                        raise TaskError("Task draft is incomplete.")
                    reserve_total = (
                        preliminary.credit_reward_per_performer * preliminary.performer_slots
                    )
                else:
                    if template_before is None or preliminary.performer_slots is None:
                        raise TaskError("Task draft is incomplete.")
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
            if web_actor is None and actor.telegram_user_id != command.actor_telegram_user_id:
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
                await _finish_receipt(
                    uow,
                    command.update_id,
                    actor,
                    _web_task_outcome(existing.id, draft.id, command.replay_fingerprint)
                    if web_actor is not None
                    else f"task:{existing.id}",
                )
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
            if draft.template_id is None:
                category = (
                    None
                    if draft.category_id is None
                    else await uow.task_category_for_creation(
                        category_id=draft.category_id,
                        actor_role=actor.role,
                    )
                )
                _validate_freeform_publishable(draft, category)
                template = None
            else:
                template = await uow.template_for_creation(
                    template_id=draft.template_id, level=level.level_number
                )
                if template is None:
                    raise PermissionError("Task template is no longer publishable.")
                _validate_publishable(draft, template)
            if draft.origin == "community":
                expected_reserve = 0
            elif draft.template_id is None:
                if draft.credit_reward_per_performer is None or draft.performer_slots is None:
                    raise TaskError("Task draft is incomplete.")
                expected_reserve = draft.credit_reward_per_performer * draft.performer_slots
            else:
                if template is None or draft.performer_slots is None:
                    raise TaskError("Task draft is incomplete.")
                expected_reserve = template.credit_reward * draft.performer_slots
            if expected_reserve != reserve_total:
                raise TaskError("Task reserve changed after preview.")
            if (
                draft.origin == "community"
                and draft.template_id is not None
                and not is_superadministrator(actor)
            ):
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
                web_fingerprint=command.replay_fingerprint if web_actor is not None else None,
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
            if draft.template_id is None:
                raise TaskError("Community task template is required.")
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

    async def list_owned_cards(  # noqa: PLR0913
        self,
        *,
        actor_telegram_user_id: int | None = None,
        actor: ActorContext | None = None,
        limit: int = 20,
        status: TaskStatus | None = None,
        cursor: tuple[datetime.datetime, UUID] | None = None,
        creator_only: bool = False,
        order_by_updated_at: bool = False,
    ) -> tuple[OwnedTaskCard, ...]:
        """Return compact-card context for tasks visible to one owner or reviewer."""
        if not 1 <= limit <= _MAX_OWNED_TASKS:
            raise TaskError("Owned task page size must be between 1 and 20.")
        if (actor_telegram_user_id is None) == (actor is None):
            raise TaskError("Exactly one task actor identity is required.")
        async with self._unit_of_work_factory() as uow:
            member = (
                await _active_context_actor(uow, actor)
                if actor is not None
                else await _active_actor(uow, cast("int", actor_telegram_user_id))
            )
            cards = await uow.list_owned_task_cards(
                creator_id=member.id,
                limit=limit,
                status=status,
                before_created_at=None if cursor is None else cursor[0],
                before_id=None if cursor is None else cursor[1],
                creator_only=creator_only,
                order_by_updated_at=order_by_updated_at,
            )
            now = _utc_now()
            return tuple(
                replace(card, cancellation_action=_owned_cancellation_action(card, now))
                for card in cards
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
        actor: ActorContext,
        cursor_task_id: UUID | None = None,
        limit: int = _MAX_AVAILABLE_TASKS,
    ) -> AvailableTaskPage:
        """Return tasks the actor may attempt to accept right now."""
        async with self._unit_of_work_factory() as uow:
            member = await _active_context_actor(uow, actor)
            await uow.ensure_moderation_action_allowed(member.id, RestrictedAction.ACCEPT_TASK)
            active = await uow.get_active_product_config()
            assignment_limit = 3 if active is None else active.maximum_active_assignments
            if await uow.count_active_assignments(member.id) >= assignment_limit:
                return AvailableTaskPage(items=(), next_cursor_task_id=None)
            level = await uow.resolve_member_level(member.id)
            page_limit = max(1, min(limit, 50))
            tasks = await uow.list_available_tasks(
                performer_id=member.id,
                level=level.level_number,
                limit=page_limit + 1,
                cursor_task_id=cursor_task_id,
                now=datetime.datetime.now(datetime.UTC),
            )
        items = tasks[:page_limit]
        return AvailableTaskPage(
            items=items,
            next_cursor_task_id=items[-1].id if len(tasks) > page_limit else None,
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

    async def request_cancellation(  # noqa: PLR0915 - existing exact cancellation transaction.
        self,
        *,
        update_id: int,
        task_id: UUID,
        actor_telegram_user_id: int | None = None,
        actor: ActorContext | None = None,
    ) -> TaskCancellationOutcome:
        """Close performer intake and ask accepted performers for cancellation consent."""
        if (actor_telegram_user_id is None) == (actor is None):
            raise TaskError("Exactly one task actor identity is required.")
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                outcome = await _cancellation_outcome_from_receipt(uow, replay)
                if actor is not None:
                    replay_actor = await _active_context_actor(uow, actor)
                    await uow.ensure_task_test_access(
                        task_id=outcome.task.id, member_id=replay_actor.id
                    )
                return outcome
            member = (
                await _active_context_actor(uow, actor)
                if actor is not None
                else await _active_actor(uow, cast("int", actor_telegram_user_id))
            )
            await uow.acquire_task_identity_gate(member.telegram_user_id)
            preliminary = await uow.get_task(task_id)
            if preliminary is None:
                raise TaskError("Task does not exist.")
            await uow.acquire_assignment_task_gate(task_id)
            await uow.acquire_task_command_gate(task_id)
            task = await uow.lock_task(task_id)
            if task is None or task.creator_id is None:
                raise PermissionError("Only the member task creator can cancel this task.")
            if member.id != task.creator_id:
                raise PermissionError("Only the task creator can cancel this task.")
            await uow.ensure_task_test_access(task_id=task.id, member_id=member.id)
            if task.status is TaskStatus.CANCELLED:
                await _finish_receipt(uow, update_id, member, f"task_cancelled:{task.id}")
                return TaskCancellationOutcome(task, None, "cancelled")
            if task.status not in {TaskStatus.PUBLISHED, TaskStatus.PARTIALLY_COMPLETED}:
                raise TaskError("Task cannot be cancelled from its current state.")
            if _utc_now() >= task.deadline_at:
                raise TaskError("Task cancellation deadline has passed.")
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            latest = _latest_slot_assignments(assignments)
            occupied = [item for item in latest if item.status is not AssignmentStatus.CANCELLED]
            active = _active_slot_assignments(latest)
            free_slots = max(0, task.performer_slots - len(occupied))
            if task.status is TaskStatus.PARTIALLY_COMPLETED and free_slots == 0:
                raise TaskError("Task has no free performer slots to release.")
            if not occupied:
                prepared = await uow.economy.prepare_batch(
                    (
                        refund_reward(
                            member_id=member.id,
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
                    actor_member_id=member.id,
                    action="task_cancelled",
                    entity_type="task",
                    entity_id=str(task.id),
                    reason="assignment_slots_released",
                )
                await _finish_receipt(uow, update_id, member, f"task_cancelled:{task.id}")
                return TaskCancellationOutcome(task, None, "cancelled")
            pending = await uow.get_pending_task_cancellation(task.id)
            if pending is not None:
                raise TaskError("A cancellation request is already awaiting performer responses.")
            if free_slots:
                prepared = await uow.economy.prepare_batch(
                    (
                        refund_reward(
                            member_id=member.id,
                            amount=free_slots * task.credit_reward_per_performer,
                            idempotency_key=f"task_close:{task.id}:free_slots:refund",
                        ),
                    )
                )
                await prepared.apply()
            task = await uow.close_task_for_new_performers(task_id=task.id, now=_utc_now())
            accepted = [item for item in active if item.status is AssignmentStatus.ACCEPTED]
            request_id = (
                await uow.create_task_cancellation(
                    task_id=task.id,
                    creator_id=member.id,
                    assignments=accepted,
                )
                if accepted
                else None
            )
            await uow.append_audit_event(
                actor_member_id=member.id,
                action="task_intake_closed",
                entity_type="task",
                entity_id=str(task.id),
                reason="creator_closed_group_intake",
            )
            if request_id is None:
                await _finish_receipt(uow, update_id, member, f"task_closed:{task.id}")
                return TaskCancellationOutcome(task, None, "closed")
            await _finish_receipt(
                uow,
                update_id,
                member,
                f"task_cancel_request:{task.id}:{request_id}",
            )
            return TaskCancellationOutcome(task, request_id, "pending")

    async def pending_cancellation_responses(
        self,
        *,
        actor: ActorContext,
        limit: int = 50,
    ) -> tuple[TaskCancellationResponse, ...]:
        """Return performer-owned cancellation responses that still need a decision."""
        if not 1 <= limit <= _MAX_CANCELLATION_RESPONSES:
            raise TaskError("Cancellation response page size must be between 1 and 50.")
        async with self._unit_of_work_factory() as uow:
            member = await _active_context_actor(uow, actor)
            return await uow.list_pending_task_cancellation_responses(
                performer_id=member.id,
                limit=limit,
            )

    async def respond_cancellation(
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
                task.status in {TaskStatus.PUBLISHED, TaskStatus.CLOSED_FOR_NEW_PERFORMERS}
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
            if response.request_status != "pending" or response.response_status != "pending":
                raise TaskError("Cancellation request is no longer active.")
            if task.status not in {TaskStatus.PUBLISHED, TaskStatus.CLOSED_FOR_NEW_PERFORMERS}:
                raise TaskError("Cancellation request is no longer active.")
            response = await uow.answer_task_cancellation(
                response_id=response.id, accepted=accepted, now=now
            )
            if not accepted:
                if await uow.task_cancellation_all_answered(response.request_id):
                    await uow.resolve_task_cancellation(
                        request_id=response.request_id,
                        status="completed",
                        reason="performer_continues",
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
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            for assignment in assignments:
                if (
                    assignment.id == response.assignment_id
                    and assignment.status is AssignmentStatus.ACCEPTED
                ):
                    await uow.cancel_assignment_by_creator(
                        assignment.id,
                        task.creator_id,
                        "creator_cancellation_approved",
                    )
            prepared = await uow.economy.prepare_batch(
                (
                    refund_reward(
                        member_id=task.creator_id,
                        amount=task.credit_reward_per_performer,
                        idempotency_key=f"task_cancel:{task.id}:{response.assignment_id}:refund",
                    ),
                )
            )
            await prepared.apply()
            if await uow.task_cancellation_all_answered(response.request_id):
                await uow.resolve_task_cancellation(
                    request_id=response.request_id,
                    status="completed",
                    reason="performers_answered",
                    now=now,
                )
            assignments = await uow.list_task_assignments(task.id, for_update=True)
            if not _active_slot_assignments(_latest_slot_assignments(assignments)):
                task = await uow.save_task_status(task_id=task.id, status=TaskStatus.CANCELLED)
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
                    reason="performer_consent",
                )
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="task_assignment_cancelled_by_consent",
                entity_type="task",
                entity_id=str(task.id),
                reason="performer_consent",
            )
            await _finish_receipt(
                uow,
                update_id,
                actor,
                (
                    f"task_cancelled:{task.id}:{response.request_id}"
                    if task.status is TaskStatus.CANCELLED
                    else f"task_cancel_pending:{task.id}:{response.request_id}"
                ),
            )
            return TaskCancellationOutcome(
                task,
                response.request_id,
                "cancelled" if task.status is TaskStatus.CANCELLED else "pending",
            )

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
    statuses: dict[str, TaskCancellationStatus] = {
        "task_cancelled:": "cancelled",
        "task_closed:": "closed",
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


async def _active_context_actor(uow: TaskUnitOfWork, context: ActorContext | UUID) -> Member:
    actor = await uow.get_member(context if isinstance(context, UUID) else context.member_id)
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


def _advance_freeform_draft(draft: TaskDraft, value: object) -> TaskDraft:
    editing_complete_draft = _has_complete_freeform_values(draft)
    changes: dict[str, object]
    if draft.current_step is TaskDraftStep.TASK_KIND:
        kind = validate_task_kind(value)
        changes = {
            "task_kind": kind,
            "performer_slots": 1 if kind is TaskKind.SOLO else max(2, draft.performer_slots or 2),
            "current_step": (
                TaskDraftStep.SLOTS
                if editing_complete_draft
                and draft.task_kind is TaskKind.SOLO
                and kind is TaskKind.GROUP
                else TaskDraftStep.PREVIEW
                if editing_complete_draft
                else TaskDraftStep.CATEGORY
            ),
        }
    elif draft.current_step is TaskDraftStep.CATEGORY:
        if not isinstance(value, UUID):
            raise TaskError("Task category is invalid.")
        changes = {
            "category_id": value,
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.TIME_SIZE
            ),
        }
    elif draft.current_step is TaskDraftStep.TIME_SIZE:
        size = validate_time_size(value)
        changes = {
            "time_size": size,
            "estimated_minutes": TASK_TIME_SIZE_SPECS[size].estimated_minutes,
            "credit_reward_per_performer": (
                draft.credit_reward_per_performer if editing_complete_draft else None
            ),
            "current_step": (
                TaskDraftStep.REWARD
                if editing_complete_draft
                else TaskDraftStep.SLOTS
                if draft.task_kind is TaskKind.GROUP
                else TaskDraftStep.REWARD
            ),
        }
    elif draft.current_step is TaskDraftStep.SLOTS:
        if draft.task_kind is None:
            raise TaskError("Task kind is missing.")
        if not isinstance(value, int):
            raise TaskError("Task performer slots must be an integer.")
        changes = {
            "performer_slots": validate_freeform_slots(value, kind=draft.task_kind),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.REWARD
            ),
        }
    elif draft.current_step is TaskDraftStep.REWARD:
        if draft.time_size is None or not isinstance(value, int):
            raise TaskError("Task reward cannot be selected before size.")
        changes = {
            "credit_reward_per_performer": validate_freeform_reward(draft.time_size, value),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.TITLE
            ),
        }
    elif draft.current_step is TaskDraftStep.TITLE:
        changes = {
            "title": validate_freeform_text(value, field="title"),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.DESCRIPTION
            ),
        }
    elif draft.current_step is TaskDraftStep.DESCRIPTION:
        changes = {
            "description": validate_freeform_text(value, field="description"),
            "current_step": (
                TaskDraftStep.PREVIEW
                if editing_complete_draft
                else TaskDraftStep.COMPLETION_CRITERIA
            ),
        }
    elif draft.current_step is TaskDraftStep.COMPLETION_CRITERIA:
        changes = {
            "completion_criteria": validate_freeform_text(
                value,
                field="completion_criteria",
            ),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.MATERIALS
            ),
        }
    elif draft.current_step is TaskDraftStep.MATERIALS:
        if not isinstance(value, Mapping):
            raise TaskError("Task materials must be an object.")
        changes = {
            "materials": validate_freeform_materials(value),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.DEADLINE
            ),
        }
    elif draft.current_step is TaskDraftStep.DEADLINE:
        if not isinstance(value, datetime.datetime):
            raise TaskError("Task deadline must be a datetime.")
        changes = {
            "deadline_at": validate_deadline(value, now=_utc_now()),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.FORMAT
            ),
        }
    elif draft.current_step is TaskDraftStep.FORMAT:
        if not isinstance(value, tuple) or len(value) != _FORMAT_VALUE_SIZE:
            raise TaskError("Task format value must include format and city.")
        task_format, city = value
        if not isinstance(task_format, TaskFormat) or not (isinstance(city, str) or city is None):
            raise TaskError("Task format value is invalid.")
        selected, normalized_city = validate_task_format(
            task_format,
            template_format=TaskFormat.ANY,
            city=city,
        )
        changes = {
            "format": selected,
            "city": normalized_city,
            "current_step": TaskDraftStep.PREVIEW,
        }
    else:
        raise TaskError("Task draft cannot advance from its current step.")
    changes["revision"] = draft.revision + 1
    return _replace_draft(draft, **changes)


def _advance_draft(draft: TaskDraft, template: CatalogTemplate, value: object) -> TaskDraft:
    editing_complete_draft = _has_complete_template_values(draft)
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
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.DEADLINE
            ),
        }
    elif draft.current_step is TaskDraftStep.DEADLINE:
        if not isinstance(value, datetime.datetime):
            raise TaskError("Task deadline must be a datetime.")
        changes = {
            "deadline_at": validate_deadline(value, now=_utc_now()),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.FORMAT
            ),
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
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.MATERIALS
            ),
        }
    elif draft.current_step is TaskDraftStep.MATERIALS:
        if not isinstance(value, Mapping):
            raise TaskError("Task materials must be an object.")
        changes = {
            "materials": validate_materials(value),
            "current_step": (
                TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.SLOTS
            ),
        }
    elif draft.current_step is TaskDraftStep.SLOTS:
        if value is None:
            if draft.performer_slots is None:
                raise TaskError("Task performer slots are missing.")
            changes = {"current_step": TaskDraftStep.PREVIEW}
        else:
            if not isinstance(value, int) or isinstance(value, bool):
                raise TaskError("Task performer slots must be an integer.")
            changes = {
                "performer_slots": validate_slots(value, maximum=template.maximum_performers),
                "current_step": (
                    TaskDraftStep.PREVIEW if editing_complete_draft else TaskDraftStep.SLOTS
                ),
            }
    else:
        raise TaskError("Task draft cannot advance from its current step.")
    changes["revision"] = draft.revision + 1
    return _replace_draft(draft, **changes)


def _has_complete_freeform_values(draft: TaskDraft) -> bool:
    return (
        draft.template_id is None
        and draft.task_kind is not None
        and draft.category_id is not None
        and draft.time_size is not None
        and draft.credit_reward_per_performer is not None
        and draft.title is not None
        and draft.description is not None
        and draft.completion_criteria is not None
        and draft.materials is not None
        and draft.performer_slots is not None
        and draft.deadline_at is not None
        and draft.format is not None
    )


def _has_complete_template_values(draft: TaskDraft) -> bool:
    return (
        draft.template_id is not None
        and draft.input_payload is not None
        and draft.materials is not None
        and draft.performer_slots is not None
        and draft.deadline_at is not None
        and draft.format is not None
    )


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


def _validate_freeform_publishable(
    draft: TaskDraft,
    category: TaskCategoryOption | None,
) -> None:
    if draft.template_id is not None:
        raise TaskError("Free-form validation received a template draft.")
    if category is None:
        raise TaskError("Task category is unavailable.")
    if draft.origin == "community" and category.code != _COMMUNITY_CATEGORY_CODE:
        raise TaskError("Community task must use the community development category.")
    if draft.origin == "member" and category.code == _COMMUNITY_CATEGORY_CODE:
        raise TaskError("Community development tasks must be published by the community.")
    if draft.task_kind is None or draft.time_size is None:
        raise TaskError("Task draft is incomplete.")
    if (
        draft.title is None
        or draft.description is None
        or draft.completion_criteria is None
        or draft.credit_reward_per_performer is None
        or draft.estimated_minutes is None
        or draft.materials is None
        or draft.performer_slots is None
        or draft.deadline_at is None
        or draft.format is None
    ):
        raise TaskError("Task draft is incomplete.")
    validate_freeform_slots(draft.performer_slots, kind=draft.task_kind)
    validate_freeform_reward(draft.time_size, draft.credit_reward_per_performer)
    if (
        draft.origin == "community"
        and draft.credit_reward_per_performer > _COMMUNITY_TASK_MAX_REWARD
    ):
        raise TaskError("Community task reward cannot exceed 10 credits.")
    validate_freeform_text(draft.title, field="title")
    validate_freeform_text(draft.description, field="description")
    validate_freeform_text(draft.completion_criteria, field="completion_criteria")
    validate_freeform_materials(draft.materials)
    validate_deadline(draft.deadline_at, now=_utc_now())
    validate_task_format(draft.format, template_format=TaskFormat.ANY, city=draft.city)


async def _freeform_preview(
    uow: TaskUnitOfWork, draft: TaskDraft, category: TaskCategoryOption | None
) -> TaskPreview:
    _validate_freeform_publishable(draft, category)
    return TaskPreview(
        draft,
        (
            "Сообщество"
            if draft.origin == "community"
            else await uow.member_display_name(draft.creator_id)
        ),
        category.name if category else None,
        category.icon if category else None,
        draft.task_kind,
        draft.time_size,
        cast("str", draft.title),
        cast("str", draft.description),
        "Следуйте описанию задания и критериям результата.",
        ("description",),
        cast("str", draft.completion_criteria),
        cast("int", draft.credit_reward_per_performer),
        (
            0
            if draft.origin == "community"
            else cast("int", draft.credit_reward_per_performer) * cast("int", draft.performer_slots)
        ),
    )


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


def _categories_for_actor(
    categories: tuple[TaskCategoryOption, ...], actor: Member
) -> tuple[TaskCategoryOption, ...]:
    """Hide the community category unless the actor may publish as the community."""
    if can_create_community_task(actor):
        return categories
    return tuple(item for item in categories if item.code != _COMMUNITY_CATEGORY_CODE)


def _category_for_actor(
    category: TaskCategoryOption | None, actor: Member
) -> TaskCategoryOption | None:
    if (
        category is not None
        and category.code == _COMMUNITY_CATEGORY_CODE
        and not can_create_community_task(actor)
    ):
        return None
    return category


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


async def _publish_locked_draft(  # noqa: PLR0913
    *,
    uow: TaskUnitOfWork,
    update_id: int,
    actor: Member,
    draft: TaskDraft,
    template: CatalogTemplate | None,
    web_fingerprint: str | None = None,
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
    if web_fingerprint is None:
        await uow.clear_text_flow(
            member_id=draft.creator_id, flow_type="task", reference_id=draft.id
        )
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
    await _finish_receipt(
        uow, update_id, actor, _web_task_outcome(task.id, draft.id, web_fingerprint)
    )
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


async def _web_draft_replay(
    uow: TaskUnitOfWork, outcome: str, actor_id: UUID, fingerprint: str
) -> TaskDraft:
    marker, raw_id, stored = outcome.split(":", 2)
    if marker != "web_task_draft" or stored != fingerprint:
        raise TaskError("Stored task draft outcome does not match command.")
    draft = await uow.get_task_draft(UUID(raw_id))
    if draft is None or draft.creator_id != actor_id:
        raise PermissionError("Task draft is unavailable.")
    await uow.ensure_task_test_access(draft_id=draft.id, member_id=actor_id)
    return draft


async def _web_publication_replay(
    uow: TaskUnitOfWork, outcome: str, actor_id: UUID, draft_id: UUID, fingerprint: str
) -> PublishedTask:
    marker, raw_task, raw_draft, stored = outcome.split(":", 3)
    if marker != "web_task" or raw_draft != str(draft_id) or stored != fingerprint:
        raise TaskError("Stored task publication outcome does not match command.")
    task = await uow.get_task(UUID(raw_task))
    if task is None or task.creator_id != actor_id:
        raise PermissionError("Task publication is unavailable.")
    await uow.ensure_task_test_access(task_id=task.id, member_id=actor_id)
    return task


def _web_task_outcome(task_id: UUID, draft_id: UUID, fingerprint: str | None) -> str:
    return (
        f"task:{task_id}" if fingerprint is None else f"web_task:{task_id}:{draft_id}:{fingerprint}"
    )


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


def _latest_slot_assignments(assignments: Sequence[Assignment]) -> tuple[Assignment, ...]:
    latest_by_slot: dict[int, Assignment] = {}
    for assignment in assignments:
        latest_by_slot[assignment.slot_number] = assignment
    return tuple(latest_by_slot.values())


def _active_slot_assignments(assignments: Sequence[Assignment]) -> tuple[Assignment, ...]:
    active = {
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.SUBMITTED,
        AssignmentStatus.REJECTED_PENDING_DISPUTE,
        AssignmentStatus.DISPUTED,
        AssignmentStatus.REVIEWER_REQUIRED,
    }
    return tuple(item for item in assignments if item.status in active)
