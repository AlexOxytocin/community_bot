"""Assignment lifecycle domain tests."""

from __future__ import annotations

import datetime
from dataclasses import replace
from uuid import uuid4

import pytest

from community_bot.domain.assignments import (
    Assignment,
    AssignmentError,
    AssignmentStatus,
    partial_reward,
    require_dispute_allowed,
    require_submit_allowed,
)


def test_partial_reward_uses_approved_ceiling_rule() -> None:
    """Partial settlement rounds one half upward and rejects reward one."""
    assert [partial_reward(value) for value in (2, 3, 4, 5, 11)] == [1, 2, 2, 3, 6]
    with pytest.raises(AssignmentError):
        partial_reward(1)


def test_dispute_window_is_half_open() -> None:
    """The performer may dispute before but not at the 24-hour boundary."""
    now = datetime.datetime.now(datetime.UTC)
    assignment = Assignment(
        id=uuid4(),
        task_id=uuid4(),
        performer_id=uuid4(),
        slot_number=1,
        status=AssignmentStatus.REJECTED_PENDING_DISPUTE,
        accepted_at=now,
        rejected_at=now,
        reject_dispute_deadline_at=now + datetime.timedelta(hours=24),
    )
    require_dispute_allowed(assignment, now=now + datetime.timedelta(hours=23))
    with pytest.raises(AssignmentError):
        require_dispute_allowed(assignment, now=now + datetime.timedelta(hours=24))


def test_submit_requires_active_assignment_and_open_deadline() -> None:
    now = datetime.datetime.now(datetime.UTC)
    accepted = Assignment(
        id=uuid4(),
        task_id=uuid4(),
        performer_id=uuid4(),
        slot_number=1,
        status=AssignmentStatus.ACCEPTED,
        accepted_at=now,
    )
    require_submit_allowed(accepted, task_deadline=now + datetime.timedelta(hours=1), now=now)
    with pytest.raises(AssignmentError, match="current state"):
        require_submit_allowed(
            replace(accepted, status=AssignmentStatus.SUBMITTED),
            task_deadline=now + datetime.timedelta(hours=1),
            now=now,
        )
    with pytest.raises(AssignmentError, match="deadline"):
        require_submit_allowed(accepted, task_deadline=now, now=now)
    with pytest.raises(AssignmentError, match="current state"):
        require_submit_allowed(
            replace(accepted, status=AssignmentStatus.CANCELLED),
            task_deadline=now + datetime.timedelta(hours=1),
            now=now,
        )
