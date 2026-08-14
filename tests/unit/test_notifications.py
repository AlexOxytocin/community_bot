"""Targeted tests for notification scheduling and worker orchestration."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup

from community_bot.application.notifications import (
    DeliveryClaim,
    NotificationProcessingError,
    NotificationWorker,
)
from community_bot.domain.notifications import DeliveryWindow, NotificationError, RetryPolicy
from community_bot.infrastructure.outbox.telegram import TelegramNotificationSender

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram import Bot


def test_retry_policy_is_bounded_and_deterministic() -> None:
    """The same failed attempt gets one reproducible bounded retry timestamp."""
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    policy = RetryPolicy(base_delay_seconds=30, maximum_delay_seconds=60)

    first = policy.next_attempt_at(now=now, attempt_count=3, identity="delivery-1")
    repeated = policy.next_attempt_at(now=now, attempt_count=3, identity="delivery-1")

    assert first == repeated
    assert datetime.timedelta(seconds=60) <= first - now < datetime.timedelta(seconds=90)
    with pytest.raises(NotificationError):
        policy.next_attempt_at(now=now, attempt_count=0, identity="delivery-1")


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (datetime.datetime(2026, 1, 10, 11, tzinfo=datetime.UTC), (9, 0)),
        (datetime.datetime(2026, 1, 10, 15, tzinfo=datetime.UTC), (12, 0)),
        (datetime.datetime(2026, 1, 11, 0, tzinfo=datetime.UTC), (9, 0)),
    ],
)
def test_delivery_window_uses_member_timezone(
    candidate: datetime.datetime, expected: tuple[int, int]
) -> None:
    """The default half-open window is evaluated in the member's IANA timezone."""
    scheduled = DeliveryWindow().schedule(
        candidate=candidate,
        timezone_name="America/Argentina/Buenos_Aires",
    )

    local = scheduled.astimezone(datetime.timezone(datetime.timedelta(hours=-3)))
    assert (local.hour, local.minute) == expected


def test_delivery_window_handles_dst_and_never_passes_deadline() -> None:
    """DST conversion remains aware and a reminder never moves beyond its deadline."""
    window = DeliveryWindow()
    candidate = datetime.datetime(2026, 3, 8, 10, tzinfo=datetime.UTC)
    deadline = datetime.datetime(2026, 3, 8, 13, tzinfo=datetime.UTC)

    scheduled = window.schedule(
        candidate=candidate,
        timezone_name="America/New_York",
        deadline=deadline,
    )

    assert scheduled.tzinfo is datetime.UTC
    assert scheduled <= deadline
    with pytest.raises(NotificationError):
        window.schedule(candidate=candidate, timezone_name="Invalid/Timezone")


class _Queue:
    """Minimal queue fake for one bounded worker tick."""

    def __init__(self, deliveries: Sequence[DeliveryClaim]) -> None:
        self.deliveries = deliveries
        self.failures: list[tuple[str, bool]] = []
        self.sent: list[DeliveryClaim] = []

    async def schedule_reminders(self, **_kwargs: object) -> int:
        return 2

    async def claim_outbox(self, **_kwargs: object) -> tuple[()]:
        return ()

    async def materialize(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def fail_outbox(self, *_args: object, **_kwargs: object) -> bool:
        return False

    async def claim_notifications(self, **_kwargs: object) -> Sequence[DeliveryClaim]:
        return self.deliveries

    async def mark_sent(self, claim: DeliveryClaim, **_kwargs: object) -> bool:
        self.sent.append(claim)
        return True

    async def mark_delivery_failed(self, claim: DeliveryClaim, **kwargs: object) -> bool:
        del claim
        error_code = kwargs["error_code"]
        permanent = kwargs["permanent"]
        assert isinstance(error_code, str)
        assert isinstance(permanent, bool)
        self.failures.append((error_code, permanent))
        return permanent

    async def heartbeat(self, **_kwargs: object) -> None:
        return None


class _Sender:
    """Fail one configured delivery and accept the rest."""

    async def send(self, claim: DeliveryClaim) -> None:
        if claim.notification_type == "temporary":
            error_code = "telegram_temporarily_unavailable"
            raise NotificationProcessingError(error_code)
        if claim.notification_type == "permanent":
            error_code = "telegram_recipient_unavailable"
            raise NotificationProcessingError(error_code, permanent=True)


@pytest.mark.asyncio
async def test_worker_classifies_success_retry_and_terminal_failure() -> None:
    """One tick handles independent delivery outcomes without aborting the batch."""
    deliveries = tuple(
        DeliveryClaim(
            id=uuid4(),
            member_id=uuid4(),
            telegram_user_id=index,
            notification_type=notification_type,
            payload={},
            attempt_count=1,
            lease_token=uuid4(),
        )
        for index, notification_type in enumerate(("ok", "temporary", "permanent"), start=1)
    )
    queue = _Queue(deliveries)

    result = await NotificationWorker(queue, _Sender()).tick(
        now=datetime.datetime.now(datetime.UTC)
    )

    assert result.reminders_created == 2
    assert result.notifications_sent == 1
    assert result.notifications_retried == 1
    assert result.notifications_failed == 1
    assert queue.failures == [
        ("telegram_temporarily_unavailable", False),
        ("telegram_recipient_unavailable", True),
    ]


class _TelegramBotStub:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[int, str]] = []
        self.reply_markups: list[object | None] = []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: object | None = None,
    ) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))
        self.reply_markups.append(reply_markup)


def _telegram_method() -> SendMessage:
    return SendMessage(chat_id=42, text="safe")


@pytest.mark.asyncio
async def test_telegram_sender_uses_allowlisted_message() -> None:
    """Delivery ignores persisted payload and sends only allowlisted text."""
    bot = _TelegramBotStub()
    sender = TelegramNotificationSender(cast("Bot", bot))
    claim = DeliveryClaim(
        id=uuid4(),
        member_id=uuid4(),
        telegram_user_id=42,
        notification_type="task.published",
        payload={"private": "must not be sent"},
        attempt_count=1,
        lease_token=uuid4(),
    )

    await sender.send(claim)

    assert bot.sent == [(42, "Опубликовано новое задание в сообществе.")]
    assert bot.reply_markups == [None]


@pytest.mark.asyncio
async def test_telegram_sender_rejects_unknown_notification_type() -> None:
    """Unknown notification types fail permanently before Bot API access."""
    bot = _TelegramBotStub()
    sender = TelegramNotificationSender(cast("Bot", bot))
    claim = DeliveryClaim(
        id=uuid4(),
        member_id=uuid4(),
        telegram_user_id=42,
        notification_type="private.raw.event",
        payload={},
        attempt_count=1,
        lease_token=uuid4(),
    )

    with pytest.raises(NotificationProcessingError) as captured:
        await sender.send(claim)

    assert captured.value.error_code == "unsupported_notification_type"
    assert captured.value.permanent
    assert bot.sent == []


@pytest.mark.asyncio
async def test_cancellation_notification_has_stable_performer_actions() -> None:
    """A retry renders the same response identity and no arbitrary persisted text."""
    bot = _TelegramBotStub()
    sender = TelegramNotificationSender(cast("Bot", bot))
    response_id = uuid4()
    claim = DeliveryClaim(
        id=uuid4(),
        member_id=uuid4(),
        telegram_user_id=42,
        notification_type="task.cancellation_requested",
        payload={
            "aggregate_id": str(response_id),
            "title": "Проверка лендинга",
            "private": "не отправлять",
        },
        attempt_count=2,
        lease_token=uuid4(),
    )

    await sender.send(claim)
    await sender.send(claim)

    assert len(bot.sent) == 2
    assert "Проверка лендинга" in bot.sent[0][1]
    assert "не отправлять" not in bot.sent[0][1]
    assert bot.reply_markups[0] == bot.reply_markups[1]
    markup = bot.reply_markups[0]
    assert isinstance(markup, InlineKeyboardMarkup)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    first, second = callbacks
    assert isinstance(first, str)
    assert isinstance(second, str)
    assert first.startswith("task:cancel:yes:")
    assert second.startswith("task:cancel:nope:")
    assert all(len(value.encode()) <= 64 for value in (first, second))


@pytest.mark.parametrize(
    ("telegram_error", "expected_code", "permanent"),
    [
        (
            TelegramBadRequest(method=_telegram_method(), message="bad recipient"),
            "telegram_recipient_unavailable",
            True,
        ),
        (
            TelegramRetryAfter(method=_telegram_method(), message="slow down", retry_after=1),
            "telegram_rate_limited",
            False,
        ),
        (
            TelegramNetworkError(method=_telegram_method(), message="network unavailable"),
            "telegram_temporarily_unavailable",
            False,
        ),
    ],
)
@pytest.mark.asyncio
async def test_telegram_sender_classifies_api_failures(
    telegram_error: Exception,
    expected_code: str,
    *,
    permanent: bool,
) -> None:
    """Telegram failures become safe retry categories without raw details."""
    sender = TelegramNotificationSender(cast("Bot", _TelegramBotStub(telegram_error)))
    claim = DeliveryClaim(
        id=uuid4(),
        member_id=uuid4(),
        telegram_user_id=42,
        notification_type="task.cancelled",
        payload={},
        attempt_count=1,
        lease_token=uuid4(),
    )

    with pytest.raises(NotificationProcessingError) as captured:
        await sender.send(claim)

    assert captured.value.error_code == expected_code
    assert captured.value.permanent is permanent
