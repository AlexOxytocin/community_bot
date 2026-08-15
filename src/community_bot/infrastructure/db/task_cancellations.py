"""PostgreSQL persistence for compact owned cards and negotiated cancellation."""

# ruff: noqa: D103, EM101, PLR0913, TRY003

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import exists, or_, select, tuple_, update

from community_bot.application.tasks import (
    OwnedTaskAssignee,
    OwnedTaskCard,
    TaskCancellationResponse,
)
from community_bot.infrastructure.db.assignments import append_reliability
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    MemberModel,
    OutboxEventModel,
    TaskCancellationRequestModel,
    TaskCancellationResponseModel,
    TaskModel,
)
from community_bot.infrastructure.db.tasks import published_task_from_model
from community_bot.infrastructure.db.test_runs import active_scope

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from community_bot.domain.assignments import Assignment
    from community_bot.domain.tasks import TaskStatus


async def list_owned_task_cards(
    session: AsyncSession,
    *,
    creator_id: uuid.UUID,
    limit: int,
    status: TaskStatus | None,
    before_created_at: datetime.datetime | None,
    before_id: uuid.UUID | None,
) -> tuple[OwnedTaskCard, ...]:
    """Return tasks with active assignee labels and the pending request state."""
    scope = await active_scope(session, creator_id)
    test_scope = (
        TaskModel.test_run_id.is_(None) if scope is None else TaskModel.test_run_id == scope.id
    )
    statement = select(TaskModel).where(
        or_(
            TaskModel.creator_id == creator_id,
            TaskModel.created_by_admin_id == creator_id,
            TaskModel.reviewer_admin_id == creator_id,
            TaskModel.community_approved_by_admin_id == creator_id,
        ),
        test_scope,
    )
    if status is not None:
        statement = statement.where(TaskModel.status == status.value)
    if before_created_at is not None and before_id is not None:
        statement = statement.where(
            tuple_(TaskModel.created_at, TaskModel.id) < (before_created_at, before_id)
        )
    tasks = (
        await session.scalars(
            statement.order_by(TaskModel.created_at.desc(), TaskModel.id.desc()).limit(limit)
        )
    ).all()
    return await _owned_task_cards(session, tasks)


async def get_owned_task_card(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> OwnedTaskCard | None:
    """Return one task visible to its member owner or community administrator."""
    scope = await active_scope(session, owner_id)
    test_scope = (
        TaskModel.test_run_id.is_(None) if scope is None else TaskModel.test_run_id == scope.id
    )
    task = await session.scalar(
        select(TaskModel).where(
            TaskModel.id == task_id,
            test_scope,
            or_(
                TaskModel.creator_id == owner_id,
                TaskModel.created_by_admin_id == owner_id,
                TaskModel.reviewer_admin_id == owner_id,
                TaskModel.community_approved_by_admin_id == owner_id,
            ),
        )
    )
    if task is None:
        return None
    return (await _owned_task_cards(session, (task,)))[0]


async def _owned_task_cards(
    session: AsyncSession, tasks: Sequence[TaskModel]
) -> tuple[OwnedTaskCard, ...]:
    if not tasks:
        return ()
    task_ids = [task.id for task in tasks]
    assignment_rows = (
        await session.execute(
            select(AssignmentModel, MemberModel.display_name)
            .join(MemberModel, MemberModel.id == AssignmentModel.performer_id)
            .where(
                AssignmentModel.task_id.in_(task_ids),
                AssignmentModel.status != "cancelled",
            )
            .order_by(AssignmentModel.slot_number, AssignmentModel.accepted_at)
        )
    ).all()
    pending_rows = (
        await session.execute(
            select(TaskCancellationRequestModel.task_id, TaskCancellationRequestModel.status).where(
                TaskCancellationRequestModel.task_id.in_(task_ids),
                TaskCancellationRequestModel.status == "pending",
            )
        )
    ).all()
    assignees: dict[uuid.UUID, list[OwnedTaskAssignee]] = {}
    for assignment, display_name in assignment_rows:
        assignees.setdefault(assignment.task_id, []).append(
            OwnedTaskAssignee(assignment.id, str(display_name), assignment.status)
        )
    pending = {row[0]: row[1] for row in pending_rows}
    return tuple(
        OwnedTaskCard(
            task=published_task_from_model(task),
            assignees=tuple(assignees.get(task.id, ())),
            cancellation_status=pending.get(task.id),
        )
        for task in tasks
    )


async def get_pending_request(session: AsyncSession, task_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(TaskCancellationRequestModel.id).where(
            TaskCancellationRequestModel.task_id == task_id,
            TaskCancellationRequestModel.status == "pending",
        )
    )


async def has_declined_request(session: AsyncSession, task_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    TaskCancellationRequestModel.task_id == task_id,
                    TaskCancellationRequestModel.status == "declined",
                )
            )
        )
    )


async def create_request(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    creator_id: uuid.UUID,
    assignments: tuple[Assignment, ...] | list[Assignment],
) -> uuid.UUID:
    model = TaskCancellationRequestModel(
        task_id=task_id, requested_by_member_id=creator_id, status="pending"
    )
    session.add(model)
    await session.flush()
    task = await session.get(TaskModel, task_id)
    title = "Задание" if task is None else task.title
    for assignment in assignments:
        response = TaskCancellationResponseModel(
            request_id=model.id,
            assignment_id=assignment.id,
            performer_id=assignment.performer_id,
            status="pending",
        )
        session.add(response)
        await session.flush()
        session.add(
            OutboxEventModel(
                event_type="task.cancellation_requested",
                aggregate_type="task_cancellation_response",
                aggregate_id=response.id,
                payload_json={"task_id": str(task_id), "title": title},
                business_key=f"task_cancel_response:{response.id}:requested",
            )
        )
    await session.flush()
    return model.id


async def get_response(
    session: AsyncSession, response_id: uuid.UUID, *, for_update: bool = False
) -> TaskCancellationResponse | None:
    statement = (
        select(TaskCancellationResponseModel, TaskCancellationRequestModel)
        .join(
            TaskCancellationRequestModel,
            TaskCancellationRequestModel.id == TaskCancellationResponseModel.request_id,
        )
        .where(TaskCancellationResponseModel.id == response_id)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        return None
    response, request = row
    return TaskCancellationResponse(
        id=response.id,
        request_id=request.id,
        task_id=request.task_id,
        assignment_id=response.assignment_id,
        performer_id=response.performer_id,
        request_status=request.status,
        request_resolution_reason=request.resolution_reason,
        response_status=response.status,
    )


async def answer_response(
    session: AsyncSession,
    *,
    response_id: uuid.UUID,
    accepted: bool,
    now: datetime.datetime,
) -> TaskCancellationResponse:
    model = await session.get(TaskCancellationResponseModel, response_id)
    if model is None:
        raise LookupError("Cancellation response does not exist.")
    model.status = "accepted" if accepted else "declined"
    model.responded_at = now
    await session.flush()
    value = await get_response(session, response_id)
    if value is None:
        raise LookupError("Cancellation response does not exist.")
    return value


async def all_accepted(session: AsyncSession, request_id: uuid.UUID) -> bool:
    return not bool(
        await session.scalar(
            select(
                exists().where(
                    TaskCancellationResponseModel.request_id == request_id,
                    TaskCancellationResponseModel.status != "accepted",
                )
            )
        )
    )


async def resolve_request(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    status: str,
    reason: str,
    now: datetime.datetime,
) -> None:
    model = await session.get(TaskCancellationRequestModel, request_id)
    if model is None:
        raise LookupError("Cancellation request does not exist.")
    model.status = status
    model.resolution_reason = reason
    model.resolved_at = now
    if status in {"declined", "obsolete"}:
        await session.execute(
            update(TaskCancellationResponseModel)
            .where(
                TaskCancellationResponseModel.request_id == request_id,
                TaskCancellationResponseModel.status == "pending",
            )
            .values(status="obsolete", responded_at=now)
        )
    await session.flush()


async def obsolete_pending_request(
    session: AsyncSession, task_id: uuid.UUID, reason: str, now: datetime.datetime
) -> bool:
    request_id = await get_pending_request(session, task_id)
    if request_id is None:
        return False
    await resolve_request(session, request_id=request_id, status="obsolete", reason=reason, now=now)
    return True


async def cancel_assignment_by_creator(
    session: AsyncSession,
    assignment_id: uuid.UUID,
    creator_id: uuid.UUID,
    reason: str,
) -> None:
    model = await session.get(AssignmentModel, assignment_id)
    if model is None:
        raise LookupError("Assignment does not exist.")
    model.status = "cancelled"
    model.cancelled_at = datetime.datetime.now(datetime.UTC)
    model.cancellation_reason = reason
    await session.flush()
    await append_reliability(session, model.id, "cancelled_creator", creator_id, reason)


async def add_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, object],
    business_key: str,
) -> None:
    session.add(
        OutboxEventModel(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=payload,
            business_key=business_key,
        )
    )
    await session.flush()
