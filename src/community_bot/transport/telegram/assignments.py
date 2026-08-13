# ruff: noqa: C901, EM101, PLR0915, RUF001, TRY003, TRY004, TRY301
"""Telegram routes for accepting, delivering, and reviewing assignments."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    BeginSubmissionCommand,
    ConfirmSubmissionDraftCommand,
    DecideAssignmentCommand,
    SaveSubmissionDraftCommand,
)
from community_bot.domain.assignments import AssignmentDecision, AssignmentError
from community_bot.transport.telegram.task_card import published_task_card
from community_bot.transport.telegram.tasks import reviewer_replacement_callback

if TYPE_CHECKING:
    from community_bot.application.assignments import AssignmentService
    from community_bot.application.conversations import TextFlow

_ACCEPT_PREFIX = "task:accept:"
_DECIDE_PREFIX = "assign:review:"
_SUBMIT_PREFIX = "assign:submit:"
_ACTION_PREFIX = "as:a:"
_DISPUTE_PREFIX = "as:d:"


def build_assignment_router(service: AssignmentService) -> Router:
    """Build the complete assignment exchange router."""
    router = Router(name="assignments")

    async def accept(callback: CallbackQuery, event_update: Update) -> None:
        try:
            if not await _require_private_callback(callback):
                return
            message = callback.message
            if not isinstance(message, Message):
                return
            task_id = UUID(str(callback.data).removeprefix(_ACCEPT_PREFIX))
            assignment, task = await service.accept_with_task(
                AcceptAssignmentCommand(event_update.update_id, callback.from_user.id, task_id)
            )
            await callback.answer("Задание принято.")
            await message.answer(
                f"{published_task_card(task)}\n\nЗадание принято. Что хотите сделать дальше?",
                parse_mode=None,
                reply_markup=_assignment_actions(assignment.id, assignment.status.value),
            )
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Не удалось принять задание.", show_alert=True)

    async def owned(message: Message) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            await send_assignment_overview(message, service)
        except (AssignmentError, PermissionError, LookupError):
            await message.answer("Не удалось открыть ваши задания.")

    async def cancel(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            raw_id, reason = _two_arguments(message.text)
            assignment = await service.cancel(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                assignment_id=UUID(raw_id),
                reason=reason,
            )
            await message.answer(f"Назначение отменено: {assignment.id}")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await message.answer("Не удалось отменить назначение. Проверьте причину и статус.")

    async def submit(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            draft = await service.begin_submission(
                BeginSubmissionCommand(
                    event_update.update_id,
                    message.from_user.id,
                    UUID(_one_argument(message.text)),
                )
            )
            await message.answer(
                "Черновик результата готов. Отправьте предпросмотр командой "
                f"/assignment_result {draft.id} {draft.revision} {{...}}"
            )
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await message.answer(
                "Не удалось начать отправку результата. Проверьте назначение и срок."
            )

    async def save_preview(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            raw_draft, raw_revision, raw_payload = _three_arguments(message.text)
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise ValueError("Result payload must be an object.")
            draft = await service.save_submission_draft(
                SaveSubmissionDraftCommand(
                    event_update.update_id,
                    message.from_user.id,
                    UUID(raw_draft),
                    int(raw_revision),
                    payload,
                )
            )
            callback_data = f"{_SUBMIT_PREFIX}{draft.id.hex}:{draft.revision}"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Подтвердить результат", callback_data=callback_data
                        )
                    ]
                ]
            )
            await message.answer(
                "Предпросмотр сохранён. Проверьте данные и подтвердите отправку.",
                reply_markup=keyboard,
            )
        except (AssignmentError, PermissionError, LookupError, ValueError, json.JSONDecodeError):
            await message.answer(
                "Не удалось сохранить предпросмотр. Проверьте JSON и версию черновика."
            )

    async def confirm_submit(callback: CallbackQuery, event_update: Update) -> None:
        try:
            if not await _require_private_callback(callback):
                return
            draft_id, revision = _parse_submission(str(callback.data))
            result = await service.confirm_submission_draft(
                ConfirmSubmissionDraftCommand(
                    event_update.update_id, callback.from_user.id, draft_id, revision
                )
            )
            await callback.answer(f"Результат отправлен, версия {result.version}.")
            if isinstance(callback.message, Message):
                await callback.message.answer("Автор получил результат на проверку.")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Не удалось отправить результат.", show_alert=True)

    async def decide(callback: CallbackQuery, event_update: Update) -> None:
        try:
            if not await _require_private_callback(callback):
                return
            assignment_id, decision = _parse_decision(str(callback.data))
            updated = await service.decide(
                DecideAssignmentCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    assignment_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"telegram:{event_update.update_id}:review"),
                    decision,
                )
            )
            await callback.answer(f"Решение сохранено: {updated.status.value}.")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Не удалось применить решение.", show_alert=True)

    async def action(callback: CallbackQuery, event_update: Update) -> None:
        try:
            if not await _require_private_callback(callback):
                return
            action_code, assignment_id = _parse_action(str(callback.data))
            if action_code == "s":
                await service.begin_submission(
                    BeginSubmissionCommand(
                        event_update.update_id,
                        callback.from_user.id,
                        assignment_id,
                    )
                )
                answer = "Опишите результат одним сообщением (не короче 10 символов)."
            elif action_code == "c":
                await service.cancel(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=callback.from_user.id,
                    assignment_id=assignment_id,
                    reason="Отменено исполнителем через Telegram",
                )
                answer = "Выполнение отменено."
            elif action_code == "d":
                await service.begin_dispute(
                    update_id=event_update.update_id,
                    actor_telegram_user_id=callback.from_user.id,
                    assignment_id=assignment_id,
                )
                answer = "Опишите причину спора одним сообщением. Комментарий увидит модерация."
            else:
                raise ValueError("Unknown assignment action.")
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(answer)
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Действие недоступно или уже выполнено.", show_alert=True)

    async def reviews(message: Message) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            cards = await service.review_cards(message.from_user.id)
            if not cards:
                await message.answer("Результатов на проверку сейчас нет.")
                return
            for card in cards:
                summary = card.result_summary or "Результат без краткого описания"
                await message.answer(
                    f"{card.task_title}\nИсполнитель: {card.performer_display_name}\n{summary}",
                    reply_markup=_review_keyboard(card.assignment.id),
                )
        except (AssignmentError, PermissionError, LookupError):
            await message.answer("Результаты на проверку сейчас недоступны.")

    async def dispute(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        if not await _require_private_message(message):
            return
        try:
            raw_id, comment = _two_arguments(message.text)
            updated = await service.dispute(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                assignment_id=UUID(raw_id),
                command_id=uuid.uuid5(
                    uuid.NAMESPACE_URL, f"telegram:{event_update.update_id}:dispute"
                ),
                comment=comment,
            )
            await message.answer(f"Спор открыт: {updated.id}")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await message.answer("Не удалось открыть спор. Проверьте срок и комментарий.")

    router.callback_query.register(accept, F.data.startswith(_ACCEPT_PREFIX))
    router.callback_query.register(action, F.data.startswith(_ACTION_PREFIX))
    router.callback_query.register(decide, F.data.startswith(_DECIDE_PREFIX))
    router.callback_query.register(confirm_submit, F.data.startswith(_SUBMIT_PREFIX))
    router.message.register(owned, Command("my_assignments"))
    router.message.register(reviews, Command("reviews"))
    router.message.register(cancel, Command("assignment_cancel"))
    router.message.register(submit, Command("assignment_submit"))
    router.message.register(save_preview, Command("assignment_result"))
    router.message.register(dispute, Command("assignment_dispute"))
    return router


async def send_assignment_overview(message: Message, service: AssignmentService) -> None:
    """Send performer and reviewer cards through one visible entry point."""
    if message.from_user is None:
        return
    if message.chat.type != "private":
        await message.answer("Задания доступны только в личном чате с ботом.")
        return
    cards = await service.cards(message.from_user.id)
    reviews = await service.review_cards(message.from_user.id)
    if not cards and not reviews:
        await message.answer("У вас пока нет принятых заданий или результатов на проверку.")
        return
    for card in cards:
        await message.answer(
            f"{published_task_card(card.task)}\nСтатус: {_status(card.assignment.status.value)}",
            parse_mode=None,
            reply_markup=_assignment_actions(
                card.assignment.id,
                card.assignment.status.value,
                case_id=card.case_id,
                case_status=card.case_status,
            ),
        )
    for card in reviews:
        summary = card.result_summary or "Результат без краткого описания"
        markup = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Выбрать нового проверяющего",
                            callback_data=reviewer_replacement_callback(card.assignment.task_id),
                        )
                    ]
                ]
            )
            if card.assignment.status.value == "reviewer_required"
            else _review_keyboard(card.assignment.id)
        )
        await message.answer(
            f"На проверку: {card.task_title}\n"
            f"Исполнитель: {card.performer_display_name}\n{summary}",
            reply_markup=markup,
        )


async def handle_assignment_text(
    service: AssignmentService,
    owner: TextFlow,
    message: Message,
    event_update: Update,
) -> bool:
    """Consume text only when the durable owner selects an assignment flow."""
    if message.from_user is None or message.text is None or owner.reference_id is None:
        return False
    if not await _require_private_message(message):
        return True
    text = message.text.strip()
    if owner.flow_type == "assignment_result":
        try:
            draft = await service.save_submission_draft(
                SaveSubmissionDraftCommand(
                    event_update.update_id,
                    message.from_user.id,
                    owner.reference_id,
                    owner.revision,
                    {"summary": text, "findings": [text], "evidence": []},
                )
            )
            await message.answer(
                f"Проверьте результат:\n{text}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Подтвердить результат",
                                callback_data=f"{_SUBMIT_PREFIX}{draft.id.hex}:{draft.revision}",
                            )
                        ]
                    ]
                ),
            )
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await message.answer("Не удалось сохранить результат. Нужен текст от 10 символов.")
        return True
    if owner.flow_type == "assignment_dispute":
        try:
            updated = await service.dispute(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                assignment_id=owner.reference_id,
                command_id=uuid.uuid5(
                    uuid.NAMESPACE_URL, f"telegram:{event_update.update_id}:dispute"
                ),
                comment=text,
            )
            await message.answer(
                "Спор открыт и передан модерации.",
                reply_markup=_assignment_actions(updated.id, updated.status.value),
            )
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await message.answer("Не удалось открыть спор. Проверьте срок и комментарий.")
        return True
    return False


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


def _assignment_actions(
    assignment_id: UUID,
    status: str,
    *,
    case_id: UUID | None = None,
    case_status: str | None = None,
) -> InlineKeyboardMarkup | None:
    buttons: list[list[InlineKeyboardButton]] = []
    if status == "accepted":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Отправить результат",
                    callback_data=f"{_ACTION_PREFIX}s:{assignment_id.hex}",
                ),
                InlineKeyboardButton(
                    text="Отказаться",
                    callback_data=f"{_ACTION_PREFIX}c:{assignment_id.hex}",
                ),
            ]
        )
    elif status == "rejected_pending_dispute":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Открыть спор",
                    callback_data=f"{_ACTION_PREFIX}d:{assignment_id.hex}",
                )
            ]
        )
    if case_id is not None and case_status == "resolved":
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Подать апелляцию",
                    callback_data=f"mod:appeal:{case_id.hex}",
                )
            ]
        )
    return None if not buttons else InlineKeyboardMarkup(inline_keyboard=buttons)


def _review_keyboard(assignment_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять полностью",
                    callback_data=f"{_DECIDE_PREFIX}{assignment_id.hex}:full",
                ),
                InlineKeyboardButton(
                    text="Принять частично",
                    callback_data=f"{_DECIDE_PREFIX}{assignment_id.hex}:partial",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отклонить",
                    callback_data=f"{_DECIDE_PREFIX}{assignment_id.hex}:reject",
                )
            ],
        ]
    )


def _parse_action(value: str) -> tuple[str, UUID]:
    payload = value.removeprefix(_ACTION_PREFIX)
    action, separator, raw_id = payload.partition(":")
    if not separator or action not in {"s", "c", "d"}:
        raise ValueError("Assignment action callback is invalid.")
    return action, UUID(hex=raw_id)


def _status(value: str) -> str:
    return {
        "accepted": "в работе",
        "submitted": "на проверке",
        "rejected_pending_dispute": "отклонено, можно открыть спор",
        "disputed": "спор рассматривается",
        "approved": "выполнено",
        "partially_approved": "выполнено частично",
        "rejected": "отклонено",
        "cancelled": "отменено",
        "no_show": "неявка",
        "reviewer_required": "нужен новый проверяющий",
    }.get(value, value)


def _two_arguments(text: str | None) -> tuple[str, str]:
    if not text:
        raise ValueError("Command arguments are required.")
    _command, separator, tail = text.partition(" ")
    first, separator, second = tail.strip().partition(" ") if separator else ("", "", "")
    if not separator or not first or not second.strip():
        raise ValueError("Two command arguments are required.")
    return first, second.strip()


def _one_argument(text: str | None) -> str:
    if not text:
        raise ValueError("Command argument is required.")
    _command, separator, tail = text.partition(" ")
    if not separator or not tail.strip() or " " in tail.strip():
        raise ValueError("One command argument is required.")
    return tail.strip()


def _three_arguments(text: str | None) -> tuple[str, str, str]:
    if not text:
        raise ValueError("Command arguments are required.")
    _command, separator, tail = text.partition(" ")
    first, separator, remaining = tail.strip().partition(" ") if separator else ("", "", "")
    second, separator, third = remaining.strip().partition(" ") if separator else ("", "", "")
    if not separator or not first or not second or not third.strip():
        raise ValueError("Three command arguments are required.")
    return first, second, third.strip()


def _parse_decision(value: str) -> tuple[UUID, AssignmentDecision]:
    payload = value.removeprefix(_DECIDE_PREFIX)
    raw_id, separator, raw_decision = payload.partition(":")
    if not separator:
        raise ValueError("Assignment review callback is invalid.")
    return UUID(hex=raw_id), AssignmentDecision(raw_decision)


def _parse_submission(value: str) -> tuple[UUID, int]:
    payload = value.removeprefix(_SUBMIT_PREFIX)
    raw_id, separator, raw_revision = payload.partition(":")
    if not separator:
        raise ValueError("Assignment submission callback is invalid.")
    return UUID(hex=raw_id), int(raw_revision)
