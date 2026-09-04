from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from community_bot.application.identity import ActorContext
from community_bot.application.membership import MembershipCheckUnavailableError
from community_bot.bootstrap.settings import Settings
from community_bot.domain.community_preferences import (
    PreferencesConflictError,
    notification_category,
    topic_message_url,
)
from community_bot.domain.members import MemberStatus
from community_bot.infrastructure.db.activity_publications import activity_publisher
from community_bot.infrastructure.db.community_preferences import active_superadministrator
from community_bot.infrastructure.db.models import MemberModel
from community_bot.transport.community_settings import install_community_settings_routes
from community_bot.transport.telegram_updates import (
    ACTIVITIES_BUTTON,
    APP_BUTTON,
    HELP_BUTTON,
    NOMAD_SUBSCRIBE_BUTTON,
    NOMAD_SUBSCRIBED_BUTTON,
    NOTIFICATIONS_BUTTON,
    START_BUTTON,
    TelegramUpdates,
)

CHAT_ID = -1002237685639
TOPIC_ID = 24962


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("task.published", "tasks"),
        ("assignment_submitted", "task_updates"),
        ("review_reminder_24h", "task_reminders"),
        ("task_deadline_reminder", "task_reminders"),
        ("assignment_disputed", "disputes"),
        ("moderation_case_resolved", "disputes"),
        ("nomad.published", "nomad"),
        ("wallet.transfer_received", None),
        ("registration.approved", None),
        ("interaction_alert_opened", None),
    ],
)
def test_notification_categories(kind: str, expected: str | None) -> None:
    assert notification_category(kind) == expected


@pytest.mark.parametrize(
    ("role", "status", "permissions", "expected"),
    [
        ("administrator", "active", ["superadministrator"], True),
        ("administrator", "active", [], False),
        ("moderator", "active", ["superadministrator"], False),
        ("administrator", "banned", ["superadministrator"], False),
    ],
)
def test_only_active_superadministrator_can_change_registration_policy(
    role: str,
    status: str,
    permissions: list[str],
    expected: bool,  # noqa: FBT001 - parametrized expectation.
) -> None:
    assert (
        active_superadministrator(
            MemberModel(role=role, status=status, permissions_json=permissions)
        )
        is expected
    )


@pytest.mark.parametrize(
    ("role", "status", "expected"),
    [
        ("administrator", "active", True),
        ("moderator", "active", False),
        ("member", "active", False),
        ("administrator", "banned", False),
    ],
)
def test_regular_administrator_can_publish_activity(
    role: str,
    status: str,
    expected: bool,  # noqa: FBT001
) -> None:
    assert (
        activity_publisher(MemberModel(role=role, status=status, permissions_json=[])) is expected
    )


@pytest.mark.asyncio
async def test_caption_hashtags_use_utf16_offsets_and_ignore_plain_text() -> None:
    handler, _, _ = _handler()
    message = {
        **_post(),
        "text": None,
        "entities": [],
        "caption": "🌍 #OFFLINE #online #IMPORTANT #nomad #other",
        "caption_entities": [
            {"type": "hashtag", "offset": 3, "length": 8},
            {"type": "hashtag", "offset": 12, "length": 7},
            {"type": "hashtag", "offset": 20, "length": 10},
        ],
        "photo": [{"file_id": "x", "file_unique_id": "x", "width": 10, "height": 10}],
    }
    await handler.handle(json.dumps({"update_id": 9, "message": message}).encode())
    publications = cast("AsyncMock", handler.publications)
    assert publications.observe.call_args.kwargs["categories"] == {"offline", "online", "important"}
    publications.observe.reset_mock()
    message["forward_origin"] = {
        "type": "hidden_user",
        "date": message["date"],
        "sender_user_name": "Hidden",
    }
    await handler.handle(json.dumps({"update_id": 10, "message": message}).encode())
    publications.observe.assert_not_awaited()


def test_exact_topic_message_link() -> None:
    assert topic_message_url(CHAT_ID, TOPIC_ID, 24968) == "https://t.me/c/2237685639/24962/24968"
    with pytest.raises(ValueError, match="Invalid Telegram topic identity"):
        topic_message_url(123, TOPIC_ID, 24968)


def _handler() -> tuple[TelegramUpdates, AsyncMock, AsyncMock]:
    store = AsyncMock(
        publish_nomad=AsyncMock(),
        member_for_telegram=AsyncMock(return_value=None),
        preferences=AsyncMock(return_value={"tasks": False, "nomad": False, "revision": 0}),
        set_preference=AsyncMock(),
    )
    bot = AsyncMock(
        send_message=AsyncMock(), answer_callback_query=AsyncMock(), edit_message_text=AsyncMock()
    )
    registration = AsyncMock()
    handler = TelegramUpdates(
        bot=bot,
        settings=Settings(
            _env_file=None,
            community_telegram_chat_id=CHAT_ID,
            community_telegram_join_url="https://t.me/+example",
            telegram_bot_username="humanquest_bot",
            nomad_telegram_chat_id=CHAT_ID,
            nomad_telegram_topic_id=TOPIC_ID,
        ),
        store=store,
        registration=registration,
        membership=AsyncMock(is_member=AsyncMock(return_value=True)),
    )
    handler.publications = AsyncMock()
    return handler, store, registration


def _post() -> dict:
    return {
        "message_id": 24968,
        "date": int(datetime.datetime.now(datetime.UTC).timestamp()),
        "chat": {"id": CHAT_ID, "type": "supergroup"},
        "from": {"id": 456, "is_bot": False, "first_name": "Alex"},
        "message_thread_id": TOPIC_ID,
        "is_topic_message": True,
        "text": "#nomad",
        "entities": [{"type": "hashtag", "offset": 0, "length": 6}],
    }


@pytest.mark.asyncio
async def test_tag_ingress_accepts_edits_all_topics_but_ignores_anonymous_and_other_chats() -> None:
    handler, _, _ = _handler()
    publications = cast("AsyncMock", handler.publications)
    await handler.handle(json.dumps({"update_id": 1, "message": _post()}).encode())
    publications.observe.assert_awaited_once()
    assert publications.observe.call_args.kwargs["categories"] == {"nomad"}
    for variant in [
        {"edited_message": _post()},
        {"message": {**_post(), "message_thread_id": TOPIC_ID + 1}},
    ]:
        await handler.handle(json.dumps({"update_id": 2, **variant}).encode())
    assert publications.observe.await_count == 3
    publications.observe.reset_mock()
    variants = [
        {"message": {**_post(), "sender_chat": {"id": CHAT_ID, "type": "supergroup"}}},
        {"message": {**_post(), "text": None, "forum_topic_closed": {}}},
        {"message": {**_post(), "chat": {"id": CHAT_ID - 1, "type": "supergroup"}}},
    ]
    for variant in variants:
        await handler.handle(json.dumps({"update_id": 2, **variant}).encode())
    publications.observe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("joined", [False, MembershipCheckUnavailableError()])
@pytest.mark.parametrize("label", ["/start", START_BUTTON])
async def test_start_is_fail_closed_without_confirmed_chat_membership(
    joined: object, label: str
) -> None:
    handler, _, registration = _handler()
    if isinstance(joined, Exception):
        cast("AsyncMock", handler.membership).is_member.side_effect = joined
    else:
        cast("AsyncMock", handler.membership).is_member.return_value = joined
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": label}
    await handler.handle(json.dumps({"update_id": 3, "message": message}).encode())
    registration.start.assert_not_awaited()
    cast("AsyncMock", handler.bot).send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_preferences_use_explicit_shared_value_and_revision() -> None:
    handler, store, _ = _handler()
    member_id = uuid4()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status="active")
    callback = {
        "id": "cb1",
        "chat_instance": "test",
        "from": _post()["from"],
        "data": "notifications:nomad:1:0",
        "message": {**_post(), "chat": {"id": 456, "type": "private"}},
    }
    await handler.handle(json.dumps({"update_id": 4, "callback_query": callback}).encode())
    store.set_preference.assert_awaited_once_with(member_id, "nomad", True, 0)  # noqa: FBT003
    cast("AsyncMock", handler.bot).edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["/start", START_BUTTON])
async def test_start_shows_compact_persistent_bottom_menu(label: str) -> None:
    handler, _, registration = _handler()
    registration.start.return_value = SimpleNamespace(
        context=SimpleNamespace(member_status=MemberStatus.ACTIVE, member_id=uuid4())
    )
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": label}
    await handler.handle(json.dumps({"update_id": 11, "message": message}).encode())
    registration.start.assert_awaited_once()
    command = registration.start.call_args.args[0]
    assert command.telegram_user_id == 456
    assert command.telegram_display_name == "Alex"
    assert command.community_membership_verified
    assert command.invitation_token is None
    replies = cast("AsyncMock", handler.bot).send_message.call_args_list
    markup = replies[0].kwargs["reply_markup"]
    assert markup.is_persistent
    assert markup.resize_keyboard
    assert not markup.one_time_keyboard
    assert [[key.text for key in row] for row in markup.keyboard] == [
        [ACTIVITIES_BUTTON],
        [HELP_BUTTON],
    ]
    assert all(key.web_app is None for row in markup.keyboard for key in row)
    assert replies[1].kwargs["reply_markup"].inline_keyboard[0][0].text == "☐ Онлайн-встречи"


@pytest.mark.asyncio
@pytest.mark.parametrize("subscribed", [False, True])
async def test_old_nomad_button_opens_new_panel_without_changing_consent(
    *, subscribed: bool
) -> None:
    handler, store, registration = _handler()
    member_id = uuid4()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status="active")
    preferences = {"tasks": True, "nomad": subscribed, "revision": 4}
    store.preferences.side_effect = lambda _: dict(preferences)

    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": NOMAD_SUBSCRIBE_BUTTON}
    await handler.handle(json.dumps({"update_id": 14, "message": message}).encode())
    store.set_preference.assert_not_awaited()
    assert preferences["tasks"] is True
    registration.start.assert_not_awaited()
    reply = cast("AsyncMock", handler.bot).send_message.call_args.kwargs
    assert (
        reply["reply_markup"].inline_keyboard[0][0].callback_data
        == f"subscription:nomad:{int(not subscribed)}:4"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("subscribed", [False, True])
async def test_nomad_status_button_only_opens_current_subscription(*, subscribed: bool) -> None:
    handler, store, _ = _handler()
    store.member_for_telegram.return_value = SimpleNamespace(id=uuid4(), status="active")
    store.preferences.return_value = {"tasks": False, "nomad": subscribed, "revision": 3}
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": NOMAD_SUBSCRIBED_BUTTON}
    await handler.handle(json.dumps({"update_id": 15, "message": message}).encode())
    store.set_preference.assert_not_awaited()
    reply = cast("AsyncMock", handler.bot).send_message.call_args.kwargs
    button = reply["reply_markup"].inline_keyboard[0][0]
    assert button.text == ("Отписаться" if subscribed else "Подписаться")
    assert button.callback_data == f"subscription:nomad:{int(not subscribed)}:3"


@pytest.mark.asyncio
async def test_nomad_subscribe_conflict_displays_actual_state() -> None:
    handler, store, _ = _handler()
    store.member_for_telegram.return_value = SimpleNamespace(id=uuid4(), status="active")
    store.set_preference.side_effect = PreferencesConflictError()
    callback = {
        "id": "conflict",
        "chat_instance": "test",
        "from": _post()["from"],
        "data": "subscription:nomad:1:0",
        "message": {**_post(), "chat": {"id": 456, "type": "private"}},
    }
    await handler.handle(json.dumps({"update_id": 16, "callback_query": callback}).encode())
    reply = cast("AsyncMock", handler.bot).edit_message_text.call_args.kwargs
    assert "актуальное состояние" in reply["text"]
    assert reply["reply_markup"].inline_keyboard[0][0].text == "Подписаться"


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["nomad", "notifications"])
async def test_nomad_unsubscribe_edits_panel_without_extra_messages(prefix: str) -> None:
    handler, store, _ = _handler()
    member_id = uuid4()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status="active")
    preferences = {"tasks": False, "nomad": True, "revision": 1}
    store.preferences.side_effect = lambda _: dict(preferences)

    async def save(*_: object) -> None:
        preferences.update(nomad=False, revision=2)

    store.set_preference.side_effect = save
    callback = {
        "id": "unsubscribe",
        "chat_instance": "test",
        "from": _post()["from"],
        "data": f"{prefix}:nomad:0:1",
        "message": {**_post(), "chat": {"id": 456, "type": "private"}},
    }
    await handler.handle(json.dumps({"update_id": 17, "callback_query": callback}).encode())
    store.set_preference.assert_awaited_once_with(member_id, "nomad", False, 1)  # noqa: FBT003
    cast("AsyncMock", handler.bot).send_message.assert_not_awaited()
    reply = cast("AsyncMock", handler.bot).edit_message_text.call_args.kwargs
    assert reply["reply_markup"].inline_keyboard[0][0].text == "Подписаться"
    cast("AsyncMock", handler.bot).edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("label", [NOMAD_SUBSCRIBE_BUTTON, NOMAD_SUBSCRIBED_BUTTON])
@pytest.mark.parametrize("status", [None, "pending", "banned", "left"])
async def test_nomad_requires_active_registration(label: str, status: str | None) -> None:
    handler, store, registration = _handler()
    store.member_for_telegram.return_value = (
        SimpleNamespace(id=uuid4(), status=status) if status else None
    )
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": label}
    await handler.handle(json.dumps({"update_id": 18, "message": message}).encode())
    store.set_preference.assert_not_awaited()
    store.preferences.assert_not_awaited()
    registration.start.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("label", [APP_BUTTON, "📱 Приложение", NOTIFICATIONS_BUTTON])
async def test_bottom_menu_buttons_need_no_typed_command(label: str) -> None:
    handler, store, registration = _handler()
    store.member_for_telegram.return_value = SimpleNamespace(id=uuid4(), status="active")
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": label}
    await handler.handle(json.dumps({"update_id": 12, "message": message}).encode())
    reply = cast("AsyncMock", handler.bot).send_message.call_args.kwargs
    registration.start.assert_not_awaited()
    if label in {APP_BUTTON, "📱 Приложение"}:
        headings = [
            "Задания и взаимопомощь",
            "Статистика сообщества",
            "Ачивки и рекорды",
            "Кредиты и кошелёк",
        ]
        positions = [reply["text"].index(heading) for heading in headings]
        assert positions == sorted(positions)
        assert reply["text"].startswith("🤝 Задания и взаимопомощь")
        for example in ("солопренёров", "соцсетей", "GitHub", "консультаций", "знакомств"):
            assert example in reply["text"]
        assert "уведомлен" not in reply["text"].lower()
        assert "20 кредитов" in reply["text"]
        assert "50 кредитов" in reply["text"]
        assert len(reply["text"]) < 4096
        assert reply["reply_markup"].inline_keyboard[0][0].text == "Открыть приложение"
        assert (
            reply["reply_markup"].inline_keyboard[0][0].url
            == "https://t.me/humanquest_bot?startapp"
        )
    else:
        assert "Активности и подписки" in reply["text"]
        assert reply["reply_markup"].inline_keyboard[0][0].text == "☐ Онлайн-встречи"
    store.set_preference.assert_not_awaited()


@pytest.mark.asyncio
async def test_bottom_menu_rechecks_membership_before_preferences() -> None:
    handler, store, _ = _handler()
    cast("AsyncMock", handler.membership).is_member.return_value = False
    message = {**_post(), "chat": {"id": 456, "type": "private"}, "text": NOTIFICATIONS_BUTTON}
    await handler.handle(json.dumps({"update_id": 13, "message": message}).encode())
    store.preferences.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_routes_auth_origin_revision_and_webhook_secret() -> None:
    app, store, telegram = FastAPI(), AsyncMock(), AsyncMock()
    member_id = uuid4()

    async def actor(request: Request) -> ActorContext:
        if request.headers.get("authorization") != "test":
            raise HTTPException(401)
        return ActorContext(member_id, "telegram", datetime.datetime.now(datetime.UTC))

    def origin(request: Request) -> None:
        if request.headers.get("origin") != "https://mini.example":
            raise HTTPException(403)

    store.preferences.return_value = {"tasks": True, "nomad": False, "revision": 0}
    store.set_policy.return_value = {"mode": "simplified", "revision": 1}
    install_community_settings_routes(
        app,
        store=store,
        current_actor=actor,
        require_origin=origin,
        telegram=telegram,
        webhook_secret="test-webhook-secret",  # noqa: S106 - isolated fixture, not credentials.
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://mini.example"
    ) as client:
        assert (await client.get("/api/v1/notification-preferences")).status_code == 401
        client.headers["authorization"] = "test"
        assert (await client.get("/api/v1/notification-preferences")).json()["tasks"] is True
        path = "/api/v1/administration/registration-policy"
        assert (await client.patch(path, json={})).status_code == 403
        client.headers["origin"] = "https://mini.example"
        assert (
            await client.patch(path, json={"mode": "simplified", "expected_revision": 0})
        ).status_code == 422
        assert (
            await client.patch(
                path, json={"mode": "simplified", "expected_revision": 0, "confirmed": True}
            )
        ).status_code == 200
        assert (await client.post("/api/telegram/webhook", json={})).status_code == 403
        assert (
            await client.post(
                "/api/telegram/webhook",
                json={"update_id": 1},
                headers={"x-telegram-bot-api-secret-token": "test-webhook-secret"},
            )
        ).status_code == 200
    telegram.handle.assert_awaited_once()
