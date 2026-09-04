"""Telegram Bot API notification delivery adapter."""

# ruff: noqa: RUF001 - localized user-facing messages intentionally use Cyrillic.

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.application.notifications import NotificationProcessingError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram import Bot

    from community_bot.application.notifications import DeliveryClaim


_MESSAGES = {
    "nomad.published": "🌍 Цифровой кочевник\n\nВ теме появилась новая информация.",
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
    "assignment_rejection_pending_dispute": None,
    "assignment_disputed": "По заданию открыт спор.",
    "assignment_autoconfirmed": "Результат задания подтверждён автоматически.",
    "assignment_rejected": "Срок подачи спора истёк. Отклонение результата вступило в силу.",
    "assignment_no_show": "Срок выполнения задания истёк.",
    "moderation_case_resolved": "Решение по спору сохранено.",
    "interaction_alert_opened": "В административной очереди появился новый сигнал.",
    "task_deadline_reminder": "Напоминание: приближается срок выполнения задания.",
    "review_reminder_24h": "Напоминание: результат задания ожидает проверки.",
    "review_reminder_48h": "Повторное напоминание: результат задания ожидает проверки.",
}
_REJECTION_REASON_LABELS = {
    "not_completed": "Задание не выполнено",
    "requirements_not_met": "Результат не соответствует условиям",
    "insufficient_evidence": "Недостаточно подтверждений",
    "other": "Другая причина",
}
_UNSUPPORTED_NOTIFICATION_TYPE = "unsupported_notification_type"
_RECIPIENT_UNAVAILABLE = "telegram_recipient_unavailable"
_RATE_LIMITED = "telegram_rate_limited"
_TEMPORARILY_UNAVAILABLE = "telegram_temporarily_unavailable"
_INVALID_NOTIFICATION_PAYLOAD = "invalid_notification_payload"
_NOTIFICATION_DISABLED = "notification_disabled"


def _notification_text(claim: DeliveryClaim) -> str:
    if claim.notification_type == "activity.published":
        names = {
            "online": "💻 Онлайн ивенты",
            "offline": "📍 Офлайн ивенты",
            "nomad": "🌍 Цифровой кочевник",
            "important": "📌 Важные обновления чата",
            "crypto": "🪙 Крипта",
        }
        categories = claim.payload.get("categories")
        if (
            not isinstance(categories, list)
            or not categories
            or any(not isinstance(key, str) or key not in names for key in categories)
        ):
            raise NotificationProcessingError(_INVALID_NOTIFICATION_PAYLOAD, permanent=True)
        return (
            " · ".join(names[key] for key in categories)
            + "\n\nНовая публикация администратора в сообществе."
        )
    if claim.notification_type == "wallet.transfer_received":
        amount = claim.payload.get("amount")
        if type(amount) is not int or amount <= 0:
            raise NotificationProcessingError(_INVALID_NOTIFICATION_PAYLOAD, permanent=True)
        return (
            f"Получен перевод: +{amount} кредитов. Подробности — во вкладке «Кошелёк» в приложении."
        )
    if claim.notification_type != "assignment_rejection_pending_dispute":
        text = _MESSAGES.get(claim.notification_type)
        if not isinstance(text, str):
            raise NotificationProcessingError(_UNSUPPORTED_NOTIFICATION_TYPE, permanent=True)
        return text
    reason = claim.payload.get("rejection_reason")
    label = _REJECTION_REASON_LABELS.get(reason) if isinstance(reason, str) else None
    if label is None:
        raise NotificationProcessingError(_INVALID_NOTIFICATION_PAYLOAD, permanent=True)
    parts = ["Результат задания отклонён.", f"Причина: {label}."]
    comment = claim.payload.get("rejection_comment")
    if isinstance(comment, str) and (normalized := " ".join(comment.split())):
        parts.append(f"Комментарий: {normalized[:500]}")
    parts.append("Резерв заморожен на 24 часа. Вы можете открыть спор в приложении.")
    return "\n\n".join(parts)


class TelegramNotificationSender:
    """Send allowlisted messages without exposing persisted payload details."""

    def __init__(
        self,
        bot: Bot,
        *,
        allow_delivery: Callable[[DeliveryClaim], Awaitable[bool]] | None = None,
    ) -> None:
        """Use one process-owned aiogram bot client."""
        self._bot = bot
        self._allow_delivery = allow_delivery

    async def send(self, claim: DeliveryClaim) -> None:
        """Map Telegram failures to safe retry categories."""
        text = _notification_text(claim)
        if self._allow_delivery is not None and not await self._allow_delivery(claim):
            raise NotificationProcessingError(_NOTIFICATION_DISABLED, permanent=True)
        markup = None
        if claim.notification_type in {"nomad.published", "activity.published"}:
            url = claim.payload.get("message_url")
            if not isinstance(url, str) or not re.fullmatch(
                r"https://t\.me/c/[0-9]+/(?:[0-9]+/)?[0-9]+", url
            ):
                raise NotificationProcessingError(_INVALID_NOTIFICATION_PAYLOAD, permanent=True)
            markup = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть сообщение", url=url)]]
            )
        try:
            await self._bot.send_message(
                chat_id=claim.telegram_user_id,
                text=text,
                **({"reply_markup": markup} if markup is not None else {}),
            )
        except (TelegramForbiddenError, TelegramBadRequest) as error:
            raise NotificationProcessingError(_RECIPIENT_UNAVAILABLE, permanent=True) from error
        except TelegramRetryAfter as error:
            raise NotificationProcessingError(_RATE_LIMITED) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            raise NotificationProcessingError(
                "delivery_uncertain"
                if claim.notification_type == "activity.published"
                else _TEMPORARILY_UNAVAILABLE,
                permanent=claim.notification_type == "activity.published",
            ) from error
