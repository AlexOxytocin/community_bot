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
    ReviewAlertCommand,
    RevokeSanctionCommand,
)
from community_bot.domain.moderation import (
    AlertOutcome,
    ResolutionCode,
    RestrictedAction,
    SanctionType,
)

if TYPE_CHECKING:
    from community_bot.application.moderation import ModerationCase, ModerationService

_CONFIRM_PREFIX = "mod:res:"
_CASE_PREFIX = "mod:case:"
_FRAUD_PREFIX = "mod:fraud:"
_APPEAL_PREFIX = "mod:appeal:"
_WARN_PREFIX = "mod:warn:"
_RESTRICT_PREFIX = "mod:restrict:"
_REVOKE_PREFIX = "mod:revoke:"
_ALERT_PREFIX = "mod:alert:"
_LIST_PREFIX = "mod:list:"
_RESOLUTION_CODES = {
    "pay": ResolutionCode.FULL_PAYMENT,
    "part": ResolutionCode.PARTIAL_PAYMENT,
    "refund": ResolutionCode.FULL_REFUND,
    "cancel": ResolutionCode.CANCEL_WITHOUT_FAULT,
    "noshow": ResolutionCode.PERFORMER_NO_SHOW,
    "abuse": ResolutionCode.CREATOR_ABUSE,
    "fraud": ResolutionCode.FRAUD,
}


def build_moderation_router(service: ModerationService) -> Router:
    """Build privacy-minimal administrative moderation routes."""
    router = Router(name="moderation")

    async def queue(message: Message) -> None:
        if message.from_user is None:
            return
        try:
            await send_moderation_overview(message, service)
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

    async def case_resolution(callback: CallbackQuery, event_update: Update) -> None:
        try:
            raw_case, raw_revision, raw_code = (
                str(callback.data).removeprefix(_CASE_PREFIX).split(":", 2)
            )
            code = _RESOLUTION_CODES[raw_code]
            draft = await service.preview_resolution(
                PreviewResolutionCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    UUID(hex=raw_case),
                    int(raw_revision),
                    code,
                    "Решение администратора через Telegram",
                )
            )
            await callback.answer()
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    f"Подтвердите решение: {_resolution_label(code)}.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Подтвердить решение",
                                    callback_data=f"{_CONFIRM_PREFIX}{draft.id.hex}",
                                )
                            ]
                        ]
                    ),
                )
        except (KeyError, PermissionError, LookupError, ValueError):
            await callback.answer("Решение недоступно или устарело.", show_alert=True)

    async def fraud_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            assignment_id = UUID(hex=str(callback.data).removeprefix(_FRAUD_PREFIX))
            case = await service.open_fraud_case(
                OpenFraudCaseCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    assignment_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-fraud:{event_update.update_id}"),
                    "Ручная проверка выплаты через Telegram",
                )
            )
            await callback.answer("Расследование открыто.")
            if isinstance(callback.message, Message):
                await _send_case(callback.message, case)
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Расследование недоступно.", show_alert=True)

    async def appeal_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            case_id = UUID(hex=str(callback.data).removeprefix(_APPEAL_PREFIX))
            await service.appeal(
                RequestAppealCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    case_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-appeal:{event_update.update_id}"),
                    "Апелляция участника через Telegram",
                )
            )
            await callback.answer("Апелляция подана.")
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Апелляция недоступна.", show_alert=True)

    async def sanction_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            raw = str(callback.data)
            restricted = raw.startswith(_RESTRICT_PREFIX)
            prefix = _RESTRICT_PREFIX if restricted else _WARN_PREFIX
            target_id = UUID(hex=raw.removeprefix(prefix))
            await service.issue_sanction(
                IssueSanctionCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    target_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-sanction:{event_update.update_id}"),
                    SanctionType.RESTRICTION if restricted else SanctionType.WARNING,
                    "Решение администратора через Telegram",
                    (RestrictedAction.ACCEPT_TASK, RestrictedAction.CREATE_TASK)
                    if restricted
                    else (),
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=7)
                    if restricted
                    else None,
                )
            )
            await callback.answer("Санкция применена.")
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Санкция недоступна.", show_alert=True)

    async def revoke_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            sanction_id = UUID(hex=str(callback.data).removeprefix(_REVOKE_PREFIX))
            await service.revoke_sanction(
                RevokeSanctionCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    sanction_id,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-revoke:{event_update.update_id}"),
                    "Отменено администратором через Telegram",
                )
            )
            await callback.answer("Санкция отменена.")
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Санкция недоступна.", show_alert=True)

    async def alert_callback(callback: CallbackQuery, event_update: Update) -> None:
        try:
            raw_id, raw_outcome = str(callback.data).removeprefix(_ALERT_PREFIX).split(":", 1)
            outcome = {
                "ok": AlertOutcome.LEGITIMATE,
                "watch": AlertOutcome.MONITOR,
            }[raw_outcome]
            await service.review_alert(
                ReviewAlertCommand(
                    event_update.update_id,
                    callback.from_user.id,
                    UUID(hex=raw_id),
                    uuid.uuid5(uuid.NAMESPACE_URL, f"moderation-alert:{event_update.update_id}"),
                    outcome,
                    "Проверено администратором через Telegram",
                )
            )
            await callback.answer("Алерт закрыт.")
        except (KeyError, PermissionError, LookupError, ValueError):
            await callback.answer("Алерт недоступен.", show_alert=True)

    async def list_callback(callback: CallbackQuery) -> None:
        try:
            if not isinstance(callback.message, Message):
                return
            action = str(callback.data).removeprefix(_LIST_PREFIX)
            await callback.answer()
            if action == "fraud":
                await _send_paid_assignments(callback.message, service, callback.from_user.id)
            elif action == "alerts":
                await _send_alerts(callback.message, service, callback.from_user.id)
            elif action == "sanctions":
                await _send_sanctions(callback.message, service, callback.from_user.id)
            else:
                _unknown_moderation_list()
        except (PermissionError, LookupError, ValueError):
            await callback.answer("Раздел недоступен.", show_alert=True)

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
    router.callback_query.register(case_resolution, F.data.startswith(_CASE_PREFIX))
    router.callback_query.register(fraud_callback, F.data.startswith(_FRAUD_PREFIX))
    router.callback_query.register(appeal_callback, F.data.startswith(_APPEAL_PREFIX))
    router.callback_query.register(
        sanction_callback,
        F.data.startswith(_WARN_PREFIX) | F.data.startswith(_RESTRICT_PREFIX),
    )
    router.callback_query.register(revoke_callback, F.data.startswith(_REVOKE_PREFIX))
    router.callback_query.register(alert_callback, F.data.startswith(_ALERT_PREFIX))
    router.callback_query.register(list_callback, F.data.startswith(_LIST_PREFIX))
    return router


async def send_moderation_overview(message: Message, service: ModerationService) -> None:
    """Send the reachable moderation queue and its adjacent admin sections."""
    if message.from_user is None:
        return
    cases = await service.queue(message.from_user.id)
    if not cases:
        await message.answer("Очередь споров и расследований пуста.")
    for case in cases:
        await _send_case(message, case)
    if not await service.is_administrator(message.from_user.id):
        return
    await message.answer(
        "Другие разделы модерации:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Проверить выплаты", callback_data="mod:list:fraud")],
                [
                    InlineKeyboardButton(
                        text="Алерты взаимодействий", callback_data="mod:list:alerts"
                    )
                ],
                [InlineKeyboardButton(text="Активные санкции", callback_data="mod:list:sanctions")],
            ]
        ),
    )


async def _send_case(message: Message, case: ModerationCase) -> None:
    choices = (
        {"fraud": ResolutionCode.FRAUD}
        if case.case_type == "fraud_review" and case.status == "open"
        else _RESOLUTION_CODES
    )
    rows = [
        [
            InlineKeyboardButton(
                text=_resolution_label(code),
                callback_data=f"{_CASE_PREFIX}{case.id.hex}:{case.revision}:{key}",
            )
        ]
        for key, code in choices.items()
    ]
    await message.answer(
        f"Дело: {'спор' if case.case_type == 'dispute' else 'проверка выплаты'}\n"
        f"Статус: {case.status}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _send_paid_assignments(
    message: Message, service: ModerationService, actor_telegram_user_id: int
) -> None:
    items = await service.paid_assignments(actor_telegram_user_id)
    if not items:
        await message.answer("Выплат для ручной проверки нет.")
    for item in items:
        await message.answer(
            f"{item.task_title}\nИсполнитель: {item.performer_display_name}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Открыть проверку",
                            callback_data=f"{_FRAUD_PREFIX}{item.assignment_id.hex}",
                        )
                    ]
                ]
            ),
        )


async def _send_alerts(
    message: Message, service: ModerationService, actor_telegram_user_id: int
) -> None:
    items = await service.alerts(actor_telegram_user_id)
    if not items:
        await message.answer("Открытых алертов нет.")
    for item in items:
        await message.answer(
            f"{item.first_display_name} ↔ {item.second_display_name}\n"
            f"Взаимодействий: {item.interaction_count}, порог: {item.threshold}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Всё в порядке",
                            callback_data=f"{_ALERT_PREFIX}{item.id.hex}:ok",
                        ),
                        InlineKeyboardButton(
                            text="Наблюдать",
                            callback_data=f"{_ALERT_PREFIX}{item.id.hex}:watch",
                        ),
                    ]
                ]
            ),
        )


async def _send_sanctions(
    message: Message, service: ModerationService, actor_telegram_user_id: int
) -> None:
    items = await service.sanctions(actor_telegram_user_id)
    if not items:
        await message.answer("Активных санкций нет.")
    for item in items:
        await message.answer(
            f"{item.target_display_name}: {item.sanction.sanction_type.value}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Отменить санкцию",
                            callback_data=f"{_REVOKE_PREFIX}{item.sanction.id.hex}",
                        )
                    ]
                ]
            ),
        )


def _resolution_label(code: ResolutionCode) -> str:
    return {
        ResolutionCode.FULL_PAYMENT: "Полная выплата",
        ResolutionCode.PARTIAL_PAYMENT: "Частичная выплата",
        ResolutionCode.FULL_REFUND: "Полный возврат",
        ResolutionCode.CANCEL_WITHOUT_FAULT: "Отмена без вины",
        ResolutionCode.PERFORMER_NO_SHOW: "Неявка исполнителя",
        ResolutionCode.CREATOR_ABUSE: "Нарушение автора",
        ResolutionCode.FRAUD: "Мошенничество",
    }[code]


def _unknown_moderation_list() -> None:
    raise ValueError("Unknown moderation list.")


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
