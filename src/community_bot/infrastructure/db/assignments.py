# ruff: noqa: EM101, PLR0913, TRY003
"""PostgreSQL persistence for task assignments and result review."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

from community_bot.domain.assignments import (
    ACTIVE_ASSIGNMENT_STATUSES,
    OCCUPIED_SLOT_STATUSES,
    Assignment,
    AssignmentError,
    AssignmentStatus,
    ResultVersion,
    SubmissionDraft,
)
from community_bot.infrastructure.db.models import (
    AssignmentDisputeModel,
    AssignmentModel,
    AssignmentResultVersionModel,
    AssignmentSubmissionDraftModel,
    OutboxEventModel,
    ReliabilityEventModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_TASK_GATE = "task_assignment"
_ACTIVE_LIMIT_GATE = "assignment_active_limit"


async def acquire_task_gate(session: AsyncSession, task_id: uuid.UUID) -> None:
    """Serialize mutations of one task aggregate."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:value, hashtextextended(:gate, 0)))"),
        {"gate": _TASK_GATE, "value": str(task_id)},
    )


async def acquire_active_limit_gate(session: AsyncSession, member_id: uuid.UUID) -> None:
    """Serialize concurrent accepts by one performer across different tasks."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:value, hashtextextended(:gate, 0)))"),
        {"gate": _ACTIVE_LIMIT_GATE, "value": str(member_id)},
    )


async def count_active(session: AsyncSession, performer_id: uuid.UUID) -> int:
    """Count assignments occupying the configurable active limit."""
    statuses = tuple(status.value for status in ACTIVE_ASSIGNMENT_STATUSES)
    value = await session.scalar(
        select(func.count(AssignmentModel.id)).where(
            AssignmentModel.performer_id == performer_id,
            AssignmentModel.status.in_(statuses),
        )
    )
    return int(value or 0)


async def create_assignment(
    session: AsyncSession, *, task_id: uuid.UUID, performer_id: uuid.UUID, slots: int
) -> Assignment:
    """Claim the lowest currently free slot under the task gate."""
    occupied = set(
        await session.scalars(
            select(AssignmentModel.slot_number).where(
                AssignmentModel.task_id == task_id,
                AssignmentModel.status.in_(tuple(s.value for s in OCCUPIED_SLOT_STATUSES)),
            )
        )
    )
    slot = next((candidate for candidate in range(1, slots + 1) if candidate not in occupied), None)
    if slot is None:
        raise AssignmentError("Task has no free performer slots.")
    model = AssignmentModel(task_id=task_id, performer_id=performer_id, slot_number=slot)
    session.add(model)
    await session.flush()
    await append_reliability(session, model.id, "accepted", performer_id, None)
    return _assignment(model)


async def lock_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> Assignment | None:
    """Lock one assignment lifecycle row."""
    model = await session.scalar(
        select(AssignmentModel).where(AssignmentModel.id == assignment_id).with_for_update()
    )
    return None if model is None else _assignment(model)


async def get_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> Assignment | None:
    """Read one assignment without taking a row lock before the task gate."""
    model = await session.get(AssignmentModel, assignment_id)
    return None if model is None else _assignment(model)


async def list_assignments(
    session: AsyncSession, performer_id: uuid.UUID
) -> tuple[Assignment, ...]:
    """List a performer's latest assignments."""
    models = (
        await session.scalars(
            select(AssignmentModel)
            .where(AssignmentModel.performer_id == performer_id)
            .order_by(AssignmentModel.accepted_at.desc())
            .limit(20)
        )
    ).all()
    return tuple(_assignment(model) for model in models)


async def list_task_assignments(
    session: AsyncSession, task_id: uuid.UUID, *, for_update: bool = False
) -> tuple[Assignment, ...]:
    """List all historical assignments of one task in canonical order."""
    statement = (
        select(AssignmentModel)
        .where(AssignmentModel.task_id == task_id)
        .order_by(AssignmentModel.slot_number, AssignmentModel.accepted_at, AssignmentModel.id)
    )
    if for_update:
        statement = statement.with_for_update()
    models = (await session.scalars(statement)).all()
    return tuple(_assignment(model) for model in models)


async def cancel_assignment(
    session: AsyncSession, assignment_id: uuid.UUID, reason: str
) -> Assignment:
    """Cancel an accepted assignment while preserving its history."""
    model = await session.get(AssignmentModel, assignment_id)
    if model is None:
        raise LookupError("Assignment does not exist.")
    model.status = AssignmentStatus.CANCELLED.value
    model.cancelled_at = datetime.datetime.now(datetime.UTC)
    model.cancellation_reason = reason
    await session.flush()
    await append_reliability(session, model.id, "cancelled_performer", model.performer_id, reason)
    return _assignment(model)


async def append_result(
    session: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    command_id: uuid.UUID,
    payload: dict[str, object],
    now: datetime.datetime,
) -> ResultVersion:
    """Append and select a new current result version."""
    existing = await session.scalar(
        select(AssignmentResultVersionModel).where(
            AssignmentResultVersionModel.submit_command_id == command_id
        )
    )
    if existing is not None:
        if existing.assignment_id != assignment_id or existing.payload_json != payload:
            raise ValueError("Result command identity conflicts with stored payload.")
        return _result(existing)
    latest = await session.scalar(
        select(func.max(AssignmentResultVersionModel.version)).where(
            AssignmentResultVersionModel.assignment_id == assignment_id
        )
    )
    model = AssignmentResultVersionModel(
        assignment_id=assignment_id,
        version=int(latest or 0) + 1,
        payload_json=payload,
        submit_command_id=command_id,
    )
    assignment = await session.get(AssignmentModel, assignment_id)
    if assignment is None:
        raise LookupError("Assignment does not exist.")
    assignment.status = AssignmentStatus.SUBMITTED.value
    assignment.submitted_at = now
    if assignment.review_deadline_at is None:
        assignment.review_deadline_at = now + datetime.timedelta(hours=72)
    session.add(model)
    await session.flush()
    return _result(model)


async def get_result(session: AsyncSession, result_id: uuid.UUID) -> ResultVersion | None:
    """Read one immutable result version by its durable identity."""
    model = await session.get(AssignmentResultVersionModel, result_id)
    return None if model is None else _result(model)


async def get_submission_draft(
    session: AsyncSession, draft_id: uuid.UUID, *, for_update: bool = False
) -> SubmissionDraft | None:
    """Read or lock one durable Telegram submission draft."""
    statement = select(AssignmentSubmissionDraftModel).where(
        AssignmentSubmissionDraftModel.id == draft_id
    )
    if for_update:
        statement = statement.with_for_update()
    model = await session.scalar(statement)
    return None if model is None else _submission_draft(model)


async def create_or_get_submission_draft(
    session: AsyncSession, *, assignment_id: uuid.UUID, performer_id: uuid.UUID
) -> SubmissionDraft:
    """Create the stable confirmation identity for one assignment."""
    model = await session.scalar(
        select(AssignmentSubmissionDraftModel)
        .where(
            AssignmentSubmissionDraftModel.assignment_id == assignment_id,
            AssignmentSubmissionDraftModel.submitted_result_id.is_(None),
        )
        .order_by(AssignmentSubmissionDraftModel.created_at.desc())
        .with_for_update()
    )
    if model is None:
        model = AssignmentSubmissionDraftModel(
            assignment_id=assignment_id,
            performer_id=performer_id,
            submit_command_id=uuid.uuid4(),
        )
        session.add(model)
        await session.flush()
    if model.performer_id != performer_id:
        raise PermissionError("Submission draft belongs to another performer.")
    return _submission_draft(model)


async def save_submission_draft_payload(
    session: AsyncSession,
    *,
    draft_id: uuid.UUID,
    expected_revision: int,
    payload: dict[str, object],
) -> SubmissionDraft:
    """Replace a preview payload under optimistic revision control."""
    model = await session.scalar(
        select(AssignmentSubmissionDraftModel)
        .where(AssignmentSubmissionDraftModel.id == draft_id)
        .with_for_update()
    )
    if model is None:
        raise LookupError("Submission draft does not exist.")
    if model.submitted_result_id is not None:
        raise ValueError("Submission draft is already confirmed.")
    if model.revision != expected_revision:
        raise ValueError("Submission draft revision is stale.")
    model.payload_json = payload
    model.revision += 1
    model.updated_at = datetime.datetime.now(datetime.UTC)
    await session.flush()
    return _submission_draft(model)


async def complete_submission_draft(
    session: AsyncSession, *, draft_id: uuid.UUID, result_id: uuid.UUID
) -> SubmissionDraft:
    """Bind a confirmed draft to its immutable result version."""
    model = await session.get(AssignmentSubmissionDraftModel, draft_id)
    if model is None:
        raise LookupError("Submission draft does not exist.")
    if model.submitted_result_id not in {None, result_id}:
        raise ValueError("Submission draft already points to another result.")
    model.submitted_result_id = result_id
    model.updated_at = datetime.datetime.now(datetime.UTC)
    await session.flush()
    return _submission_draft(model)


async def set_decision(
    session: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    status: AssignmentStatus,
    command_id: uuid.UUID,
    outcome: str,
    now: datetime.datetime,
) -> Assignment:
    """Persist one review transition under the assignment lock."""
    model = await session.get(AssignmentModel, assignment_id)
    if model is None:
        raise LookupError("Assignment does not exist.")
    model.status = status.value
    model.terminal_command_id = command_id
    model.terminal_outcome = outcome
    if status is AssignmentStatus.REJECTED_PENDING_DISPUTE:
        model.rejected_at = now
        model.reject_dispute_deadline_at = now + datetime.timedelta(hours=24)
    else:
        model.reviewed_at = now
    await session.flush()
    return _assignment(model)


async def open_dispute(
    session: AsyncSession,
    *,
    assignment_id: uuid.UUID,
    performer_id: uuid.UUID,
    command_id: uuid.UUID,
    comment: str,
) -> uuid.UUID:
    """Insert the immutable private handoff for future dispute moderation."""
    existing = await session.scalar(
        select(AssignmentDisputeModel).where(AssignmentDisputeModel.assignment_id == assignment_id)
    )
    if existing is not None:
        if existing.open_command_id != command_id or existing.comment != comment:
            raise ValueError("Assignment already has another dispute opening.")
        return existing.id
    model = AssignmentDisputeModel(
        assignment_id=assignment_id,
        performer_id=performer_id,
        open_command_id=command_id,
        comment=comment,
    )
    session.add(model)
    await session.flush()
    assignment = await session.get(AssignmentModel, assignment_id)
    if assignment is None:
        raise LookupError("Assignment does not exist.")
    assignment.status = AssignmentStatus.DISPUTED.value
    await session.flush()
    return model.id


async def append_reliability(
    session: AsyncSession,
    assignment_id: uuid.UUID,
    event_type: str,
    actor_id: uuid.UUID | None,
    reason: str | None,
) -> None:
    """Append a reliability fact."""
    session.add(
        ReliabilityEventModel(
            assignment_id=assignment_id,
            event_type=event_type,
            actor_member_id=actor_id,
            reason=reason,
        )
    )
    await session.flush()


async def add_outbox(
    session: AsyncSession, *, assignment: Assignment, event_type: str, business_key: str
) -> None:
    """Stage a privacy-minimal assignment event."""
    session.add(
        OutboxEventModel(
            event_type=event_type,
            aggregate_type="assignment",
            aggregate_id=assignment.id,
            payload_json={
                "assignment_id": str(assignment.id),
                "task_id": str(assignment.task_id),
                "status": assignment.status.value,
            },
            business_key=business_key,
        )
    )


def _assignment(model: AssignmentModel) -> Assignment:
    return Assignment(
        id=model.id,
        task_id=model.task_id,
        performer_id=model.performer_id,
        slot_number=model.slot_number,
        status=AssignmentStatus(model.status),
        accepted_at=model.accepted_at,
        submitted_at=model.submitted_at,
        review_deadline_at=model.review_deadline_at,
        rejected_at=model.rejected_at,
        reject_dispute_deadline_at=model.reject_dispute_deadline_at,
        terminal_outcome=model.terminal_outcome,
        terminal_command_id=model.terminal_command_id,
    )


def _result(model: AssignmentResultVersionModel) -> ResultVersion:
    return ResultVersion(
        id=model.id,
        assignment_id=model.assignment_id,
        version=model.version,
        payload=dict(model.payload_json),
        submit_command_id=model.submit_command_id,
        created_at=model.created_at,
    )


def _submission_draft(model: AssignmentSubmissionDraftModel) -> SubmissionDraft:
    return SubmissionDraft(
        id=model.id,
        assignment_id=model.assignment_id,
        performer_id=model.performer_id,
        submit_command_id=model.submit_command_id,
        revision=model.revision,
        payload=None if model.payload_json is None else dict(model.payload_json),
        submitted_result_id=model.submitted_result_id,
    )
