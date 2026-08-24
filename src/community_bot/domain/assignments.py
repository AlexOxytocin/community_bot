# ruff: noqa: EM101, TRY003
"""Task assignment lifecycle and deterministic settlement rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime
    from uuid import UUID


class AssignmentError(ValueError):
    """Raised when an assignment transition is invalid."""


class AssignmentStatus(StrEnum):
    """Persistent assignment lifecycle states."""

    ACCEPTED = "accepted"
    SUBMITTED = "submitted"
    REJECTED_PENDING_DISPUTE = "rejected_pending_dispute"
    DISPUTED = "disputed"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    REVIEWER_REQUIRED = "reviewer_required"


class AssignmentDecision(StrEnum):
    """Author decisions supported by the MVP."""

    FULL = "full"
    PARTIAL = "partial"
    REJECT = "reject"


ACTIVE_ASSIGNMENT_STATUSES = frozenset(
    {
        AssignmentStatus.ACCEPTED,
        AssignmentStatus.SUBMITTED,
        AssignmentStatus.REJECTED_PENDING_DISPUTE,
        AssignmentStatus.DISPUTED,
        AssignmentStatus.REVIEWER_REQUIRED,
    }
)

OCCUPIED_SLOT_STATUSES = frozenset(
    status for status in AssignmentStatus if status is not AssignmentStatus.CANCELLED
)


@dataclass(frozen=True, slots=True)
class Assignment:
    """Transport-neutral assignment snapshot."""

    id: UUID
    task_id: UUID
    performer_id: UUID
    slot_number: int
    status: AssignmentStatus
    accepted_at: datetime.datetime
    submitted_at: datetime.datetime | None = None
    review_deadline_at: datetime.datetime | None = None
    rejected_at: datetime.datetime | None = None
    reject_dispute_deadline_at: datetime.datetime | None = None
    reviewed_at: datetime.datetime | None = None
    terminal_outcome: str | None = None
    terminal_command_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ResultVersion:
    """One immutable assignment result version."""

    id: UUID
    assignment_id: UUID
    version: int
    payload: dict[str, object]
    submit_command_id: UUID
    created_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class SubmissionDraft:
    """Durable result input awaiting explicit performer confirmation."""

    id: UUID
    assignment_id: UUID
    performer_id: UUID
    submit_command_id: UUID
    revision: int
    payload: dict[str, object] | None
    submitted_result_id: UUID | None


def partial_reward(full_reward: Decimal | int) -> Decimal:
    """Return half of a reward, rounded up to the supported tenth of a credit."""
    reward = Decimal(str(full_reward))
    if reward < Decimal("0.2"):
        raise AssignmentError("Partial approval requires a reward of at least 0.2 credits.")
    return (reward / 2).quantize(Decimal("0.1"), rounding=ROUND_CEILING)


def require_submit_allowed(
    assignment: Assignment, *, task_deadline: datetime.datetime, now: datetime.datetime
) -> None:
    """Validate a result submission or follow-up version."""
    if assignment.status not in {AssignmentStatus.ACCEPTED, AssignmentStatus.SUBMITTED}:
        raise AssignmentError("Assignment does not accept result versions in its current state.")
    if now >= task_deadline:
        raise AssignmentError("Task submission deadline has passed.")


def require_dispute_allowed(assignment: Assignment, *, now: datetime.datetime) -> None:
    """Validate the half-open rejection dispute window."""
    if assignment.status is not AssignmentStatus.REJECTED_PENDING_DISPUTE:
        raise AssignmentError("Only a rejected pending assignment can be disputed.")
    if assignment.rejected_at is None or assignment.reject_dispute_deadline_at is None:
        raise AssignmentError("Assignment rejection window is incomplete.")
    if not assignment.rejected_at <= now < assignment.reject_dispute_deadline_at:
        raise AssignmentError("Assignment dispute window has closed.")
