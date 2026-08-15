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

from community_bot.application.tasks import (
    AdvanceDraftCommand,
    CommunityPublicationRequest,
    OwnedTaskCard,
    PublishTaskCommand,
    TaskDraft,
)
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import (
    COMPLETION_CRITERIA_LIMIT,
    DESCRIPTION_LIMIT,
    TASK_TIME_SIZE_SPECS,
    TITLE_LIMIT,
    StaleTaskDraftError,
    TaskDraftStep,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
    task_time_size_label,
)
from community_bot.transport.telegram.task_card import preview_task_card, published_task_card

if TYPE_CHECKING:
    from community_bot.application.tasks import (
        PublishedTask,
        TaskCategoryOption,
        TaskPreview,
        TaskService,
    )

_CALLBACK_PREFIX = "task:pub:"
_APPROVE_PREFIX = "task:approve:"
_REVIEWER_PREFIX = "task:reviewer:"
_STEP_PREFIX = "task:step:"
_EDIT_PREFIX = "task:edit:"
_REPLACE_REVIEWER_PREFIX = "task:rr:"
_SELECT_REVIEWER_PREFIX = "task:rs:"
_CANCEL_REQUEST_PREFIX = "task:cancel:ask:"
_CANCEL_CONFIRM_PREFIX = "task:cancel:do:"
_CANCEL_NEGOTIATE_PREFIX = "task:cancel:req:"
_CANCEL_ACCEPT_PREFIX = "task:cancel:yes:"
_CANCEL_DECLINE_PREFIX = "task:cancel:nope:"
_CANCEL_DISMISS = "task:cancel:no"
_VIEW_OPEN_PREFIX = "task:view:open:"
_VIEW_CLOSE_PREFIX = "task:view:close:"
_CALLBACK_LIMIT = 64
_PREVIEW_EDIT_ROW_SIZE = 2
_SINGULAR_CREDIT_TEEN = 11


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
                await message.answer("Не удалось открыть черновик задания.")
            else:
                await _send_draft_prompt(
                    message,
                    draft,
                    service=service,
                    actor_telegram_user_id=message.from_user.id,
                )
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
            await _send_draft_prompt(
                message,
                draft,
                service=service,
                actor_telegram_user_id=message.from_user.id,
            )
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
            result = await service.publish(
                PublishTaskCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    draft_id,
                    revision,
                )
            )
            if isinstance(result, TaskDraft):
                await callback.answer("Запрос отправлен.")
                if isinstance(callback.message, Message):
                    await callback.message.answer(
                        "Задание отправлено суперадминистратору на подтверждение."
                    )
                return
            await callback.answer("Задание опубликовано.")
            if isinstance(callback.message, Message):
                await callback.message.answer(f"Задание опубликовано: {result.title}")
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_community_approval(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            draft_id, revision = _parse_approval_callback(str(callback.data))
            task = await service.confirm_community_publication(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                draft_id=draft_id,
                expected_revision=revision,
            )
            await callback.answer("Задание опубликовано.")
            if isinstance(callback.message, Message):
                await callback.message.answer(f"Подтверждено и опубликовано: {task.title}")
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

    async def handle_step(  # noqa: PLR0912
        callback: CallbackQuery,
        event_update: Update,
    ) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            action = str(callback.data).removeprefix(_STEP_PREFIX)
            draft = await service.current(actor_telegram_user_id=callback.from_user.id)
            if draft is None:
                raise TaskError("Task draft does not exist.")
            if action.startswith("kind:"):
                value = TaskKind(action.removeprefix("kind:"))
            elif action.startswith("cat:"):
                value = _decode_uuid(action.removeprefix("cat:"))
            elif action.startswith("size:"):
                value = TaskTimeSize(action.removeprefix("size:"))
            elif action.startswith("reward:"):
                value = int(action.removeprefix("reward:"))
            elif action.startswith("days:"):
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
                await _send_draft_prompt(
                    callback.message,
                    updated,
                    service=service,
                    actor_telegram_user_id=callback.from_user.id,
                )
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_friendly_error(error), show_alert=True)

    async def handle_edit(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            draft_id, revision, step = _parse_edit_callback(str(callback.data))
            updated = await service.edit_draft_step(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                draft_id=draft_id,
                expected_revision=revision,
                step=step,
            )
            await callback.answer("Можно изменить пункт.")
            if isinstance(callback.message, Message):
                await _send_draft_prompt(
                    callback.message,
                    updated,
                    service=service,
                    actor_telegram_user_id=callback.from_user.id,
                )
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
            cards = await service.list_owned_cards(actor_telegram_user_id=message.from_user.id)
            if not cards:
                await message.answer("У вас пока нет опубликованных заданий.")
                return
            for card in cards:
                await message.answer(
                    owned_task_summary(card),
                    parse_mode=None,
                    reply_markup=owned_task_keyboard(card),
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

    async def request_cancel(callback: CallbackQuery) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            task_id = _decode_uuid(str(callback.data).removeprefix(_CANCEL_REQUEST_PREFIX))
            card = await service.owned_card(
                actor_telegram_user_id=callback.from_user.id, task_id=task_id
            )
            task = card.task
            if task.creator_id is None:
                raise PermissionError("Only the task creator can cancel this task.")
            if task.status is not TaskStatus.PUBLISHED:
                raise TaskError("Task cannot be cancelled from its current state.")
            if card.assignees:
                text = (
                    f"Завершить набор для «{task.title}»?\n"
                    "Новые исполнители больше не смогут взять задание. Свободный резерв "
                    "вернётся сразу, а тем, кто уже взял задание, уйдёт запрос на отмену."
                )
                markup = _cancel_confirmation_keyboard(task.id, negotiated=True)
            else:
                text = (
                    f"Отменить «{task.title}»?\n"
                    "Задание исчезнет из каталога, а "
                    f"{_credits(task.reserved_credit_total)} вернутся в доступный баланс."
                )
                markup = _cancel_confirmation_keyboard(task.id)
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(text, reply_markup=markup)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_cancel_error(error), show_alert=True)

    async def confirm_cancel(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            task_id = _decode_uuid(str(callback.data).removeprefix(_CANCEL_CONFIRM_PREFIX))
            task = await service.cancel(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                task_id=task_id,
            )
            await callback.answer("Задание отменено.")
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    f"Задание «{task.title}» отменено. "
                    f"{_credits(task.reserved_credit_total)} возвращены в доступный баланс."
                )
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_cancel_error(error), show_alert=True)

    async def confirm_negotiated_cancel(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        try:
            task_id = _decode_uuid(str(callback.data).removeprefix(_CANCEL_NEGOTIATE_PREFIX))
            outcome = await service.request_cancellation(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                task_id=task_id,
            )
            if outcome.status == "cancelled":
                answer = "Задание отменено."
                message = (
                    f"Задание «{outcome.task.title}» отменено. "
                    f"{_credits(outcome.task.reserved_credit_total)} возвращены в доступный баланс."
                )
            elif outcome.status == "closed":
                answer = "Набор завершён."
                message = (
                    f"Набор для «{outcome.task.title}» завершён. "
                    "Новые исполнители больше не смогут взять задание."
                )
            else:
                answer = "Набор завершён."
                message = (
                    f"Набор для «{outcome.task.title}» завершён. "
                    "Исполнителям отправлен запрос на отмену, но они могут сдать результат."
                )
            await callback.answer(answer)
            if isinstance(callback.message, Message):
                await callback.message.answer(message)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_cancel_error(error), show_alert=True)

    async def respond_cancel(callback: CallbackQuery, event_update: Update) -> None:
        if not await _require_private_callback(callback):
            return
        data = str(callback.data)
        accepted = data.startswith(_CANCEL_ACCEPT_PREFIX)
        prefix = _CANCEL_ACCEPT_PREFIX if accepted else _CANCEL_DECLINE_PREFIX
        try:
            response_id = _decode_uuid(data.removeprefix(prefix))
            outcome = await service.respond_cancellation(
                update_id=event_update.update_id,
                actor_telegram_user_id=callback.from_user.id,
                response_id=response_id,
                accepted=accepted,
            )
            if outcome.status == "cancelled":
                message = "Отмена подтверждена. Задание отменено."
            elif outcome.status == "declined":
                message = "Понятно. Можно сдать результат автору обычным способом."
            elif outcome.status == "obsolete":
                message = _obsolete_cancellation_message(outcome.reason)
            else:
                message = "Согласие сохранено. Ждём ответы остальных исполнителей."
            await callback.answer(message, show_alert=True)
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_cancellation_response_error(error), show_alert=True)

    async def toggle_owned_card(callback: CallbackQuery) -> None:
        if not await _require_private_callback(callback):
            return
        data = str(callback.data)
        expanded = data.startswith(_VIEW_OPEN_PREFIX)
        prefix = _VIEW_OPEN_PREFIX if expanded else _VIEW_CLOSE_PREFIX
        try:
            task_id = _decode_uuid(data.removeprefix(prefix))
            card = await service.owned_card(
                actor_telegram_user_id=callback.from_user.id, task_id=task_id
            )
            text = (
                f"{published_task_card(card.task)}\n{owned_task_summary(card, include_title=False)}"
                if expanded
                else owned_task_summary(card)
            )
            if isinstance(callback.message, Message):
                await callback.message.edit_text(
                    text,
                    parse_mode=None,
                    reply_markup=owned_task_keyboard(card, expanded=expanded),
                )
            await callback.answer()
        except (TaskError, PermissionError, LookupError, ValueError) as error:
            await callback.answer(_cancel_error(error), show_alert=True)

    async def dismiss_cancel(callback: CallbackQuery) -> None:
        if not await _require_private_callback(callback):
            return
        await callback.answer("Отмена не выполнена.")

    router.message.register(handle_create, Command("task_create"))
    router.message.register(handle_resume, Command("task_resume"))
    router.message.register(handle_preview, Command("task_preview"))
    router.message.register(handle_owned, Command("my_tasks"))
    router.message.register(handle_cancel, Command("task_cancel"))
    router.callback_query.register(request_cancel, F.data.startswith(_CANCEL_REQUEST_PREFIX))
    router.callback_query.register(confirm_cancel, F.data.startswith(_CANCEL_CONFIRM_PREFIX))
    router.callback_query.register(
        confirm_negotiated_cancel, F.data.startswith(_CANCEL_NEGOTIATE_PREFIX)
    )
    router.callback_query.register(respond_cancel, F.data.startswith(_CANCEL_ACCEPT_PREFIX))
    router.callback_query.register(respond_cancel, F.data.startswith(_CANCEL_DECLINE_PREFIX))
    router.callback_query.register(toggle_owned_card, F.data.startswith(_VIEW_OPEN_PREFIX))
    router.callback_query.register(toggle_owned_card, F.data.startswith(_VIEW_CLOSE_PREFIX))
    router.callback_query.register(dismiss_cancel, F.data == _CANCEL_DISMISS)
    router.callback_query.register(handle_community_approval, F.data.startswith(_APPROVE_PREFIX))
    router.callback_query.register(handle_publish, F.data.startswith(_CALLBACK_PREFIX))
    router.callback_query.register(handle_reviewer, F.data.startswith(_REVIEWER_PREFIX))
    router.callback_query.register(handle_edit, F.data.startswith(_EDIT_PREFIX))
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
        await _send_draft_prompt(
            message,
            updated,
            service=service,
            actor_telegram_user_id=message.from_user.id,
        )
    except (TaskError, PermissionError, LookupError, ValueError) as error:
        await message.answer(_friendly_error(error))
    return True


async def send_task_draft_prompt(
    message: Message,
    draft: TaskDraft,
    *,
    service: TaskService,
    actor_telegram_user_id: int,
) -> None:
    """Render the current task draft prompt for another router."""
    await _send_draft_prompt(
        message,
        draft,
        service=service,
        actor_telegram_user_id=actor_telegram_user_id,
    )


async def _send_preview(message: Message, preview: TaskPreview) -> None:
    callback_data = f"{_CALLBACK_PREFIX}{preview.draft.id.hex}:{preview.draft.revision}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task publish callback exceeds the Telegram limit.")
    rows = _preview_edit_rows(preview.draft)
    rows.append([InlineKeyboardButton(text="Опубликовать", callback_data=callback_data)])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(
        preview_task_card(preview),
        parse_mode=None,
        reply_markup=markup,
    )


_EDIT_STEP_CODES = {
    "tk": TaskDraftStep.TASK_KIND,
    "cat": TaskDraftStep.CATEGORY,
    "ts": TaskDraftStep.TIME_SIZE,
    "sl": TaskDraftStep.SLOTS,
    "rw": TaskDraftStep.REWARD,
    "ti": TaskDraftStep.TITLE,
    "ds": TaskDraftStep.DESCRIPTION,
    "cc": TaskDraftStep.COMPLETION_CRITERIA,
    "in": TaskDraftStep.INPUT,
    "mt": TaskDraftStep.MATERIALS,
    "dl": TaskDraftStep.DEADLINE,
    "fm": TaskDraftStep.FORMAT,
}
_EDIT_CODES_BY_STEP = {step: code for code, step in _EDIT_STEP_CODES.items()}


def _preview_edit_rows(draft: TaskDraft) -> list[list[InlineKeyboardButton]]:
    steps = (
        (
            (TaskDraftStep.INPUT, "Данные"),
            (TaskDraftStep.MATERIALS, "Материалы"),
        )
        if draft.template_id is not None
        else (
            (TaskDraftStep.TASK_KIND, "Тип"),
            (TaskDraftStep.CATEGORY, "Категория"),
            (TaskDraftStep.TIME_SIZE, "Время"),
            (TaskDraftStep.SLOTS, "Исполнители"),
            (TaskDraftStep.REWARD, "Награда"),
            (TaskDraftStep.TITLE, "Название"),
            (TaskDraftStep.DESCRIPTION, "Описание"),
            (TaskDraftStep.COMPLETION_CRITERIA, "Критерии"),
            (TaskDraftStep.MATERIALS, "Материалы"),
        )
    )
    common = ((TaskDraftStep.DEADLINE, "Срок"), (TaskDraftStep.FORMAT, "Формат"))
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for step, label in (*steps, *common):
        if (
            draft.template_id is None
            and step is TaskDraftStep.SLOTS
            and draft.task_kind is TaskKind.SOLO
        ):
            continue
        current.append(
            InlineKeyboardButton(
                text=label,
                callback_data=_edit_callback(draft.id, draft.revision, step),
            )
        )
        if len(current) == _PREVIEW_EDIT_ROW_SIZE:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows


def _edit_callback(draft_id: UUID, revision: int, step: TaskDraftStep) -> str:
    code = _EDIT_CODES_BY_STEP[step]
    callback_data = f"{_EDIT_PREFIX}{_encode_uuid(draft_id)}:{revision}:{code}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task edit callback exceeds the Telegram limit.")
    return callback_data


def _parse_step_value(step: TaskDraftStep, text: str) -> object:  # noqa: PLR0911, PLR0912
    clean = text.strip()
    if step is TaskDraftStep.TASK_KIND:
        return TaskKind(clean.lower())
    if step is TaskDraftStep.CATEGORY:
        return UUID(clean)
    if step is TaskDraftStep.TIME_SIZE:
        return TaskTimeSize(clean.lower())
    if step is TaskDraftStep.REWARD:
        return int(clean)
    if step in {
        TaskDraftStep.TITLE,
        TaskDraftStep.DESCRIPTION,
        TaskDraftStep.COMPLETION_CRITERIA,
    }:
        return clean
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


def _category_prompt(categories: tuple[TaskCategoryOption, ...]) -> str:
    lines = [
        "Выберите категорию:",
        *(f"{item.icon} {item.name} — {item.description}".strip() for item in categories),
    ]
    return "\n".join(lines)


def _reward_prompt(draft: TaskDraft) -> str:
    if draft.time_size is None:
        return "Выберите награду за одного исполнителя."
    spec = TASK_TIME_SIZE_SPECS[draft.time_size]
    if spec.reward_options is None:
        return "Укажите награду за одного исполнителя целым числом больше 10."
    values = ", ".join(str(value) for value in spec.reward_options)
    return f"Выберите награду за одного исполнителя: {values} кредитов."


def _draft_prompt(draft: TaskDraft) -> str:
    prompts = {
        TaskDraftStep.TASK_KIND: (
            "Выберите тип задания.\n"
            "Соло — один исполнитель. Групповое — несколько исполнителей, награда считается "
            "за каждого."
        ),
        TaskDraftStep.CATEGORY: "Выберите категорию. Описание категорий ниже.",
        TaskDraftStep.TIME_SIZE: "Выберите примерное время выполнения.",
        TaskDraftStep.REWARD: _reward_prompt(draft),
        TaskDraftStep.TITLE: f"Напишите короткое название задания. Лимит: {TITLE_LIMIT} символов.",
        TaskDraftStep.DESCRIPTION: (
            f"Опишите, что нужно сделать. Лимит: {DESCRIPTION_LIMIT} символов."
        ),
        TaskDraftStep.COMPLETION_CRITERIA: (
            "Напишите критерии приемки: по чему автор поймёт, что работа сдана. "
            f"Лимит: {COMPLETION_CRITERIA_LIMIT} символов."
        ),
        TaskDraftStep.INPUT: "Опишите задание обычным сообщением.",
        TaskDraftStep.DEADLINE: "Выберите срок выполнения.",
        TaskDraftStep.FORMAT: "Выберите онлайн или отправьте город для очного задания.",
        TaskDraftStep.MATERIALS: "Отправьте материалы или нажмите «Не нужны».",
        TaskDraftStep.SLOTS: "Выберите число исполнителей.",
        TaskDraftStep.PREVIEW: "Черновик готов. Откройте предпросмотр.",
        TaskDraftStep.PUBLISHED: "Этот черновик уже опубликован.",
    }
    return prompts[draft.current_step]


async def _send_draft_prompt(  # noqa: PLR0912
    message: Message,
    draft: TaskDraft,
    *,
    service: TaskService | None = None,
    actor_telegram_user_id: int | None = None,
) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    prompt = _draft_prompt(draft)
    if draft.current_step is TaskDraftStep.TASK_KIND:
        rows = [
            [
                InlineKeyboardButton(text="Соло", callback_data=f"{_STEP_PREFIX}kind:solo"),
                InlineKeyboardButton(text="Групповое", callback_data=f"{_STEP_PREFIX}kind:group"),
            ]
        ]
    elif draft.current_step is TaskDraftStep.CATEGORY:
        if service is None or actor_telegram_user_id is None:
            raise TaskError("Task category prompt requires a service.")
        categories = await service.task_categories(actor_telegram_user_id)
        if not categories:
            raise TaskError("No task categories are available.")
        prompt = _category_prompt(categories)
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{item.icon} {item.name}".strip(),
                    callback_data=f"{_STEP_PREFIX}cat:{_encode_uuid(item.id)}",
                )
            ]
            for item in categories
        ]
    elif draft.current_step is TaskDraftStep.TIME_SIZE:
        rows = [
            [
                InlineKeyboardButton(
                    text=task_time_size_label(size),
                    callback_data=f"{_STEP_PREFIX}size:{size.value}",
                )
            ]
            for size in TaskTimeSize
        ]
    elif draft.current_step is TaskDraftStep.REWARD:
        if draft.time_size is not None:
            options = TASK_TIME_SIZE_SPECS[draft.time_size].reward_options
            if options is not None:
                rows = [
                    [
                        InlineKeyboardButton(
                            text=str(value),
                            callback_data=f"{_STEP_PREFIX}reward:{value}",
                        )
                        for value in options
                    ]
                ]
    elif draft.current_step is TaskDraftStep.DEADLINE:
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
        if draft.template_id is None and draft.performer_slots is None:
            rows = [
                [
                    InlineKeyboardButton(
                        text=str(value),
                        callback_data=f"{_STEP_PREFIX}slots:{value}",
                    )
                    for value in (2, 3, 5)
                ]
            ]
        elif draft.performer_slots is None:
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
        prompt,
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


def _parse_edit_callback(value: str) -> tuple[UUID, int, TaskDraftStep]:
    if not value.startswith(_EDIT_PREFIX):
        raise TaskError("Task edit callback is invalid.")
    payload = value.removeprefix(_EDIT_PREFIX)
    raw_id, separator, tail = payload.partition(":")
    if not separator:
        raise TaskError("Task edit callback is invalid.")
    raw_revision, separator, code = tail.partition(":")
    if not separator or code not in _EDIT_STEP_CODES:
        raise TaskError("Task edit callback is invalid.")
    return _decode_uuid(raw_id), int(raw_revision), _EDIT_STEP_CODES[code]


def _parse_approval_callback(value: str) -> tuple[UUID, int]:
    if not value.startswith(_APPROVE_PREFIX):
        raise TaskError("Community approval callback is invalid.")
    payload = value.removeprefix(_APPROVE_PREFIX)
    draft_hex, separator, revision = payload.partition(":")
    if not separator:
        raise TaskError("Community approval callback is invalid.")
    return UUID(hex=draft_hex), int(revision)


def community_publication_approval_keyboard(
    requests: tuple[CommunityPublicationRequest, ...],
) -> InlineKeyboardMarkup | None:
    """Build confirmation buttons for pending community publication requests."""
    rows: list[list[InlineKeyboardButton]] = []
    for item in requests:
        callback_data = f"{_APPROVE_PREFIX}{item.draft_id.hex}:{item.revision}"
        if len(callback_data.encode()) > _CALLBACK_LIMIT:
            raise TaskError("Community approval callback exceeds the Telegram limit.")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Подтвердить: {item.template_name}",
                    callback_data=callback_data,
                )
            ]
        )
    return None if not rows else InlineKeyboardMarkup(inline_keyboard=rows)


def reviewer_replacement_callback(task_id: UUID) -> str:
    """Build a compact callback for the visible reviewer-replacement action."""
    return f"{_REPLACE_REVIEWER_PREFIX}{_encode_uuid(task_id)}"


def task_cancellation_keyboard(task: PublishedTask) -> InlineKeyboardMarkup | None:
    """Expose cancellation only for the creator-owned cancellable task state."""
    if task.creator_id is None or task.status is not TaskStatus.PUBLISHED:
        return None
    callback_data = f"{_CANCEL_REQUEST_PREFIX}{_encode_uuid(task.id)}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task cancellation callback exceeds the Telegram limit.")
    text = "Завершить набор" if task.performer_slots > 1 else "Отменить"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]]
    )


def _cancel_confirmation_keyboard(
    task_id: UUID, *, negotiated: bool = False
) -> InlineKeyboardMarkup:
    prefix = _CANCEL_NEGOTIATE_PREFIX if negotiated else _CANCEL_CONFIRM_PREFIX
    confirm_text = "Завершить набор" if negotiated else "Да, отменить"
    callback_data = f"{prefix}{_encode_uuid(task_id)}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task cancellation callback exceeds the Telegram limit.")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=confirm_text, callback_data=callback_data),
                InlineKeyboardButton(text="Не отменять", callback_data=_CANCEL_DISMISS),
            ]
        ]
    )


def owned_task_summary(card: OwnedTaskCard, *, include_title: bool = True) -> str:
    """Render the stable compact information needed before expansion."""
    lines = [card.task.title] if include_title else []
    if card.assignees:
        lines.append(f"Взято: {len(card.assignees)}/{card.task.performer_slots}")
        lines.append("Исполнитель: " + ", ".join(item.display_name for item in card.assignees))
    else:
        lines.append("Свободно")
    if card.cancellation_status == "pending":
        lines.append("Запрос отмены: ожидает ответа")
    elif card.task.status is not TaskStatus.PUBLISHED:
        lines.append(f"Статус: {card.task.status.value}")
    return "\n".join(lines)


def owned_task_keyboard(card: OwnedTaskCard, *, expanded: bool = False) -> InlineKeyboardMarkup:
    """Build expand/collapse and creator cancellation controls."""
    prefix = _VIEW_CLOSE_PREFIX if expanded else _VIEW_OPEN_PREFIX
    rows = [
        [
            InlineKeyboardButton(
                text="−" if expanded else "+",
                callback_data=f"{prefix}{_encode_uuid(card.task.id)}",
            )
        ]
    ]
    if (
        card.task.creator_id is not None
        and card.task.status is TaskStatus.PUBLISHED
        and card.cancellation_status != "pending"
    ):
        rows.append(
            [
                InlineKeyboardButton(
                    text="Завершить набор" if card.task.performer_slots > 1 else "Отменить",
                    callback_data=f"{_CANCEL_REQUEST_PREFIX}{_encode_uuid(card.task.id)}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _encode_uuid(value: UUID) -> str:
    return base64.urlsafe_b64encode(value.bytes).decode().rstrip("=")


def cancellation_response_callback(response_id: str, *, accepted: bool) -> str:
    """Build a stable allowlisted performer response callback."""
    prefix = _CANCEL_ACCEPT_PREFIX if accepted else _CANCEL_DECLINE_PREFIX
    callback_data = f"{prefix}{_encode_uuid(UUID(response_id))}"
    if len(callback_data.encode()) > _CALLBACK_LIMIT:
        raise TaskError("Task cancellation response callback exceeds the Telegram limit.")
    return callback_data


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


def _cancel_error(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "Отменить задание может только его автор."
    detail = str(error)
    messages = (
        ("assignment history", "Задание уже взял исполнитель, поэтому отменить его нельзя."),
        ("already cancelled", "Это задание уже отменено."),
        ("deadline has passed", "Срок задания уже истёк. Отмена больше недоступна."),
        ("already awaiting", "Запрос отмены уже отправлен исполнителю."),
        ("already declined", "Исполнитель уже отказал в отмене. Задание остаётся активным."),
        ("work has already started", "Исполнитель уже начал работу. Отмена больше недоступна."),
        ("no longer active", "Запрос отмены больше не актуален."),
        ("no longer available", "Запрос отмены больше не актуален."),
        ("current state", "Задание уже завершено или недоступно для отмены."),
    )
    for marker, message in messages:
        if marker in detail:
            return message
    return (
        "Не удалось отменить задание. Откройте «Задания → Мои задания → "
        "Созданные мной → Активные» и попробуйте снова."
    )


def _cancellation_response_error(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "Этот запрос на отмену адресован другому исполнителю."
    detail = str(error)
    if "does not exist" in detail:
        return "Запрос отмены не найден."
    if "no longer active" in detail or "no longer available" in detail:
        return "Запрос отмены больше не актуален."
    return "Не удалось сохранить ответ на отмену. Попробуйте открыть новое уведомление."


def _obsolete_cancellation_message(reason: str | None) -> str:
    messages = {
        "deadline_passed": "Срок задания истёк. Запрос отмены больше не актуален.",
        "deadline_reached": "Срок задания истёк. Запрос отмены больше не актуален.",
        "work_started": "Работа уже началась. Запрос отмены больше не актуален.",
        "assignment_cancelled": (
            "Исполнение задания уже отменено. Запрос автора больше не актуален."
        ),
    }
    return messages.get(reason, "Состояние задания изменилось. Запрос отмены больше не актуален.")


def _credits(value: int) -> str:
    if value % 10 == 1 and value % 100 != _SINGULAR_CREDIT_TEEN:
        suffix = "кредит"
    elif value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        suffix = "кредита"
    else:
        suffix = "кредитов"
    return f"{value} {suffix}"


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
