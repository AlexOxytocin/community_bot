"""Telegram routes for persistent member task creation and cancellation."""

from __future__ import annotations

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

if TYPE_CHECKING:
    from community_bot.application.tasks import TaskDraft, TaskPreview, TaskService

_CALLBACK_PREFIX = "task:pub:"
_CALLBACK_LIMIT = 64


def build_task_router(
    service: TaskService,
    *,
    include_text_fallback: bool = True,
) -> Router:
    """Build persistent task creation commands and callbacks."""
    router = Router(name="tasks")

    async def handle_create(message: Message, event_update: Update) -> None:
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
                await message.answer(_draft_prompt(draft))
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_resume(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            draft = await service.resume(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                draft_id=UUID(_required_tail(message.text)),
            )
            await message.answer(_draft_prompt(draft))
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await message.answer(_friendly_error(error))

    async def handle_answer(message: Message, event_update: Update) -> None:
        if not await handle_task_text(service, message, event_update):
            raise SkipHandler

    async def handle_preview(message: Message, event_update: Update) -> None:
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

    async def handle_owned(message: Message) -> None:
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
    if include_text_fallback:
        router.message.register(handle_answer, F.text & ~F.text.startswith("/"))
    return router


async def handle_task_text(service: TaskService, message: Message, event_update: Update) -> bool:
    """Handle a task-draft answer, or return false when no task draft owns the text."""
    if message.from_user is None or message.text is None:
        return False
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
        await message.answer(_draft_prompt(updated))
    except (TaskError, PermissionError, LookupError, ValueError, json.JSONDecodeError) as error:
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
        f"{preview.template_name}\n"
        f"{preview.credit_reward_per_performer} кредита × "
        f"{preview.draft.performer_slots} = {preview.reserved_credit_total}\n"
        f"Срок: {preview.draft.deadline_at}",
        reply_markup=markup,
    )


def _parse_step_value(step: TaskDraftStep, text: str) -> object:
    if step in {TaskDraftStep.INPUT, TaskDraftStep.MATERIALS}:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise TaskError("Task JSON answer must be an object.")
        return value
    if step is TaskDraftStep.DEADLINE:
        return datetime.datetime.fromisoformat(text)
    if step is TaskDraftStep.FORMAT:
        format_value, _, city = text.partition(" ")
        return TaskFormat(format_value), city.strip() or None
    if step is TaskDraftStep.SLOTS:
        return int(text)
    raise StaleTaskDraftError("Task draft is not waiting for a text answer.")


def _draft_prompt(draft: TaskDraft) -> str:
    prompts = {
        TaskDraftStep.INPUT: "Отправьте JSON с данными шаблона.",
        TaskDraftStep.DEADLINE: "Отправьте срок в ISO 8601 с часовым поясом.",
        TaskDraftStep.FORMAT: "Отправьте online или offline и город.",
        TaskDraftStep.MATERIALS: "Отправьте JSON материалов: text и/или url.",
        TaskDraftStep.SLOTS: "Отправьте число исполнителей, затем /task_preview.",
        TaskDraftStep.PREVIEW: "Черновик готов. Используйте /task_preview.",
        TaskDraftStep.PUBLISHED: "Этот черновик уже опубликован.",
    }
    return prompts[draft.current_step]


def _parse_publish_callback(value: str) -> tuple[UUID, int]:
    if not value.startswith(_CALLBACK_PREFIX):
        raise TaskError("Task publish callback is invalid.")
    payload = value.removeprefix(_CALLBACK_PREFIX)
    draft_hex, separator, revision = payload.partition(":")
    if not separator:
        raise TaskError("Task publish callback is invalid.")
    return UUID(hex=draft_hex), int(revision)


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
