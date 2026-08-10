"""Application workflows for persistent task creation and reservation."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from community_bot.domain.catalog import TaskFormat, validate_payload
from community_bot.domain.economy import ResolvedLevel, refund_reward, reserve_reward
from community_bot.domain.members import Member, MemberStatus
from community_bot.domain.tasks import (
    AcceptanceTaskSnapshot,
    StaleTaskDraftError,
    TaskDraftStep,
    TaskError,
    TaskStatus,
    validate_acceptance_actor,
    validate_deadline,
    validate_materials,
    validate_slots,
    validate_task_format,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from community_bot.application.catalog import CatalogTemplate
    from community_bot.application.economy import EconomyMutationPort

_MAX_OWNED_TASKS = 20
_FORMAT_VALUE_SIZE = 2


@dataclass(frozen=True, slots=True)
class TaskDraft:
    """Persistent resumable task creation draft."""

    id: UUID
    creator_id: UUID
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


@dataclass(frozen=True, slots=True)
class TaskPreview:
    """Read-only publication preview with the exact reserve amount."""

    draft: TaskDraft
    template_name: str
    credit_reward_per_performer: int
    reserved_credit_total: int


@dataclass(frozen=True, slots=True)
class PublishedTask:
    """Immutable public task snapshot plus creation-owned lifecycle state."""

    id: UUID
    creator_id: UUID
    template_id: UUID
    template_version: int
    title: str
    description: str
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

    def acceptance_snapshot(self) -> AcceptanceTaskSnapshot:
        """Return the transport-neutral static acceptance input."""
        return AcceptanceTaskSnapshot(self.creator_id, self.status, self.minimum_level)


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


class TaskUnitOfWork(Protocol):
    """Caller-owned transaction contract for task workflows."""

    @property
    def economy(self) -> EconomyMutationPort: ...
    async def acquire_update_gate(self, update_id: int) -> None: ...
    async def get_receipt_outcome(self, update_id: int) -> str | None: ...
    async def acquire_task_identity_gate(self, telegram_user_id: int) -> None: ...
    async def acquire_task_command_gate(self, command_id: UUID) -> None: ...
    async def acquire_catalog_mutation_gate(self) -> None: ...
    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...
    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]: ...
    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel: ...
    async def template_for_creation(
        self, *, template_id: UUID, level: int
    ) -> CatalogTemplate | None: ...
    async def catalog_template(self, template_id: UUID) -> CatalogTemplate | None: ...
    async def create_task_draft(self, *, creator_id: UUID, template_id: UUID) -> TaskDraft: ...
    async def get_current_task_draft(self, creator_id: UUID) -> TaskDraft | None: ...
    async def get_task_draft(self, draft_id: UUID) -> TaskDraft | None: ...
    async def lock_task_draft(self, draft_id: UUID) -> TaskDraft | None: ...
    async def select_task_draft(self, *, creator_id: UUID, draft_id: UUID) -> TaskDraft: ...
    async def save_task_draft(self, draft: TaskDraft) -> TaskDraft: ...
    async def delete_task_draft(self, draft_id: UUID) -> None: ...
    async def task_by_publish_command(self, command_id: UUID) -> PublishedTask | None: ...
    async def insert_published_task(
        self, *, draft: TaskDraft, template: CatalogTemplate
    ) -> PublishedTask: ...
    async def get_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def lock_task(self, task_id: UUID) -> PublishedTask | None: ...
    async def save_task_status(self, *, task_id: UUID, status: TaskStatus) -> PublishedTask: ...
    async def list_owned_tasks(
        self,
        *,
        creator_id: UUID,
        limit: int,
        status: TaskStatus | None,
        before_created_at: datetime.datetime | None,
        before_id: UUID | None,
    ) -> tuple[PublishedTask, ...]: ...
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


class TaskUnitOfWorkFactory(Protocol):
    """Create isolated task transactions."""

    def __call__(self) -> AbstractAsyncContextManager[TaskUnitOfWork]: ...


class TaskService:
    """Coordinate persistent drafts, publication, ownership, and cancellation."""

    def __init__(self, unit_of_work_factory: TaskUnitOfWorkFactory) -> None:
        """Configure the shared caller-owned transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def start(
        self, *, update_id: int, actor_telegram_user_id: int, template_id: UUID | None
    ) -> TaskDraft | None:
        """Create a new current draft or resume the existing current draft."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, update_id)
            if replay is not None:
                return await _draft_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(actor_telegram_user_id)
            actor = await _active_actor(uow, actor_telegram_user_id)
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
                draft = await uow.create_task_draft(creator_id=actor.id, template_id=template.id)
                outcome = f"task_draft:{draft.id}"
            await _finish(uow, update_id, actor, outcome, "task_draft")
            return draft

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
                template.name,
                template.credit_reward,
                template.credit_reward * draft.performer_slots,
            )

    async def publish(self, command: PublishTaskCommand) -> PublishedTask:
        """Atomically reserve credits and publish one exact preview revision."""
        async with self._unit_of_work_factory() as uow:
            replay = await _begin_update(uow, command.update_id)
            if replay is not None:
                return await _task_from_outcome(uow, replay)
            await uow.acquire_task_identity_gate(command.actor_telegram_user_id)
            preliminary = await uow.get_task_draft(command.draft_id)
            if preliminary is None:
                raise TaskError("Task draft does not exist.")
            await uow.acquire_task_command_gate(preliminary.publish_command_id)
            await uow.acquire_catalog_mutation_gate()
            template_before = await uow.catalog_template(preliminary.template_id)
            if template_before is None or preliminary.performer_slots is None:
                raise TaskError("Task draft is incomplete.")
            reserve_total = template_before.credit_reward * preliminary.performer_slots
            prepared = await uow.economy.prepare_batch(
                (
                    reserve_reward(
                        member_id=preliminary.creator_id,
                        amount=reserve_total,
                        idempotency_key=(f"task_publish:{preliminary.publish_command_id}:reserve"),
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
                    or draft.revision != command.expected_revision + 1
                ):
                    raise StaleTaskDraftError("Task publication identity is conflicting.")
                await prepared.apply()
                await _finish_receipt(uow, command.update_id, actor, f"task:{existing.id}")
                return existing
            _expect(draft, TaskDraftStep.PREVIEW, command.expected_revision)
            level = await uow.resolve_member_level(actor.id)
            template = await uow.template_for_creation(
                template_id=draft.template_id, level=level.level_number
            )
            if template is None:
                raise PermissionError("Task template is no longer publishable.")
            _validate_publishable(draft, template)
            if template.credit_reward * (draft.performer_slots or 0) != reserve_total:
                raise TaskError("Task reserve changed after preview.")
            await prepared.apply()
            task = await uow.insert_published_task(draft=draft, template=template)
            await uow.save_task_draft(
                _replace_draft(
                    draft,
                    current_step=TaskDraftStep.PUBLISHED,
                    is_current=False,
                    revision=draft.revision + 1,
                )
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
            await _finish_receipt(uow, command.update_id, actor, f"task:{task.id}")
            return task

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
            await uow.acquire_task_command_gate(task_id)
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
            task = await uow.lock_task(task_id)
            if task is None:
                raise TaskError("Task does not exist.")
            if task.status is TaskStatus.CANCELLED:
                raise TaskError("Task is already cancelled.")
            if task.status is not TaskStatus.PUBLISHED:
                raise TaskError("Task cannot be cancelled from its current state.")
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


async def _active_actor(uow: TaskUnitOfWork, telegram_user_id: int) -> Member:
    actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None:
        raise PermissionError("Task actor is not a registered member.")
    _require_active(actor)
    return actor


def _require_active(actor: Member) -> None:
    if actor.status is not MemberStatus.ACTIVE:
        raise PermissionError("Task workflow requires an active member.")


def _expect(draft: TaskDraft, step: TaskDraftStep, revision: int) -> None:
    if draft.current_step is not step or draft.revision != revision:
        raise StaleTaskDraftError("Task draft step or revision is stale.")


def _advance_draft(draft: TaskDraft, template: CatalogTemplate, value: object) -> TaskDraft:
    changes: dict[str, object]
    if draft.current_step is TaskDraftStep.INPUT:
        if not isinstance(value, Mapping):
            raise TaskError("Task input must be an object.")
        changes = {
            "input_payload": validate_payload(template.input_schema, value),
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
    validate_deadline(draft.deadline_at, now=_utc_now())
    validate_task_format(draft.format, template_format=template.format, city=draft.city)
    validate_slots(draft.performer_slots, maximum=template.maximum_performers)


def _replace_draft(draft: TaskDraft, **changes: object) -> TaskDraft:
    values = {field: getattr(draft, field) for field in draft.__dataclass_fields__}
    values.update(changes)
    return TaskDraft(**values)


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


async def _task_from_outcome(uow: TaskUnitOfWork, outcome: str) -> PublishedTask:
    if not outcome.startswith("task:"):
        raise TaskError("Telegram update was already used by another operation.")
    task = await uow.get_task(UUID(outcome.split(":", 1)[1]))
    if task is None:
        raise TaskError("Stored task outcome no longer exists.")
    return task


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
