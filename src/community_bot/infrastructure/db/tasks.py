"""PostgreSQL persistence for task drafts, publication, and outbox."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, exists, func, or_, select, text, tuple_, update

from community_bot.application.tasks import PublishedTask, TaskDraft
from community_bot.domain.assignments import AssignmentStatus
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import TaskDraftStep, TaskError, TaskStatus
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    MemberModel,
    OutboxEventModel,
    TaskCreationDraftModel,
    TaskModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from community_bot.application.catalog import CatalogTemplate

_TASK_IDENTITY_GATE = "task_creation_identity"
_TASK_COMMAND_GATE = "task_workflow_command"


async def acquire_task_identity_gate(session: AsyncSession, telegram_user_id: int) -> None:
    """Serialize task draft mutations for one Telegram identity."""
    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:identity, hashtextextended(:gate, 0)))"
        ),
        {"gate": _TASK_IDENTITY_GATE, "identity": str(telegram_user_id)},
    )


async def acquire_task_command_gate(session: AsyncSession, command_id: uuid.UUID) -> None:
    """Serialize one publish or cancel business command."""
    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:identity, hashtextextended(:gate, 0)))"
        ),
        {"gate": _TASK_COMMAND_GATE, "identity": str(command_id)},
    )


async def create_task_draft(
    session: AsyncSession,
    *,
    creator_id: uuid.UUID,
    template_id: uuid.UUID,
    origin: str = "member",
) -> TaskDraft:
    """Create a new current draft while preserving previous drafts."""
    await session.execute(
        update(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.creator_id == creator_id)
        .where(TaskCreationDraftModel.is_current.is_(True))
        .values(is_current=False)
    )
    model = TaskCreationDraftModel(
        creator_id=creator_id,
        template_id=template_id,
        origin=origin,
        current_step=TaskDraftStep.INPUT.value,
        revision=0,
        is_current=True,
        publish_command_id=uuid.uuid4(),
    )
    session.add(model)
    await session.flush()
    return _draft(model)


async def get_current_task_draft(session: AsyncSession, creator_id: uuid.UUID) -> TaskDraft | None:
    """Return the one selected unfinished draft."""
    model = await session.scalar(
        select(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.creator_id == creator_id)
        .where(TaskCreationDraftModel.is_current.is_(True))
        .where(TaskCreationDraftModel.current_step != TaskDraftStep.PUBLISHED.value)
    )
    return None if model is None else _draft(model)


async def get_task_draft(session: AsyncSession, draft_id: uuid.UUID) -> TaskDraft | None:
    """Read one task draft without locking."""
    model = await session.get(TaskCreationDraftModel, draft_id)
    return None if model is None else _draft(model)


async def lock_task_draft(session: AsyncSession, draft_id: uuid.UUID) -> TaskDraft | None:
    """Lock one task draft for a caller-owned mutation."""
    model = await session.scalar(
        select(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.id == draft_id)
        .with_for_update()
    )
    return None if model is None else _draft(model)


async def select_task_draft(
    session: AsyncSession, *, creator_id: uuid.UUID, draft_id: uuid.UUID
) -> TaskDraft:
    """Select one owned nonterminal draft as current."""
    target = await session.scalar(
        select(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.id == draft_id)
        .with_for_update()
    )
    if target is None or target.creator_id != creator_id:
        raise PermissionError("Task draft is not owned by this member.")
    if target.current_step == TaskDraftStep.PUBLISHED.value:
        raise TaskError("Published task draft cannot be resumed.")
    await session.execute(
        update(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.creator_id == creator_id)
        .where(TaskCreationDraftModel.is_current.is_(True))
        .values(is_current=False)
    )
    target.is_current = True
    await session.flush()
    return _draft(target)


async def save_task_draft(session: AsyncSession, draft: TaskDraft) -> TaskDraft:
    """Persist one already locked validated draft snapshot."""
    model = await session.get(TaskCreationDraftModel, draft.id)
    if model is None:
        raise LookupError("Task draft does not exist.")
    model.input_payload_json = draft.input_payload
    model.origin = draft.origin
    model.reviewer_admin_id = draft.reviewer_admin_id
    model.deadline_at = draft.deadline_at
    model.format = None if draft.format is None else draft.format.value
    model.city = draft.city
    model.materials_json = draft.materials
    model.performer_slots = draft.performer_slots
    model.current_step = draft.current_step.value
    model.revision = draft.revision
    model.is_current = draft.is_current
    await session.flush()
    return _draft(model)


async def delete_task_draft(session: AsyncSession, draft_id: uuid.UUID) -> None:
    """Delete one unfinished creation draft."""
    await session.execute(
        delete(TaskCreationDraftModel)
        .where(TaskCreationDraftModel.id == draft_id)
        .where(TaskCreationDraftModel.current_step != TaskDraftStep.PUBLISHED.value)
    )
    await session.flush()


async def task_by_publish_command(
    session: AsyncSession, command_id: uuid.UUID
) -> PublishedTask | None:
    """Read the unique task produced by one draft command."""
    model = await session.scalar(
        select(TaskModel).where(TaskModel.publish_command_id == command_id)
    )
    return None if model is None else _task(model)


async def insert_published_task(
    session: AsyncSession,
    *,
    draft: TaskDraft,
    template: CatalogTemplate,
) -> PublishedTask:
    """Insert one immutable member-origin task snapshot."""
    if (
        draft.input_payload is None
        or draft.materials is None
        or draft.deadline_at is None
        or draft.format is None
        or draft.performer_slots is None
    ):
        raise TaskError("Task draft is incomplete.")
    creator = await session.get(MemberModel, draft.creator_id)
    if creator is None:
        raise LookupError("Task creator does not exist.")
    community = draft.origin == "community"
    schema_properties = template.input_schema.get("properties")
    public_input_keys = list(schema_properties) if isinstance(schema_properties, dict) else []
    model = TaskModel(
        origin=draft.origin,
        template_id=template.id,
        template_version=template.version,
        creator_id=None if community else draft.creator_id,
        created_by_admin_id=draft.creator_id if community else None,
        reviewer_admin_id=draft.reviewer_admin_id if community else None,
        author_display_name="Сообщество" if community else creator.display_name,
        category_id=template.category_id,
        title=template.name,
        description=template.description,
        completion_criteria=template.completion_criteria,
        materials_json=draft.materials,
        input_payload_json=draft.input_payload,
        credit_reward_per_performer=template.credit_reward,
        performer_slots=draft.performer_slots,
        reserved_credit_total=0 if community else template.credit_reward * draft.performer_slots,
        estimated_minutes=template.estimated_minutes,
        minimum_level=template.minimum_level,
        format=draft.format.value,
        city=draft.city,
        deadline_at=draft.deadline_at,
        status=TaskStatus.PUBLISHED.value,
        safety_snapshot_json={
            "creator_instructions": template.creator_instructions,
            "performer_instructions": template.performer_instructions,
            "public_input_keys": public_input_keys,
            "moderation_required": template.moderation_required,
        },
        publish_command_id=draft.publish_command_id,
    )
    session.add(model)
    await session.flush()
    return _task(model)


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> PublishedTask | None:
    """Read one published task."""
    model = await session.get(TaskModel, task_id)
    return None if model is None else _task(model)


async def member_display_name(session: AsyncSession, member_id: uuid.UUID) -> str:
    """Return the immutable preview author label from the current profile."""
    value = await session.scalar(
        select(MemberModel.display_name).where(MemberModel.id == member_id)
    )
    if value is None:
        raise LookupError("Task creator does not exist.")
    return value


async def lock_task(session: AsyncSession, task_id: uuid.UUID) -> PublishedTask | None:
    """Lock one published task for cancellation or future assignment."""
    model = await session.scalar(select(TaskModel).where(TaskModel.id == task_id).with_for_update())
    return None if model is None else _task(model)


async def save_task_status(
    session: AsyncSession, *, task_id: uuid.UUID, status: TaskStatus
) -> PublishedTask:
    """Persist a creation-owned task status transition."""
    model = await session.get(TaskModel, task_id)
    if model is None:
        raise LookupError("Task does not exist.")
    model.status = status.value
    model.cancelled_at = (
        datetime.datetime.now(datetime.UTC) if status is TaskStatus.CANCELLED else None
    )
    await session.flush()
    return _task(model)


async def save_community_reviewer(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    now: datetime.datetime,
) -> PublishedTask:
    """Replace a community reviewer and reopen only assignments waiting for one."""
    model = await session.get(TaskModel, task_id)
    if model is None:
        raise LookupError("Task does not exist.")
    model.reviewer_admin_id = reviewer_id
    await session.execute(
        update(AssignmentModel)
        .where(
            AssignmentModel.task_id == task_id,
            AssignmentModel.status == "reviewer_required",
        )
        .values(status="submitted", review_deadline_at=now + datetime.timedelta(hours=72))
    )
    await session.flush()
    return _task(model)


async def list_owned_tasks(  # noqa: PLR0913 - explicit keyset fields keep the query typed.
    session: AsyncSession,
    *,
    creator_id: uuid.UUID,
    limit: int,
    status: TaskStatus | None,
    before_created_at: datetime.datetime | None,
    before_id: uuid.UUID | None,
) -> tuple[PublishedTask, ...]:
    """Return the latest owned tasks without exposing other creators."""
    statement = select(TaskModel).where(
        or_(
            TaskModel.creator_id == creator_id,
            TaskModel.created_by_admin_id == creator_id,
            TaskModel.reviewer_admin_id == creator_id,
        )
    )
    if status is not None:
        statement = statement.where(TaskModel.status == status.value)
    if before_created_at is not None and before_id is not None:
        statement = statement.where(
            tuple_(TaskModel.created_at, TaskModel.id) < (before_created_at, before_id)
        )
    models = (
        await session.scalars(
            statement.order_by(TaskModel.created_at.desc(), TaskModel.id.desc()).limit(limit)
        )
    ).all()
    return tuple(_task(model) for model in models)


async def list_available_tasks(  # noqa: PLR0913 - explicit discovery policy inputs.
    session: AsyncSession,
    *,
    performer_id: uuid.UUID,
    level: int,
    limit: int,
    cursor_task_id: uuid.UUID | None,
    now: datetime.datetime,
) -> tuple[PublishedTask, ...]:
    """Return discoverable tasks while leaving final authorization to acceptance."""
    occupied = (
        select(func.count(AssignmentModel.id))
        .where(
            AssignmentModel.task_id == TaskModel.id,
            AssignmentModel.status != AssignmentStatus.CANCELLED.value,
        )
        .correlate(TaskModel)
        .scalar_subquery()
    )
    already_assigned = exists().where(
        AssignmentModel.task_id == TaskModel.id,
        AssignmentModel.performer_id == performer_id,
        AssignmentModel.status != AssignmentStatus.CANCELLED.value,
    )
    availability = (
        TaskModel.status == TaskStatus.PUBLISHED.value,
        TaskModel.deadline_at > now,
        TaskModel.minimum_level <= level,
        (TaskModel.creator_id.is_(None) | (TaskModel.creator_id != performer_id)),
        occupied < TaskModel.performer_slots,
        ~already_assigned,
    )
    statement = select(TaskModel).where(*availability)
    if cursor_task_id is not None:
        cursor = await session.scalar(
            select(TaskModel).where(TaskModel.id == cursor_task_id, *availability)
        )
        if cursor is not None:
            statement = statement.where(
                tuple_(TaskModel.created_at, TaskModel.id) < (cursor.created_at, cursor.id)
            )
    models = (
        await session.scalars(
            statement.order_by(TaskModel.created_at.desc(), TaskModel.id.desc()).limit(limit)
        )
    ).all()
    return tuple(_task(model) for model in models)


async def add_task_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    task: PublishedTask,
    business_key: str,
) -> None:
    """Stage a privacy-minimal task lifecycle outbox event."""
    session.add(
        OutboxEventModel(
            event_type=event_type,
            aggregate_type="task",
            aggregate_id=task.id,
            payload_json={
                "task_id": str(task.id),
                "creator_id": str(task.creator_id),
                "status": task.status.value,
            },
            business_key=business_key,
        )
    )


def _draft(model: TaskCreationDraftModel) -> TaskDraft:
    return TaskDraft(
        id=model.id,
        creator_id=model.creator_id,
        origin=model.origin,
        reviewer_admin_id=model.reviewer_admin_id,
        template_id=model.template_id,
        input_payload=None if model.input_payload_json is None else dict(model.input_payload_json),
        deadline_at=model.deadline_at,
        format=None if model.format is None else TaskFormat(model.format),
        city=model.city,
        materials=None if model.materials_json is None else dict(model.materials_json),
        performer_slots=model.performer_slots,
        current_step=TaskDraftStep(model.current_step),
        revision=model.revision,
        is_current=model.is_current,
        publish_command_id=model.publish_command_id,
    )


def _task(model: TaskModel) -> PublishedTask:
    stored_public_keys = model.safety_snapshot_json.get("public_input_keys")
    public_input_keys = (
        tuple(str(key) for key in stored_public_keys)
        if isinstance(stored_public_keys, list)
        else tuple(str(key) for key in model.input_payload_json)
    )
    return PublishedTask(
        id=model.id,
        creator_id=model.creator_id,
        created_by_admin_id=model.created_by_admin_id,
        reviewer_admin_id=model.reviewer_admin_id,
        origin=model.origin,
        author_display_name=model.author_display_name,
        template_id=model.template_id,
        template_version=model.template_version,
        title=model.title,
        description=model.description,
        performer_instructions=str(
            model.safety_snapshot_json.get(
                "performer_instructions",
                "Следуйте описанию задания и критериям результата.",
            )
        ),
        public_input_keys=public_input_keys,
        completion_criteria=model.completion_criteria,
        input_payload=dict(model.input_payload_json),
        materials=dict(model.materials_json),
        credit_reward_per_performer=model.credit_reward_per_performer,
        performer_slots=model.performer_slots,
        reserved_credit_total=model.reserved_credit_total,
        minimum_level=model.minimum_level,
        format=TaskFormat(model.format),
        city=model.city,
        deadline_at=model.deadline_at,
        status=TaskStatus(model.status),
        publish_command_id=model.publish_command_id,
        created_at=model.created_at,
    )


def published_task_from_model(model: TaskModel) -> PublishedTask:
    """Map a joined task row for assignment projections."""
    return _task(model)
