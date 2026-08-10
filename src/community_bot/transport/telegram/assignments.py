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

if TYPE_CHECKING:
    from community_bot.application.assignments import AssignmentService

_ACCEPT_PREFIX = "task:accept:"
_DECIDE_PREFIX = "assign:review:"
_SUBMIT_PREFIX = "assign:submit:"


def build_assignment_router(service: AssignmentService) -> Router:
    """Build the complete assignment exchange router."""
    router = Router(name="assignments")

    async def accept(callback: CallbackQuery, event_update: Update) -> None:
        try:
            task_id = UUID(str(callback.data).removeprefix(_ACCEPT_PREFIX))
            assignment = await service.accept(
                AcceptAssignmentCommand(event_update.update_id, callback.from_user.id, task_id)
            )
            await callback.answer("Задание принято.")
            if isinstance(callback.message, Message):
                await callback.message.answer(f"Назначение: {assignment.id}")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Не удалось принять задание.", show_alert=True)

    async def owned(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            assignments = await service.list_owned(message.from_user.id)
            text = (
                "У вас пока нет заданий."
                if not assignments
                else "\n".join(f"{item.id} · {item.status.value}" for item in assignments)
            )
            await message.answer(text)
        except (AssignmentError, PermissionError, LookupError):
            await message.answer("Не удалось открыть ваши задания.")

    async def cancel(message: Message, event_update: Update) -> None:
        if message.from_user is None:
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
            draft_id, revision = _parse_submission(str(callback.data))
            result = await service.confirm_submission_draft(
                ConfirmSubmissionDraftCommand(
                    event_update.update_id, callback.from_user.id, draft_id, revision
                )
            )
            await callback.answer(f"Результат отправлен, версия {result.version}.")
        except (AssignmentError, PermissionError, LookupError, ValueError):
            await callback.answer("Не удалось отправить результат.", show_alert=True)

    async def decide(callback: CallbackQuery, event_update: Update) -> None:
        try:
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

    async def dispute(message: Message, event_update: Update) -> None:
        if message.from_user is None:
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
    router.callback_query.register(decide, F.data.startswith(_DECIDE_PREFIX))
    router.callback_query.register(confirm_submit, F.data.startswith(_SUBMIT_PREFIX))
    router.message.register(owned, Command("my_assignments"))
    router.message.register(cancel, Command("assignment_cancel"))
    router.message.register(submit, Command("assignment_submit"))
    router.message.register(save_preview, Command("assignment_result"))
    router.message.register(dispute, Command("assignment_dispute"))
    return router


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
