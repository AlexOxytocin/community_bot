"""Telegram routes for persistent member task creation and cancellation."""

from __future__ import annotations

import base64
import datetime
import json
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from community_bot.application.tasks import AdvanceDraftCommand, PublishTaskCommand
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import StaleTaskDraftError, TaskDraftStep, TaskError
from community_bot.transport.telegram.task_card import preview_task_card

if TYPE_CHECKING:
    from community_bot.application.tasks import TaskDraft, TaskPreview, TaskService

_CALLBACK_PREFIX = "task:pub:"
_REVIEWER_PREFIX = "task:reviewer:"
_STEP_PREFIX = "task:step:"
_REPLACE_REVIEWER_PREFIX = "task:rr:"
_SELECT_REVIEWER_PREFIX = "task:rs:"
_CALLBACK_LIMIT = 64


def build_task_router(
    service: TaskService,
    *,
    include_text_fallback: bool = True,
) -> Router:
    """Build persistent task creation commands and callbacks."""
    router = Router(name="tasks")

    async def handle_create(message: Message, event_update: Update) -> None:
        if not await _require_private_message(message):
            return
        if message.from_user is None:
            return
        try:
            tail = _command_tail(message.text)
            template_id = None if not tail else UUID(tail)
            draft = await service.start(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                template_id=template_id,
            )
            if draft is None:
                await message.answer("Активного черновика нет. Выберите шаблон в каталоге.")
            else:
                await _send_draft_prompt(message, draft)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_resume(message: Message, event_update: Update) -> None:
        if not await _require_private_message(message):
            return
        if message.from_user is None:
            return
        try:
            draft = await service.resume(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                draft_id=UUID(_required_tail(message.text)),
            )
            await _send_draft_prompt(message, draft)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_answer(message: Message, event_update: Update) -> None:
        if not await _require_private_message(message):
            return
        if not await handle_task_text(service, message, event_update):
            raise SkipHandler

    async def handle_preview(message: Message, event_update: Update) -> None:
        if not await _require_private_message(message):
            return
        if message.from_user is None:
            return
        try:
            draft = await service.current(actor_telegram_user_id=message.from_user.id)
            if draft is None:
                raise TaskError("Task draft does not exist.")
            preview = await service.preview(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                draft_id=draft.id,
                expected_revision=draft.revision,
            )
            await _send_preview(message, preview)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_publish(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            draft_id, revision = _parse_publish_callback(str(callback.data))
            task = await service.publish(
                PublishTaskCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    draft_id,
                    revision,
                )
            )
            await callback.answer("Задание опубликовано.")
            if isinstance(callback.message, Message):
                await callback.message.answer(f"Задание опубликовано: {task.title}")
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_reviewer(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            reviewer_id = UUID(hex=str(callback.data).removeprefix(_REVIEWER_PREFIX))
            await service.select_community_reviewer(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                reviewer_id=reviewer_id,
            )
            await callback.answer("Проверяющий выбран.")
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Опишите задание обычным сообщением. Для отмены — /cancel."
                )
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_step(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            action = str(callback.data).removeprefix(_STEP_PREFIX)
            draft = await service.current(actor_telegram_user_id=callback.from_user.id)
            if draft is None:
                raise TaskError("Task draft does not exist.")
            if action.startswith("days:"):
                days = int(action.removeprefix("days:"))
                value: object = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=days)
            elif action == "online":
                value = (TaskFormat.ONLINE, None)
            elif action == "materials:none":
                value = {"text": "Дополнительные материалы не требуются"}
            elif action.startswith("slots:"):
                value = int(action.removeprefix("slots:"))
            elif action == "preview":
                preview = await service.preview(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=callback.from_user.id,
                    draft_id=draft.id,
                    expected_revision=draft.revision,
                )
                await callback.answer()
                if isinstance(callback.message, Message):
                    await _send_preview(callback.message, preview)
                return
            else:
                raise TaskError("Task step callback is invalid.")
            updated = await service.advance(
                AdvanceDraftCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    draft.id,
                    draft.current_step,
                    draft.revision,
                    value,
                )
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await _send_draft_prompt(callback.message, updated)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def replace_reviewer(callback: CallbackQuery) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            task_id = _decode_uuid(str(callback.data).removeprefix(_REPLACE_REVIEWER_PREFIX))
            reviewers = await service.community_reviewers(callback.from_user.id)
            if not reviewers:
                raise TaskError("No independent community reviewer is available.")
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Выберите нового независимого проверяющего:",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=item.display_name,
                                    callback_data=(
                                        f"{_SELECT_REVIEWER_PREFIX}{_encode_uuid(task_id)}:"
                                        f"{_encode_uuid(item.id)}"
                                    ),
                                )
                            ]
                            for item in reviewers
                        ]
                    ),
                )
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def select_replacement(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            raw_task, raw_reviewer = (
                str(callback.data).removeprefix(_SELECT_REVIEWER_PREFIX).split(":", 1)
            )
            await service.replace_community_reviewer(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                task_id=_decode_uuid(raw_task),
                reviewer_id=_decode_uuid(raw_reviewer),
            )
            await callback.answer("Проверяющий заменён.")
            if isinstance(callback.message, Message):
                await callback.message.answer("Результат снова доступен для проверки.")
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_owned(message: Message) -> None:
        if not await _require_private_message(message):
            return
        if message.from_user is None:
            return
        try:
            tasks = await service.list_owned(actor_telegram_user_id=message.from_user.id)
            if not tasks:
                await message.answer("У вас пока нет опубликованных заданий.")
                return
            await message.answer(
                "\n\n".join(
                    f"{task.title}\n{task.status.value} · {task.reserved_credit_total} кредита"
                    for task in tasks
                )
            )
        except (TaskError, PermissionError, LookupError) as error:
            await message.answer(_friendly_error(error))

    async def handle_cancel(message: Message, event_update: Update) -> None:
        if not await _require_private_message(message):
            return
        if message.from_user is None:
            return
        try:
            reference_id = UUID(_required_tail(message.text))
            try:
                await service.cancel_draft(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=message.from_user.id,
                    draft_id=reference_id,
                )
                await message.answer("Черновик удалён.")
            except (LookupError, TaskError):
                task = await service.cancel(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=message.from_user.id,
                    task_id=reference_id,
                )
                await message.answer(f"Задание отменено: {task.title}")
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    router.message.register(handle_create, Command("task_create"))
    router.message.register(handle_resume, Command("task_resume"))
    router.message.register(handle_preview, Command("task_preview"))
    router.message.register(handle_owned, Command("my_tasks"))
    router.message.register(handle_cancel, Command("task_cancel"))
    router.callback_query.register(handle_publish, F.data.startswith(_CALLBACK_PREFIX))
    router.callback_query.register(handle_reviewer, F.data.startswith(_REVIEWER_PREFIX))
    router.callback_query.register(handle_step, F.data.startswith(_STEP_PREFIX))
    router.callback_query.register(
        replace_reviewer,
        F.data.startswith(_REPLACE_REVIEWER_PREFIX),
    )
    router.callback_query.register(
        select_replacement,
        F.data.startswith(_SELECT_REVIEWER_PREFIX),
    )
    if include_text_fallback:
        router.message.register(handle_answer, F.text & ~F.text.startswith("/"))
    return router


async def handle_task_text(service: TaskService, message: Message, event_update: Update) -> bool:
    """Handle a task-draft answer, or return false when no task draft owns the text."""
    if message.from_user is None or message.text is None:
        return False
    if not await _require_private_message(message):
        return True
    try:
        draft = await service.current(actor_telegram_user_id=message.from_user.id)
    except (PermissionError, LookupError):
        return False
    if draft is None:
        return False
    try:
        value = _parse_step_value(draft.current_step, message.text)
        updated = await service.advance(
            AdvanceDraftCommand(
                event_update.update_id,
                message.from_user.id,
                draft.id,
                draft.current_step,
                draft.revision,
                value,
            )
        )
        await _send_draft_prompt(message, updated)
    except (TaskError, PermissionError, LookupError, ValueError) as error:
        await message.answer(_friendly_error(error))
    return True


async def _send_preview(message: Message, preview: TaskPreview) -> None:
    callback_data = f"{_CALLBACK_PREFIX}{preview.draft.id.hex}:{preview.draft.revision}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task publish callback exceeds the Telegram limit.")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Опубликовать", callback_data=callback_data)]]
    )
    await message.answer(
        preview_task_card(preview),
        parse_mode=None,
        reply_markup=markup,
    )


def _parse_step_value(step: TaskDraftStep, text: str) -> object:  # noqa: PLR0911
    clean = text.strip()
    if step is TaskDraftStep.INPUT:
        if clean.startswith("{"):
            value = json.loads(clean)
            if not isinstance(value, dict):
                raise TaskError("Task JSON answer must be an object.")
            return value
        return {"_plain_text": clean}
    if step is TaskDraftStep.DEADLINE:
        return datetime.datetime.fromisoformat(clean)
    if step is TaskDraftStep.MATERIALS:
        if clean.startswith("{"):
            value = json.loads(clean)
            if not isinstance(value, dict):
                raise TaskError("Task JSON answer must be an object.")
            return value
        return {"text": clean}
    if step is TaskDraftStep.FORMAT:
        format_value, separator, city = clean.partition(" ")
        if format_value in {TaskFormat.ONLINE.value, TaskFormat.OFFLINE.value}:
            return TaskFormat(format_value), city.strip() if separator else None
        return TaskFormat.OFFLINE, clean
    if step is TaskDraftStep.SLOTS:
        return int(clean)
    raise StaleTaskDraftError("Task draft is not waiting for a text answer.")


def _draft_prompt(draft: TaskDraft) -> str:
    prompts = {
        TaskDraftStep.INPUT: "Опишите задание обычным сообщением.",
        TaskDraftStep.DEADLINE: "Выберите срок выполнения.",
        TaskDraftStep.FORMAT: "Выберите онлайн или отправьте город для очного задания.",
        TaskDraftStep.MATERIALS: "Отправьте материалы или нажмите «Не нужны».",
        TaskDraftStep.SLOTS: "Выберите число исполнителей.",
        TaskDraftStep.PREVIEW: "Черновик готов. Откройте предпросмотр.",
        TaskDraftStep.PUBLISHED: "Этот черновик уже опубликован.",
    }
    return prompts[draft.current_step]


async def _send_draft_prompt(message: Message, draft: TaskDraft) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    if draft.current_step is TaskDraftStep.DEADLINE:
        rows = [
            [
                InlineKeyboardButton(text="1 день", callback_data=f"{_STEP_PREFIX}days:1"),
                InlineKeyboardButton(text="3 дня", callback_data=f"{_STEP_PREFIX}days:3"),
                InlineKeyboardButton(text="7 дней", callback_data=f"{_STEP_PREFIX}days:7"),
            ]
        ]
    elif draft.current_step is TaskDraftStep.FORMAT:
        rows = [[InlineKeyboardButton(text="Онлайн", callback_data=f"{_STEP_PREFIX}online")]]
    elif draft.current_step is TaskDraftStep.MATERIALS:
        rows = [
            [
                InlineKeyboardButton(
                    text="Не нужны",
                    callback_data=f"{_STEP_PREFIX}materials:none",
                )
            ]
        ]
    elif draft.current_step is TaskDraftStep.SLOTS:
        if draft.performer_slots is None:
            rows = [
                [
                    InlineKeyboardButton(
                        text=str(value),
                        callback_data=f"{_STEP_PREFIX}slots:{value}",
                    )
                    for value in range(1, 4)
                ]
            ]
        else:
            rows = [
                [
                    InlineKeyboardButton(
                        text="Предпросмотр",
                        callback_data=f"{_STEP_PREFIX}preview",
                    )
                ]
            ]
    elif draft.current_step is TaskDraftStep.PREVIEW:
        rows = [
            [
                InlineKeyboardButton(
                    text="Предпросмотр",
                    callback_data=f"{_STEP_PREFIX}preview",
                )
            ]
        ]
    await message.answer(
        _draft_prompt(draft),
        reply_markup=None if not rows else InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _parse_publish_callback(value: str) -> tuple[UUID, int]:
    if not value.startswith(_CALLBACK_PREFIX):
        raise TaskError("Task publish callback is invalid.")
    payload = value.removeprefix(_CALLBACK_PREFIX)
    draft_hex, separator, revision = payload.partition(":")
    if not separator:
        raise TaskError("Task publish callback is invalid.")
    return UUID(hex=draft_hex), int(revision)


def reviewer_replacement_callback(task_id: UUID) -> str:
    """Build a compact callback for the visible reviewer-replacement action."""
    return f"{_REPLACE_REVIEWER_PREFIX}{_encode_uuid(task_id)}"


def _encode_uuid(value: UUID) -> str:
    return base64.urlsafe_b64encode(value.bytes).decode().rstrip("=")


def _decode_uuid(value: str) -> UUID:
    return UUID(bytes=base64.urlsafe_b64decode(f"{value}=="))


def _command_tail(text: str | None) -> str:
    if not text:
        return ""
    _command, separator, tail = text.partition(" ")
    return tail.strip() if separator else ""


def _required_tail(text: str | None) -> str:
    value = _command_tail(text)
    if not value:
        raise TaskError("Task command argument is required.")
    return value


def _friendly_error(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "Это действие вам недоступно."
    if isinstance(error, StaleTaskDraftError):
        return "Черновик уже изменился. Откройте его заново."
    return "Не удалось обработать задание. Проверьте данные и попробуйте снова."


async def _require_private_message(message: Message) -> bool:
    if message.chat.type == "private":
        return True
    await message.answer("Работа с заданиями доступна только в личном чате с ботом.")
    return False


async def _require_private_callback(callback: CallbackQuery) -> bool:
    if isinstance(callback.message, Message) and callback.message.chat.type == "private":
        return True
    await callback.answer(
        "Работа с заданиями доступна только в личном чате с ботом.", show_alert=True
    )
    return False
