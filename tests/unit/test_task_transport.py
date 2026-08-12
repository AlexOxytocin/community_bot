"""Focused safety coverage for output-driven task Telegram routes."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Never, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.application.tasks import TaskDraft
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import TaskDraftStep, TaskError
from community_bot.transport.telegram.tasks import _encode_uuid, build_task_router
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from community_bot.application.tasks import TaskService

_DENIAL = "synthetic denial"


async def _deny_task(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise TaskError(_DENIAL)


class _DeniedTaskService:
    """Return one owned draft and deny every attempted mutation."""

    def __init__(self) -> None:
        identifier = uuid4()
        self.draft = TaskDraft(
            id=identifier,
            creator_id=uuid4(),
            origin="member",
            reviewer_admin_id=None,
            template_id=uuid4(),
            input_payload=None,
            deadline_at=None,
            format=TaskFormat.ONLINE,
            city=None,
            materials=None,
            performer_slots=None,
            current_step=TaskDraftStep.INPUT,
            revision=1,
            is_current=True,
            publish_command_id=uuid4(),
        )

    async def current(self, **kwargs: object) -> TaskDraft:
        del kwargs
        return self.draft

    async def cancel_draft(self, **kwargs: object) -> Never:
        return await _deny_task(**kwargs)

    async def community_reviewers(self, *args: object) -> Never:
        return await _deny_task(*args)

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Never]]:
        del name
        return _deny_task


@pytest.mark.asyncio
async def test_task_router_safely_denies_every_output_driven_route() -> None:
    """Commands, callbacks, and free text fail visibly without leaking internals."""
    service = _DeniedTaskService()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_task_router(cast("TaskService", service)))
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'K' * 35}", session=capture)
    actor = User(id=9301, is_bot=False, first_name="Author")
    entity_id = uuid4()
    encoded = _encode_uuid(entity_id)

    def message_update(update_id: int, text: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=actor.id, type="private"),
                from_user=actor,
                text=text,
            ),
        )

    def callback_update(update_id: int, data: str) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"task-{update_id}",
                from_user=actor,
                chat_instance="tasks",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text="task",
                ),
            ),
        )

    updates = [
        message_update(93_001, f"/task_create {entity_id}"),
        message_update(93_002, f"/task_resume {entity_id}"),
        message_update(93_003, "/task_preview"),
        message_update(93_004, "/my_tasks"),
        message_update(93_005, f"/task_cancel {entity_id}"),
        message_update(93_006, "A sufficiently detailed task description"),
        callback_update(93_007, f"task:pub:{entity_id.hex}:1"),
        callback_update(93_008, f"task:reviewer:{entity_id.hex}"),
        callback_update(93_009, "task:step:days:7"),
        callback_update(93_010, "task:step:online"),
        callback_update(93_011, "task:step:materials:none"),
        callback_update(93_012, "task:step:slots:2"),
        callback_update(93_013, "task:step:preview"),
        callback_update(93_014, f"task:rr:{encoded}"),
        callback_update(93_015, f"task:rs:{encoded}:{encoded}"),
    ]
    for update in updates:
        await dispatcher.feed_update(bot, update)

    assert len(capture.texts) == len(updates)
    assert all("не" in value.lower() or "ошиб" in value.lower() for value in capture.texts)
    await bot.session.close()
