# ruff: noqa: C901, EM101, PLR0915, PLR2004, RUF001, TRY003
"""Telegram moderation queue, durable previews, sanctions, and appeals."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from community_bot.application.moderation import (
    ConfirmResolutionCommand,
    IssueSanctionCommand,
    OpenFraudCaseCommand,
    PreviewResolutionCommand,
    RequestAppealCommand,
    RevokeSanctionCommand,
)
from community_bot.domain.moderation import ResolutionCode, RestrictedAction, SanctionType

if TYPE_CHECKING:
    from community_bot.application.moderation import ModerationService

_CONFIRM_PREFIX = "mod:res:"


def build_moderation_router(service: ModerationService) -> Router:
    """Build privacy-minimal administrative moderation routes."""
    router = Router(name="moderation")

    async def queue(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            cases = await service.queue(message.from_user.id)
            body = (
                "Очередь модерации пуста."
                if not cases
                else "\n".join(
                    f"{item.id} · {item.case_type} · {item.status} · rev {item.revision}"
                    for item in cases
                )
            )
            await message.answer(body)
        except (PermissionError, LookupError, ValueError):
            await message.answer("Очередь модерации недоступна.")

    async def fraud(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            assignment_id, reason = _id_and_text(message.text)
            case = await service.open_fraud_case(
                OpenFraudCaseCommand(
                    event_update.update_id,
                    message.from_user.id,
                    assignment_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-fraud:{event_update.update_id}"),
                    reason,
                )
            )
            await message.answer(f"Расследование открыто: {case.id}")
        except (PermissionError, LookupError, ValueError):
            await message.answer("Не удалось открыть расследование.")

    async def preview(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            case_id, revision, code, reason = _resolution_arguments(message.text)
            draft = await service.preview_resolution(
                PreviewResolutionCommand(
                    event_update.update_id,
                    message.from_user.id,
                    case_id,
                    revision,
                    code,
                    reason,
                )
            )
            data = f"{_CONFIRM_PREFIX}{draft.id.hex}"
            await message.answer(
                f"Подтвердите решение {draft.code.value} по делу {draft.case_id}.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="Подтвердить", callback_data=data)]]
                ),
            )
        except (PermissionError, LookupError, ValueError):
            await message.answer("Не удалось подготовить решение.")

    async def confirm(callback: CallbackQuery, event_update: Update) -> None:
        try:
            draft_id = UUID(str(callback.data).removeprefix(_CONFIRM_PREFIX))
            case = await service.confirm_resolution(
                ConfirmResolutionCommand(event_update.update_id, callback.from_user.id, draft_id)
            )
            await callback.answer("Решение применено.")
            if isinstance(callback.message, Message):
                await callback.message.answer(f"Дело {case.id}: {case.current_code}")
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Решение устарело или недоступно.", show_alert=True)

    async def appeal(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            case_id, reason = _id_and_text(message.text)
            case = await service.appeal(
                RequestAppealCommand(
                    event_update.update_id,
                    message.from_user.id,
                    case_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-appeal:{event_update.update_id}"),
                    reason,
                )
            )
            await message.answer(f"Апелляция принята: {case.id}")
        except (PermissionError, LookupError, ValueError):
            await message.answer("Не удалось подать апелляцию.")

    async def sanction(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            target_id, sanction_type, hours, actions, reason = _sanction_arguments(message.text)
            ends_at = (
                None
                if hours == 0
                else datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=hours)
            )
            result = await service.issue_sanction(
                IssueSanctionCommand(
                    event_update.update_id,
                    message.from_user.id,
                    target_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-sanction:{event_update.update_id}"),
                    sanction_type,
                    reason,
                    actions,
                    ends_at,
                )
            )
            await message.answer(f"Санкция применена: {result.id}")
        except (PermissionError, LookupError, ValueError):
            await message.answer("Не удалось применить санкцию.")

    async def revoke(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        try:
            sanction_id, reason = _id_and_text(message.text)
            result = await service.revoke_sanction(
                RevokeSanctionCommand(
                    event_update.update_id,
                    message.from_user.id,
                    sanction_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-revoke:{event_update.update_id}"),
                    reason,
                )
            )
            await message.answer(f"Санкция отменена: {result.id}")
        except (PermissionError, LookupError, ValueError):
            await message.answer("Не удалось отменить санкцию.")

    router.message.register(queue, Command("moderation"))
    router.message.register(fraud, Command("mod_fraud"))
    router.message.register(preview, Command("mod_resolve"))
    router.message.register(appeal, Command("mod_appeal"))
    router.message.register(sanction, Command("mod_sanction"))
    router.message.register(revoke, Command("mod_revoke"))
    router.callback_query.register(confirm, F.data.startswith(_CONFIRM_PREFIX))
    return router


def _id_and_text(value: str | None) -> tuple[UUID, str]:
    parts = (value or "").split(maxsplit=2)
    if len(parts) != 3:
        raise ValueError("Expected identifier and reason.")
    return UUID(parts[1]), parts[2].strip()


def _resolution_arguments(value: str | None) -> tuple[UUID, int, ResolutionCode, str]:
    parts = (value or "").split(maxsplit=4)
    if len(parts) != 5:
        raise ValueError("Expected case, revision, code, and reason.")
    return UUID(parts[1]), int(parts[2]), ResolutionCode(parts[3]), parts[4].strip()


def _sanction_arguments(
    value: str | None,
) -> tuple[UUID, SanctionType, int, tuple[RestrictedAction, ...], str]:
    parts = (value or "").split(maxsplit=5)
    if len(parts) != 6:
        raise ValueError("Expected target, type, hours, actions, and reason.")
    actions = (
        () if parts[4] == "-" else tuple(RestrictedAction(item) for item in parts[4].split(","))
    )
    return UUID(parts[1]), SanctionType(parts[2]), int(parts[3]), actions, parts[5].strip()
