"""Telegram Bot API notification delivery adapter."""

# ruff: noqa: RUF001 - localized user-facing messages intentionally use Cyrillic.

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.application.notifications import NotificationProcessingError
from community_bot.transport.telegram.tasks import cancellation_response_callback

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import ReplyKeyboardMarkup

    from community_bot.application.notifications import DeliveryClaim


class ReplyMarkupFactory(Protocol):
    """Build allowlisted Telegram markup for one notification type."""

    def __call__(self, notification_type: str) -> ReplyKeyboardMarkup | None:
        """Return markup for the exact allowlisted notification type."""
        ...


_MESSAGES = {
    "registration.approved": "Регистрация подтверждена. Главное меню уже доступно.",
    "task.published": "Опубликовано новое задание в сообществе.",
    "task.cancelled": "Задание отменено.",
    "task.cancellation_requested": "Автор просит отменить задание.",
    "task.cancellation_declined": "Исполнитель уже начал работу. Задание остаётся активным.",
    "assignment_accepted": "У задания появился исполнитель.",
    "assignment_submitted": "Результат задания отправлен на проверку.",
    "assignment_cancelled": "Исполнение задания отменено.",
    "assignment_reviewed": "Результат задания проверен.",
    "assignment_disputed": "По заданию открыт спор.",
    "assignment_autoconfirmed": "Результат задания подтверждён автоматически.",
    "assignment_rejected": "Результат задания отклонён.",
    "assignment_no_show": "Срок выполнения задания истёк.",
    "moderation_case_resolved": "Решение по спору сохранено.",
    "interaction_alert_opened": "В административной очереди появился новый сигнал.",
    "task_deadline_reminder": "Напоминание: приближается срок выполнения задания.",
    "review_reminder_24h": "Напоминание: результат задания ожидает проверки.",
    "review_reminder_48h": "Повторное напоминание: результат задания ожидает проверки.",
}
_UNSUPPORTED_NOTIFICATION_TYPE = "unsupported_notification_type"
_RECIPIENT_UNAVAILABLE = "telegram_recipient_unavailable"
_RATE_LIMITED = "telegram_rate_limited"
_TEMPORARILY_UNAVAILABLE = "telegram_temporarily_unavailable"


class TelegramNotificationSender:
    """Send allowlisted messages without exposing persisted payload details."""

    def __init__(self, bot: Bot, reply_markup_factory: ReplyMarkupFactory | None = None) -> None:
        """Use one process-owned aiogram bot client."""
        self._bot = bot
        self._reply_markup_factory = reply_markup_factory

    async def send(self, claim: DeliveryClaim) -> None:
        """Map Telegram failures to safe retry categories."""
        text = _MESSAGES.get(claim.notification_type)
        if text is None:
            raise NotificationProcessingError(_UNSUPPORTED_NOTIFICATION_TYPE, permanent=True)
        reply_markup = (
            None
            if self._reply_markup_factory is None
            else self._reply_markup_factory(claim.notification_type)
        )
        if claim.notification_type == "task.cancellation_requested":
            title = claim.payload.get("title")
            response_id = claim.payload.get("aggregate_id")
            if not isinstance(response_id, str):
                raise NotificationProcessingError(_UNSUPPORTED_NOTIFICATION_TYPE, permanent=True)
            text = (
                f"Автор просит отменить задание «{title}».\n"
                "Можно согласиться отменить или продолжить и сдать результат автору."
            )
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Согласен отменить",
                            callback_data=cancellation_response_callback(
                                response_id, accepted=True
                            ),
                        ),
                        InlineKeyboardButton(
                            text="Сдать результат",
                            callback_data=cancellation_response_callback(
                                response_id, accepted=False
                            ),
                        ),
                    ]
                ]
            )
        try:
            await self._bot.send_message(
                chat_id=claim.telegram_user_id,
                text=text,
                reply_markup=reply_markup,
            )
        except (TelegramForbiddenError, TelegramBadRequest) as error:
            raise NotificationProcessingError(_RECIPIENT_UNAVAILABLE, permanent=True) from error
        except TelegramRetryAfter as error:
            raise NotificationProcessingError(_RATE_LIMITED) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            raise NotificationProcessingError(_TEMPORARILY_UNAVAILABLE) from error
