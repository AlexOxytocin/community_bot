"""Telegram Bot API notification delivery adapter."""

# ruff: noqa: RUF001 - localized user-facing messages intentionally use Cyrillic.

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from community_bot.application.notifications import NotificationProcessingError

if TYPE_CHECKING:
    from aiogram import Bot

    from community_bot.application.notifications import DeliveryClaim


_MESSAGES = {
    "registration.approved": "Регистрация подтверждена.",
    "registration.submitted": "В очереди модерации появилась новая регистрация.",
    "task.published": "Опубликовано новое задание в сообществе.",
    "task.cancelled": "Задание отменено.",
    "task.cancellation_requested": "Автор запросил отмену задания. Запрос ожидает ответа.",
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

    def __init__(self, bot: Bot) -> None:
        """Use one process-owned aiogram bot client."""
        self._bot = bot

    async def send(self, claim: DeliveryClaim) -> None:
        """Map Telegram failures to safe retry categories."""
        text = _MESSAGES.get(claim.notification_type)
        if text is None:
            raise NotificationProcessingError(_UNSUPPORTED_NOTIFICATION_TYPE, permanent=True)
        try:
            await self._bot.send_message(
                chat_id=claim.telegram_user_id,
                text=text,
            )
        except (TelegramForbiddenError, TelegramBadRequest) as error:
            raise NotificationProcessingError(_RECIPIENT_UNAVAILABLE, permanent=True) from error
        except TelegramRetryAfter as error:
            raise NotificationProcessingError(_RATE_LIMITED) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            raise NotificationProcessingError(_TEMPORARILY_UNAVAILABLE) from error
