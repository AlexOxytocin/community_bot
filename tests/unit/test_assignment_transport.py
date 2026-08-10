# ruff: noqa: RUF001
"""Focused parsing tests for assignment Telegram commands and callbacks."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.domain.assignments import AssignmentDecision, AssignmentError
from community_bot.transport.telegram.assignments import (
    _one_argument,
    _parse_decision,
    _parse_submission,
    _three_arguments,
    _two_arguments,
    build_assignment_router,
)
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Never

    from community_bot.application.assignments import AssignmentService


def test_assignment_command_arguments_are_parsed_without_losing_payload() -> None:
    """Valid command tails preserve free-form reason and JSON values."""
    assignment_id = str(uuid4())
    assert _one_argument(f"/assignment_submit {assignment_id}") == assignment_id
    assert _two_arguments(f"/assignment_cancel {assignment_id} a clear reason") == (
        assignment_id,
        "a clear reason",
    )
    assert _three_arguments(
        f'/assignment_result {assignment_id} 2 {{"summary":"complete value"}}'
    ) == (assignment_id, "2", '{"summary":"complete value"}')


@pytest.mark.parametrize(
    ("parser", "value"),
    [
        (_one_argument, None),
        (_one_argument, "/assignment_submit"),
        (_one_argument, "/assignment_submit one two"),
        (_two_arguments, None),
        (_two_arguments, "/assignment_cancel"),
        (_two_arguments, "/assignment_cancel only-one"),
        (_three_arguments, None),
        (_three_arguments, "/assignment_result"),
        (_three_arguments, "/assignment_result draft 1"),
    ],
)
def test_assignment_command_arguments_reject_incomplete_input(parser, value: str | None) -> None:  # noqa: ANN001
    """Malformed commands fail before any application workflow is called."""
    with pytest.raises(ValueError, match=r".+"):
        parser(value)


def test_assignment_callbacks_are_parsed_with_exact_identity() -> None:
    """Review and submit callbacks preserve UUID, decision, and revision."""
    assignment_id = uuid4()
    assert _parse_decision(f"assign:review:{assignment_id.hex}:partial") == (
        assignment_id,
        AssignmentDecision.PARTIAL,
    )
    assert _parse_submission(f"assign:submit:{assignment_id.hex}:7") == (assignment_id, 7)


@pytest.mark.parametrize(
    ("parser", "value"),
    [
        (_parse_decision, "assign:review:missing-separator"),
        (_parse_decision, "assign:review:not-a-uuid:full"),
        (_parse_decision, f"assign:review:{uuid4().hex}:unknown"),
        (_parse_submission, "assign:submit:missing-separator"),
        (_parse_submission, "assign:submit:not-a-uuid:1"),
        (_parse_submission, f"assign:submit:{uuid4().hex}:not-an-int"),
    ],
)
def test_assignment_callbacks_reject_malformed_identity(parser, value: str) -> None:  # noqa: ANN001
    """Malformed callback data cannot reach mutating application code."""
    with pytest.raises(ValueError, match=r".+"):
        parser(value)


_FAILURE_MESSAGE = "synthetic failure"


async def _fail_assignment_call(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise AssignmentError(_FAILURE_MESSAGE)


class _FailingAssignmentService:
    def __getattr__(self, name: str) -> Callable[..., Awaitable[Never]]:
        del name
        return _fail_assignment_call


@pytest.mark.asyncio
async def test_assignment_router_reports_invalid_updates_without_effects() -> None:
    """Every assignment transport route converts malformed input into a safe response."""
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_assignment_router(cast("AssignmentService", _FailingAssignmentService()))
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'T' * 35}", session=capture)
    actor = User(id=7001, is_bot=False, first_name="Performer")

    def message_update(update_id: int, value: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=actor.id, type="private"),
                from_user=actor,
                text=value,
            ),
        )

    def callback_update(update_id: int, value: str) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"invalid-{update_id}",
                from_user=actor,
                chat_instance="assignments",
                data=value,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text="invalid",
                ),
            ),
        )

    updates = [
        message_update(70_001, "/my_assignments"),
        message_update(70_002, "/assignment_cancel"),
        message_update(70_003, "/assignment_submit invalid"),
        message_update(70_004, "/assignment_result draft 0 not-json"),
        message_update(70_005, "/assignment_dispute"),
        callback_update(70_006, "task:accept:invalid"),
        callback_update(70_007, "assign:review:invalid"),
        callback_update(70_008, "assign:submit:invalid"),
    ]
    for update in updates:
        await dispatcher.feed_update(bot, update)

    assert len(capture.texts) == len(updates)
    assert all("Не удалось" in value for value in capture.texts)
    await bot.session.close()
