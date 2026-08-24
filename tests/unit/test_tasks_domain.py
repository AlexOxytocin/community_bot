from __future__ import annotations

import datetime
from typing import cast
from uuid import uuid4

import pytest

from community_bot.domain.catalog import TaskFormat
from community_bot.domain.economy import ResolvedLevel
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.tasks import (
    AcceptanceTaskSnapshot,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
    task_time_size_label,
    validate_acceptance_actor,
    validate_deadline,
    validate_freeform_materials,
    validate_freeform_result_payload,
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
    for unsafe_url in (
        "tg://resolve?domain=example",
        "file:///etc/passwd",
        "intent://example",
        "https://user:password@example.com/private",
    ):
        with pytest.raises(TaskError):
            validate_materials({"url": unsafe_url})
        with pytest.raises(TaskError):
            validate_public_text_uris({"context": f"Откройте {unsafe_url}"})
    for executable_uri in ("tg:resolve?domain=x", "file:C:/secret", "intent:open"):
        with pytest.raises(TaskError):
            validate_public_text_uris(executable_uri)
    for invalid_http_url in (
        "https://exa mple.com",
        "https://.",
        "https://example.com:bad",
        "https://[",
        "https://example.com/" + "a" * 700,
    ):
        with pytest.raises(TaskError):
            validate_materials({"url": invalid_http_url})


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
    with pytest.raises(TaskError):
        validate_acceptance_actor(
            AcceptanceTaskSnapshot(creator_id, TaskStatus.CLOSED_FOR_NEW_PERFORMERS, 1),
            other,
            resolved_level=exact,
        )
    inactive = Member(uuid4(), 3, MemberRole.MEMBER, MemberStatus.PAUSED)
    with pytest.raises(PermissionError):
        validate_acceptance_actor(task, inactive, resolved_level=high)
    validate_acceptance_actor(task, other, resolved_level=exact)


def test_freeform_size_reward_slots_and_text_boundaries() -> None:
    assert task_time_size_label(TaskTimeSize.XS).startswith("⚡ XS")
    assert validate_time_size("xl") is TaskTimeSize.XL
    assert validate_freeform_slots(1, kind=TaskKind.SOLO) == 1
    assert validate_freeform_slots(3, kind=TaskKind.GROUP) == 3
    with pytest.raises(TaskError):
        validate_freeform_slots(1, kind=TaskKind.GROUP)
    assert validate_freeform_reward(TaskTimeSize.XS, 2) == 2
    assert validate_freeform_reward(TaskTimeSize.XL, 11) == 11
    with pytest.raises(TaskError):
        validate_freeform_reward(TaskTimeSize.XL, 10)
    with pytest.raises(TaskError):
        validate_freeform_reward(TaskTimeSize.S, 5)
    assert validate_freeform_text("  Короткое название  ", field="title") == "Короткое название"
    with pytest.raises(TaskError):
        validate_freeform_text("x" * 81, field="title")
    assert validate_freeform_result_payload({"result": "Достаточно подробный результат."}) == {
        "result": "Достаточно подробный результат."
    }


def test_freeform_validators_reject_invalid_shapes() -> None:
    assert validate_task_kind("solo") is TaskKind.SOLO
    assert validate_task_kind(TaskKind.GROUP) is TaskKind.GROUP
    with pytest.raises(TaskError):
        validate_task_kind("pair")
    with pytest.raises(TaskError):
        validate_time_size("xxl")

    for invalid_slots in (True, 0, -1, "3"):
        with pytest.raises(TaskError):
            validate_freeform_slots(cast("int", invalid_slots), kind=TaskKind.SOLO)
    with pytest.raises(TaskError):
        validate_freeform_slots(2, kind=TaskKind.SOLO)
    with pytest.raises(TaskError):
        validate_freeform_slots(1, kind=TaskKind.GROUP)

    for invalid_reward in (True, "3"):
        with pytest.raises(TaskError):
            validate_freeform_reward(TaskTimeSize.S, cast("int", invalid_reward))
    with pytest.raises(TaskError):
        validate_freeform_reward(TaskTimeSize.M, 8)

    with pytest.raises(TaskError):
        validate_freeform_text("value", field="unknown")
    with pytest.raises(TaskError):
        validate_freeform_text(123, field="title")
    with pytest.raises(TaskError):
        validate_freeform_text("   ", field="description")
    with pytest.raises(TaskError):
        validate_freeform_text("tg://resolve?domain=x", field="completion_criteria")

    assert validate_freeform_text(" clear text ", field="description") == "clear text"
    assert validate_freeform_text("done", field="completion_criteria") == "done"


def test_freeform_materials_and_result_payload_boundaries() -> None:
    assert validate_freeform_materials({"text": " safe note "}) == {"text": "safe note"}
    with pytest.raises(TaskError):
        validate_freeform_materials({"text": "x" * 1001})

    for payload in (
        {},
        {"result": "valid result", "extra": "no"},
        {"result": 123},
        {"result": "too short"},
        {"result": "x" * 2001},
        {"result": "open tg://resolve?domain=x now"},
    ):
        with pytest.raises(TaskError):
            validate_freeform_result_payload(payload)

    assert validate_freeform_result_payload({"result": "  useful result text  "}) == {
        "result": "useful result text"
    }
    validate_public_text_uris(["https://example.com/path", ("plain text",)])
