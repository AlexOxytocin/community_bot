from __future__ import annotations

import datetime
from uuid import uuid4

import pytest

from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import ResolvedLevel
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.tasks import (
    AcceptanceTaskSnapshot,
    TaskError,
    TaskStatus,
    validate_acceptance_actor,
    validate_deadline,
    validate_materials,
    validate_slots,
    validate_task_format,
)


def test_deadline_format_slots_and_materials_boundaries() -> None:
    now = datetime.datetime.now(datetime.UTC)
    future = now + datetime.timedelta(hours=1)
    assert validate_deadline(future, now=now) == future
    with pytest.raises(TaskError):
        validate_deadline(now, now=now)
    with pytest.raises(TaskError):
        validate_deadline(future.replace(tzinfo=None), now=now)

    assert validate_task_format(TaskFormat.ONLINE, template_format=TaskFormat.ANY, city=None) == (
        TaskFormat.ONLINE,
        None,
    )
    with pytest.raises(TaskError):
        validate_task_format(TaskFormat.OFFLINE, template_format=TaskFormat.ANY, city=" ")
    with pytest.raises(TaskError):
        validate_task_format(TaskFormat.OFFLINE, template_format=TaskFormat.ONLINE, city="City")
    assert validate_slots(2, maximum=2) == 2
    with pytest.raises(TaskError):
        validate_slots(3, maximum=2)
    assert validate_materials({"url": " https://example.com "}) == {"url": "https://example.com"}
    with pytest.raises(TaskError):
        validate_materials({"secret": "value"})


def test_acceptance_uses_authoritative_level_and_rejects_creator() -> None:
    creator_id = uuid4()
    task = AcceptanceTaskSnapshot(creator_id, TaskStatus.PUBLISHED, minimum_level=2)
    creator = Member(creator_id, 1, MemberRole.MEMBER, MemberStatus.ACTIVE)
    other = Member(uuid4(), 2, MemberRole.MEMBER, MemberStatus.ACTIVE)
    high = ResolvedLevel(uuid4(), 2, 9, "High")
    low = ResolvedLevel(uuid4(), 1, 1, "Low")
    exact = ResolvedLevel(uuid4(), 3, 2, "Exact")
    with pytest.raises(PermissionError):
        validate_acceptance_actor(task, creator, resolved_level=high)
    with pytest.raises(PermissionError):
        validate_acceptance_actor(task, other, resolved_level=low)
    validate_acceptance_actor(task, other, resolved_level=exact)
