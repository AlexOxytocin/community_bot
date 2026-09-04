from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage

from community_bot.application.notifications import DeliveryClaim, NotificationProcessingError
from community_bot.infrastructure.outbox.telegram import TelegramNotificationSender
from community_bot.transport.activity_menu import activity_panel


@pytest.mark.asyncio
async def test_activity_sends_source_link_and_does_not_retry_uncertain_delivery() -> None:
    bot = AsyncMock()
    sender = TelegramNotificationSender(bot)
    claim = DeliveryClaim(
        id=uuid4(),
        member_id=uuid4(),
        telegram_user_id=42,
        notification_type="activity.published",
        payload={
            "categories": ["online", "offline", "important", "crypto"],
            "message_url": "https://t.me/c/2237685639/24962/24968",
        },
        attempt_count=1,
        lease_token=uuid4(),
    )
    await sender.send(claim)
    sent = bot.send_message.call_args.kwargs
    assert sent["reply_markup"].inline_keyboard[0][0].url == claim.payload["message_url"]
    assert "Онлайн ивенты" in sent["text"]
    assert "Важные обновления чата" in sent["text"]
    assert "Крипта" in sent["text"]
    bot.send_message.side_effect = TelegramNetworkError(
        method=SendMessage(chat_id=42, text="test"),
        message="connection lost",
    )
    with pytest.raises(NotificationProcessingError) as error:
        await sender.send(claim)
    assert error.value.permanent
    assert error.value.error_code == "delivery_uncertain"


def test_panel_excludes_chat_activity_and_offers_explicit_subscription() -> None:
    preferences: dict[str, object] = {"revision": 3}
    _, overview = activity_panel(preferences)
    callbacks = [button.callback_data for row in overview for button in row]
    assert callbacks == [
        "subscription:important:1:3",
        "subscription:nomad:1:3",
        "subscription:tasks:1:3",
        "subscription:online:1:3",
        "subscription:offline:1:3",
        "subscription:crypto:1:3",
        "activities:help",
    ]
    _, detail = activity_panel(preferences, "nomad")
    assert detail[0][0].text == "Подписаться"
    assert detail[0][0].callback_data == "subscription:nomad:1:3"
    text, detail = activity_panel(preferences, "important")
    assert "#important" in text
    assert detail[0][0].callback_data == "subscription:important:1:3"


def test_mutual_help_is_one_direct_toggle_including_legacy_pages() -> None:
    preferences: dict[str, object] = {"revision": 0}
    _, overview = activity_panel(preferences)
    assert overview[2][0].text == "☐ Взаимопомощь"
    assert overview[2][0].callback_data == "subscription:tasks:1:0"
    for page in ("tasks_group", "tasks", "disputes", "task_updates", "task_reminders"):
        assert activity_panel(preferences, page)[1] == overview
    preferences["disputes"] = True
    _, overview = activity_panel(preferences)
    assert overview[2][0].text == "☑ Взаимопомощь"
    assert overview[2][0].callback_data == "subscription:tasks:0:0"
