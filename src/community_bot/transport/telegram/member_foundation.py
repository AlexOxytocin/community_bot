"""Minimal Telegram routes backed by the member foundation service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update

from community_bot.domain.members import StartOutcome

if TYPE_CHECKING:
    from community_bot.application.member_foundation import MemberFoundationService

REFRESH_MENU_TEXT = "Обновить меню"


@dataclass(frozen=True, slots=True)
class StartPresentation:
    """User-facing text and optional keyboard for a start outcome."""

    text: str
    reply_markup: ReplyKeyboardMarkup | ReplyKeyboardRemove


def present_start(outcome: StartOutcome) -> StartPresentation:
    """Map a persisted outcome to the exact minimal Russian UI contract."""
    remove_keyboard = ReplyKeyboardRemove()
    if outcome is StartOutcome.REGISTRATION_REQUIRED:
        return StartPresentation("Для регистрации потребуется приглашение.", remove_keyboard)
    if outcome is StartOutcome.REGISTRATION_PENDING:
        return StartPresentation("Заявка ожидает подтверждения.", remove_keyboard)
    if outcome is StartOutcome.ACCOUNT_UNAVAILABLE:
        return StartPresentation(
            "Аккаунт недоступен. Обратитесь к администратору.",
            remove_keyboard,
        )
    return StartPresentation(
        "Главное меню",
        ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=REFRESH_MENU_TEXT)]],
            resize_keyboard=True,
        ),
    )


def build_member_foundation_router(service: MemberFoundationService) -> Router:
    """Build routes for `/start` and the one working minimal-menu button."""
    router = Router(name="member_foundation")

    async def handle_start(message: Message, event_update: Update) -> None:
        """Persist the route first and call Bot API only after commit."""
        if message.from_user is None:
            return
        outcome = await service.process_start(
            update_id=event_update.update_id,
            telegram_user_id=message.from_user.id,
        )
        presentation = present_start(outcome)
        await message.answer(presentation.text, reply_markup=presentation.reply_markup)

    router.message.register(handle_start, CommandStart())
    router.message.register(handle_start, F.text == REFRESH_MENU_TEXT)
    return router
