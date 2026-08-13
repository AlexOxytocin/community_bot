"""Privacy boundary for durable Telegram text conversations."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Never, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, Update, User

from community_bot.application.conversations import TextFlow
from community_bot.transport.telegram.conversation import build_conversation_router
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from community_bot.application.assignments import AssignmentService
    from community_bot.application.conversations import ConversationService
    from community_bot.application.registration import RegistrationService
    from community_bot.application.reputation import ReputationService
    from community_bot.application.tasks import TaskService

_UNEXPECTED_CALL = "A private task flow operation reached the service from a group chat."


async def _unexpected_call(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise AssertionError(_UNEXPECTED_CALL)


class _FailOnUse:
    def __getattr__(self, name: str) -> Callable[..., Awaitable[Never]]:
        del name
        return _unexpected_call


class _TaskConversation:
    def __init__(self) -> None:
        self.owner = TextFlow(uuid4(), "task", "input", uuid4(), 1)

    async def current(self, telegram_user_id: int) -> TextFlow:
        del telegram_user_id
        return self.owner


@pytest.mark.asyncio
async def test_task_conversation_text_and_cancel_reject_group_chat() -> None:
    """An active task draft cannot advance or be cancelled from a group."""
    failing = _FailOnUse()
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_conversation_router(
            cast("TaskService", failing),
            cast("RegistrationService", failing),
            cast("AssignmentService", failing),
            cast("ReputationService", failing),
            cast("ConversationService", _TaskConversation()),
        )
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'C' * 35}", session=capture)
    actor = User(id=9401, is_bot=False, first_name="Author")
    group = Chat(id=-1009401, type="supergroup")

    def update(update_id: int, text: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=group,
                from_user=actor,
                text=text,
            ),
        )

    await dispatcher.feed_update(bot, update(94_001, "Новое описание задания"))
    await dispatcher.feed_update(bot, update(94_002, "/cancel"))

    assert capture.texts == [
        "Работа с заданиями доступна только в личном чате с ботом.",  # noqa: RUF001
        "Работа с заданиями доступна только в личном чате с ботом.",  # noqa: RUF001
    ]
    await bot.session.close()
