"""Focused safety coverage for output-driven task Telegram routes."""

from __future__ import annotations

import datetime
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Never, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.application.tasks import (
    CommunityPublicationRequest,
    OwnedTaskAssignee,
    OwnedTaskCard,
    TaskCategoryOption,
    TaskDraft,
)
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import (
    TaskDraftStep,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
)
from community_bot.transport.telegram import tasks as task_transport
from community_bot.transport.telegram.tasks import (
    _cancel_confirmation_keyboard,
    _cancel_error,
    _cancellation_response_error,
    _category_prompt,
    _credits,
    _decode_uuid,
    _draft_prompt,
    _edit_callback,
    _encode_uuid,
    _friendly_error,
    _obsolete_cancellation_message,
    _parse_approval_callback,
    _parse_edit_callback,
    _parse_publish_callback,
    _parse_step_value,
    _required_tail,
    _reward_prompt,
    _slot_counter_rows,
    build_task_router,
    cancellation_response_callback,
    community_publication_approval_keyboard,
    owned_task_keyboard,
    owned_task_summary,
    reviewer_replacement_callback,
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
            category_id=None,
            task_kind=None,
            time_size=None,
            title=None,
            description=None,
            completion_criteria=None,
            credit_reward_per_performer=None,
            estimated_minutes=None,
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
    assert "не найден" in _cancellation_response_error(LookupError("does not exist")).lower()
    assert "другому" in _cancellation_response_error(PermissionError()).lower()


def test_task_transport_parses_freeform_text_steps_and_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text fallback and compact callbacks decode only allowlisted task values."""
    category_id = uuid4()
    draft_id = uuid4()

    assert _parse_step_value(TaskDraftStep.TASK_KIND, " GROUP ") is TaskKind.GROUP
    assert _parse_step_value(TaskDraftStep.CATEGORY, str(category_id)) == category_id
    assert _parse_step_value(TaskDraftStep.TIME_SIZE, "m") is TaskTimeSize.M
    assert _parse_step_value(TaskDraftStep.REWARD, "7") == 7
    assert _parse_step_value(TaskDraftStep.TITLE, "  title  ") == "title"
    assert _parse_step_value(TaskDraftStep.INPUT, '{"context":"value"}') == {"context": "value"}
    assert _parse_step_value(TaskDraftStep.INPUT, "plain") == {"_plain_text": "plain"}
    assert _parse_step_value(TaskDraftStep.MATERIALS, '{"url":"https://example.com"}') == {
        "url": "https://example.com"
    }
    assert _parse_step_value(TaskDraftStep.MATERIALS, "notes") == {"text": "notes"}
    assert _parse_step_value(TaskDraftStep.FORMAT, "online") == (TaskFormat.ONLINE, None)
    assert _parse_step_value(TaskDraftStep.FORMAT, "offline Buenos Aires") == (
        TaskFormat.OFFLINE,
        "Buenos Aires",
    )
    assert _parse_step_value(TaskDraftStep.FORMAT, "Buenos Aires") == (
        TaskFormat.OFFLINE,
        "Buenos Aires",
    )
    assert _parse_step_value(TaskDraftStep.SLOTS, "42") == 42
    deadline = cast(
        "datetime.datetime",
        _parse_step_value(TaskDraftStep.DEADLINE, "2026-08-15T12:00:00+00:00"),
    )
    assert deadline.tzinfo

    with pytest.raises(ValueError, match="Expecting"):
        _parse_step_value(TaskDraftStep.MATERIALS, "{")
    monkeypatch.setattr(task_transport.json, "loads", lambda _value: [])
    with pytest.raises(TaskError, match="object"):
        _parse_step_value(TaskDraftStep.INPUT, "{}")
    with pytest.raises(TaskError, match="object"):
        _parse_step_value(TaskDraftStep.MATERIALS, "{}")
    with pytest.raises(TaskError):
        _parse_publish_callback("wrong")
    with pytest.raises(TaskError):
        _parse_publish_callback("task:pub:no-separator")
    with pytest.raises(TaskError):
        _parse_edit_callback("task:edit:bad")
    with pytest.raises(TaskError):
        _parse_edit_callback(f"task:edit:{_encode_uuid(draft_id)}:1:bad")
    with pytest.raises(TaskError):
        _parse_approval_callback("task:approve:bad")
    with pytest.raises(TaskError):
        _parse_approval_callback("task:approve:no-separator")
    with pytest.raises(TaskError):
        _parse_step_value(TaskDraftStep.PUBLISHED, "ignored")

    publish = f"task:pub:{draft_id.hex}:3"
    assert _parse_publish_callback(publish) == (draft_id, 3)
    edit = _edit_callback(draft_id, 4, TaskDraftStep.DESCRIPTION)
    assert _parse_edit_callback(edit) == (draft_id, 4, TaskDraftStep.DESCRIPTION)
    approval = f"task:approve:{draft_id.hex}:5"
    assert _parse_approval_callback(approval) == (draft_id, 5)


def test_task_transport_builds_task_action_keyboards_and_summaries() -> None:
    """Creator controls stay compact across free, pending, and closed cards."""
    task_id = uuid4()
    creator_id = uuid4()
    assignee_id = uuid4()
    task = cast(
        "PublishedTask",
        SimpleNamespace(
            id=task_id,
            creator_id=creator_id,
            title="Group task",
            status=TaskStatus.PUBLISHED,
            performer_slots=3,
        ),
    )
    assignee = OwnedTaskAssignee(assignee_id, "Performer", "accepted")
    card = OwnedTaskCard(task=task, assignees=(assignee,), cancellation_status=None)

    summary = owned_task_summary(card)
    keyboard = owned_task_keyboard(card)
    cancellation = task_cancellation_keyboard(task)
    confirmation = _cancel_confirmation_keyboard(task_id, negotiated=True)

    assert "Взято: 1/3" in summary
    assert "Performer" in summary
    assert keyboard.inline_keyboard[1][0].text == "Завершить набор"
    assert cancellation is not None
    assert cancellation.inline_keyboard[0][0].text == "Завершить набор"
    assert confirmation.inline_keyboard[0][0].text == "Завершить набор"

    pending = OwnedTaskCard(task=task, assignees=(), cancellation_status="pending")
    assert "Свободно" in owned_task_summary(pending)
    assert len(owned_task_keyboard(pending).inline_keyboard) == 1

    closed_task = cast(
        "PublishedTask",
        SimpleNamespace(
            id=uuid4(),
            creator_id=creator_id,
            title="Closed task",
            status=TaskStatus.CLOSED_FOR_NEW_PERFORMERS,
            performer_slots=2,
        ),
    )
    assert "closed_for_new_performers" in owned_task_summary(
        OwnedTaskCard(task=closed_task, assignees=(), cancellation_status=None)
    )


def test_task_transport_builds_approval_and_cancellation_callbacks() -> None:
    """Compact UUID encoding round-trips through public helper callbacks."""
    draft_id = uuid4()
    response_id = uuid4()
    request = CommunityPublicationRequest(
        draft_id=draft_id,
        revision=2,
        creator_display_name="Creator",
        reviewer_display_name="Reviewer",
        template_name="Community task",
        requested_at=datetime.datetime(2026, 8, 15, tzinfo=datetime.UTC),
    )

    approval = community_publication_approval_keyboard((request,))
    assert approval is not None
    callback = approval.inline_keyboard[0][0].callback_data
    assert callback is not None
    assert _parse_approval_callback(callback) == (draft_id, 2)
    assert community_publication_approval_keyboard(()) is None

    replacement = reviewer_replacement_callback(draft_id)
    assert _decode_uuid(replacement.removeprefix("task:rr:")) == draft_id
    accepted = cancellation_response_callback(str(response_id), accepted=True)
    declined = cancellation_response_callback(str(response_id), accepted=False)
    assert _decode_uuid(accepted.removeprefix("task:cancel:yes:")) == response_id
    assert _decode_uuid(declined.removeprefix("task:cancel:nope:")) == response_id


def test_task_transport_renders_freeform_prompt_texts() -> None:
    """Draft prompts explain current choices while keeping buttons compact."""
    draft = _DeniedTaskService().draft
    freeform = replace(draft, template_id=None, task_kind=TaskKind.GROUP)

    assert "тип задания" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.TASK_KIND))
    assert "категорию" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.CATEGORY))
    assert "примерное время" in _draft_prompt(
        replace(freeform, current_step=TaskDraftStep.TIME_SIZE)
    )
    assert "Лимит: 80" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.TITLE))
    assert "Лимит: 1200" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.DESCRIPTION))
    assert "Лимит: 700" in _draft_prompt(
        replace(freeform, current_step=TaskDraftStep.COMPLETION_CRITERIA)
    )
    assert "обычным сообщением" in _draft_prompt(replace(draft, current_step=TaskDraftStep.INPUT))
    assert "срок" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.DEADLINE))
    assert "онлайн" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.FORMAT))
    assert "материалы" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.MATERIALS))
    assert "Количество исполнителей: 2" in _draft_prompt(
        replace(freeform, current_step=TaskDraftStep.SLOTS)
    )
    assert "предпросмотр" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.PREVIEW))
    assert "опубликован" in _draft_prompt(replace(freeform, current_step=TaskDraftStep.PUBLISHED))

    assert "награду" in _reward_prompt(replace(freeform, time_size=None))
    assert "2, 3, 4" in _reward_prompt(replace(freeform, time_size=TaskTimeSize.S))
    assert "больше 10" in _reward_prompt(replace(freeform, time_size=TaskTimeSize.XL))

    slot_draft = replace(
        freeform,
        current_step=TaskDraftStep.SLOTS,
        performer_slots=2,
        revision=17,
    )
    assert "Количество исполнителей: 2" in _draft_prompt(slot_draft)
    buttons = [button for row in _slot_counter_rows(slot_draft) for button in row]
    assert [button.text for button in buttons] == [
        "−5",  # noqa: RUF001
        "−1",  # noqa: RUF001
        "+1",
        "+5",
        "Готово",
    ]
    encoded_draft_id = _encode_uuid(slot_draft.id)
    assert [button.callback_data for button in buttons] == [
        f"task:step:slots:adjust:{encoded_draft_id}:17:-5",
        f"task:step:slots:adjust:{encoded_draft_id}:17:-1",
        f"task:step:slots:adjust:{encoded_draft_id}:17:1",
        f"task:step:slots:adjust:{encoded_draft_id}:17:5",
        f"task:step:slots:confirm:{encoded_draft_id}:17",
    ]
    for button in buttons:
        assert button.callback_data is not None
        assert len(button.callback_data.encode()) <= 64

    category = TaskCategoryOption(
        id=uuid4(),
        code="other",
        name="Other",
        description="Fallback category",
        icon="🧩",
        visibility="public",
    )
    category_prompt = _category_prompt((category,))
    assert "Выберите категорию" in category_prompt
    assert "🧩 Other" in category_prompt
    assert "Fallback category" in category_prompt
