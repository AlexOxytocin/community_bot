"""Focused safety coverage for output-driven task Telegram routes."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Never, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.application.tasks import TaskDraft
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import TaskDraftStep, TaskError, TaskStatus
from community_bot.transport.telegram.tasks import (
    _cancel_error,
    _credits,
    _encode_uuid,
    _friendly_error,
    _obsolete_cancellation_message,
    _required_tail,
    build_task_router,
    task_cancellation_keyboard,
)
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from community_bot.application.tasks import PublishedTask, TaskService

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
            community_approval_requested_at=None,
            community_approved_by_admin_id=None,
            community_approved_at=None,
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
        callback_update(93_016, f"task:cancel:ask:{encoded}"),
        callback_update(93_017, f"task:cancel:do:{encoded}"),
    ]
    for update in updates:
        await dispatcher.feed_update(bot, update)

    assert len(capture.texts) == len(updates)
    assert all("не" in value.lower() or "ошиб" in value.lower() for value in capture.texts)
    await bot.session.close()


@pytest.mark.asyncio
async def test_task_cancellation_callbacks_reject_group_chat_before_service() -> None:
    """Cancellation cannot be requested or confirmed outside the private chat."""
    service = _DeniedTaskService()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_task_router(cast("TaskService", service)))
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'K' * 35}", session=capture)
    actor = User(id=9302, is_bot=False, first_name="Author")
    encoded = _encode_uuid(uuid4())

    for update_id, data in (
        (93_101, f"task:cancel:ask:{encoded}"),
        (93_102, f"task:cancel:do:{encoded}"),
        (93_103, "task:cancel:no"),
    ):
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"group-task-{update_id}",
                    from_user=actor,
                    chat_instance="group-task-cancellation",
                    data=data,
                    message=Message(
                        message_id=update_id,
                        date=datetime.datetime.now(datetime.UTC),
                        chat=Chat(id=-1009302, type="supergroup"),
                        from_user=actor,
                        text="task",
                    ),
                ),
            ),
        )

    private_only = "Работа с заданиями доступна только в личном чате с ботом."  # noqa: RUF001
    assert capture.callback_answers == [private_only, private_only, private_only]
    await bot.session.close()


@pytest.mark.parametrize(
    ("creator_id", "status"),
    [
        (None, TaskStatus.PUBLISHED),
        (uuid4(), TaskStatus.CANCELLED),
        (uuid4(), TaskStatus.EXPIRED),
        (uuid4(), TaskStatus.PARTIALLY_COMPLETED),
        (uuid4(), TaskStatus.COMPLETED),
    ],
)
def test_task_cancellation_button_is_hidden_for_community_and_terminal_tasks(
    creator_id: object, status: TaskStatus
) -> None:
    """Only a member-owned published task exposes the cancellation action."""
    task = cast(
        "PublishedTask",
        SimpleNamespace(id=uuid4(), creator_id=creator_id, status=status),
    )

    assert task_cancellation_keyboard(task) is None


def test_task_transport_formats_credit_forms_and_safe_errors() -> None:
    """Compact task controls keep Russian forms and do not expose exception details."""
    assert _credits(1).endswith("кредит")
    assert _credits(2).endswith("кредита")
    assert _credits(5).endswith("кредитов")
    assert _credits(11).endswith("кредитов")
    assert _required_tail("/task_cancel value") == "value"
    with pytest.raises(TaskError, match="argument is required"):
        _required_tail("/task_cancel")
    assert "автор" in _cancel_error(PermissionError()).lower()
    assert "уже отменено" in _cancel_error(TaskError("already cancelled")).lower()
    assert "недоступно" in _cancel_error(TaskError("current state")).lower()
    assert "исполнитель" in _cancel_error(TaskError("assignment history")).lower()
    assert "недоступно" in _friendly_error(PermissionError()).lower()
    assert "срок" in _obsolete_cancellation_message("deadline_reached").lower()
    assert "работа уже началась" in _obsolete_cancellation_message("work_started").lower()
    assert "исполнение" in _obsolete_cancellation_message("assignment_cancelled").lower()
