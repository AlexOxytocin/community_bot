from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.application.registration import RegistrationService, RegistrationStartCommand
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import Settings
from community_bot.domain.community_preferences import PreferencesConflictError
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db.community_preferences import (
    CommunityPreferencesStore,
    subscription_allows,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AuditEventModel,
    MemberModel,
    MemberNotificationPreferencesModel,
    NotificationModel,
    RegistrationApplicationModel,
)
from community_bot.infrastructure.outbox.postgres import PostgresNotificationQueue
from community_bot.transport.web import create_web_app

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
CommunityFixture = tuple[Database, CommunityPreferencesStore, MemberModel, MemberModel]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def community(database_url: str) -> AsyncIterator[CommunityFixture]:
    db = Database(database_url)
    async with db.session_factory.begin() as session:
        owner = MemberModel(
            telegram_user_id=450,
            display_name="Owner",
            timezone="UTC",
            status="active",
            role="administrator",
            permissions_json=["superadministrator"],
            level_number=1,
        )
        reader = MemberModel(
            telegram_user_id=451,
            display_name="Reader",
            timezone="UTC",
            status="active",
            role="member",
            level_number=1,
        )
        session.add_all([owner, reader])
    try:
        yield db, CommunityPreferencesStore(db.session_factory), owner, reader
    finally:
        await db.dispose()


async def test_simplified_registration_serializes_identity_grant_and_policy(
    community: CommunityFixture,
) -> None:
    db, store, owner, _ = community
    await ProductConfigBootstrapCoordinator(db.unit_of_work, load_product_config_candidate).prepare(
        candidate_path=Path(__file__).parents[2] / "config/product-config.v1.json",
        actor_member_id=owner.id,
        activation_command_id=uuid4(),
        reason="Registration fixture",
    )
    assert await store.policy(owner.id) == {"mode": "standard", "revision": 0}
    await store.set_policy(owner.id, "simplified", 0)
    service = RegistrationService(db.unit_of_work)

    def command(update_id: int) -> RegistrationStartCommand:
        return RegistrationStartCommand(
            update_id=update_id,
            telegram_user_id=452,
            telegram_username=None,
            telegram_display_name="Telegram Name",
            community_membership_verified=True,
        )

    await _concurrent_bot_and_web_entry(db)
    await service.start(command(1))
    async with db.session_factory() as session:
        member = await session.scalar(
            select(MemberModel).where(MemberModel.telegram_user_id == 452)
        )
        assert member is not None
        assert (member.display_name, member.city, member.timezone, member.status) == (
            "Telegram Name",
            None,
            "UTC",
            "active",
        )
        grants = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.member_id == member.id
                )
            )
        ).all()
        assert len(grants) == 1
        assert grants[0].credit_delta == 20
        application = await session.get(RegistrationApplicationModel, member.id)
        assert application is not None
        assert application.consented_at is None
    # Returning to standard mode never deletes or re-registers an existing account.
    await store.set_policy(owner.id, "standard", 1)
    resumed = await service.start(command(3))
    assert resumed.context is not None
    assert resumed.context.member_id == member.id
    with pytest.raises(PreferencesConflictError):
        await store.set_policy(owner.id, "simplified", 0)
    async with db.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.action == "registration_policy_changed")
            )
            == 2
        )


async def _concurrent_bot_and_web_entry(db: Database) -> None:
    bot_token = "123456:isolated-test-token"  # noqa: S105
    webhook_secret = "isolated-test-webhook-secret-32-characters"  # noqa: S105
    origin = "https://mini.example"
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    user = {"id": 452, "first_name": "Telegram Name", "is_bot": False}
    fields = {"auth_date": str(now), "user": json.dumps(user)}
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        "\n".join(f"{key}={value}" for key, value in sorted(fields.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    app = create_web_app(
        settings=Settings(
            _env_file=None,
            bot_token=bot_token,
            mini_app_origin=origin,
            telegram_bot_username="humanquest_bot",
            telegram_webhook_secret=webhook_secret,
            community_telegram_chat_id=-1002237685639,
            community_telegram_join_url="https://t.me/+test",
        ),
        database=db,
        membership_checker=AsyncMock(is_member=AsyncMock(return_value=True)),
        telegram_bot=AsyncMock(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        bot_response, web_response = await asyncio.gather(
            client.post(
                "/api/telegram/webhook",
                headers={
                    "x-telegram-bot-api-secret-token": webhook_secret,
                },
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 1,
                        "date": now,
                        "from": user,
                        "chat": {"id": 452, "type": "private"},
                        "text": "/start",
                    },
                },
            ),
            client.post(
                "/api/v1/auth/telegram",
                content=urlencode(fields).encode(),
                headers={"origin": origin, "content-type": "text/plain; charset=utf-8"},
            ),
        )
        assert bot_response.status_code == 200
        assert web_response.status_code == 204
        preferences = await client.get("/api/v1/notification-preferences")
        assert preferences.json() == {"tasks": False, "nomad": False, "revision": 0}


async def test_preferences_serialize_devices_and_preserve_defaults(
    community: CommunityFixture,
) -> None:
    db, store, owner, reader = community
    assert await store.preferences(reader.id) == {"tasks": False, "nomad": False, "revision": 0}
    changes = await asyncio.gather(
        store.set_preference(reader.id, "nomad", enabled=True, expected_revision=0),
        store.set_preference(reader.id, "tasks", enabled=True, expected_revision=0),
        return_exceptions=True,
    )
    assert sum(isinstance(result, PreferencesConflictError) for result in changes) == 1
    current = await CommunityPreferencesStore(db.session_factory).preferences(reader.id)
    assert current["revision"] == 1
    with pytest.raises(PermissionError):
        await store.set_policy(reader.id, "simplified", 0)
    assert (await store.policy(owner.id))["mode"] == "standard"


async def test_task_notifications_require_opt_in_and_saved_choices_survive(
    community: CommunityFixture,
) -> None:
    db, store, _, reader = community
    now = datetime.datetime.now(datetime.UTC)
    async with db.session_factory.begin() as session:
        assert not await subscription_allows(session, reader.id, "task.published", now)
        await session.execute(
            insert(MemberNotificationPreferencesModel).values(member_id=reader.id)
        )
    assert (await store.preferences(reader.id))["tasks"] is False
    enabled = await store.set_preference(reader.id, "tasks", enabled=True, expected_revision=0)
    revision = enabled["revision"]
    assert isinstance(revision, int)
    await store.set_preference(reader.id, "nomad", enabled=True, expected_revision=revision)
    assert (await store.preferences(reader.id))["tasks"] is True
    async with db.session_factory() as session:
        assert await subscription_allows(
            session, reader.id, "task.published", datetime.datetime.now(datetime.UTC)
        )
        assert not await subscription_allows(session, reader.id, "task.published", now)


async def test_nomad_outbox_dedup_and_unsubscribe_before_send(community: CommunityFixture) -> None:
    db, store, owner, reader = community
    await store.set_preference(reader.id, "nomad", enabled=True, expected_revision=0)
    now = datetime.datetime.now(datetime.UTC)
    post: dict[str, Any] = dict(  # noqa: C408 - named Telegram event fields.
        author_id=owner.telegram_user_id,
        chat_id=-1002237685639,
        topic_id=24962,
        message_id=24968,
        published_at=now,
        album_id="album-one",
    )
    assert await store.publish_nomad(**post)
    post["message_id"] = 24969
    assert not await store.publish_nomad(**post)
    post.update(author_id=reader.telegram_user_id, album_id=None)
    assert not await store.publish_nomad(**post)
    queue = PostgresNotificationQueue(db.session_factory)
    claims = await queue.claim_outbox(
        now=now + datetime.timedelta(seconds=1),
        limit=10,
        lease_duration=datetime.timedelta(minutes=2),
    )
    assert len(claims) == 1
    await queue.materialize(
        claims[0], now=now + datetime.timedelta(seconds=1), window=DeliveryWindow()
    )
    async with db.session_factory() as session:
        rows = (await session.scalars(select(NotificationModel))).all()
        assert len(rows) == 1
        assert rows[0].member_id == reader.id
        assert rows[0].payload_json["message_url"] == "https://t.me/c/2237685639/24962/24968"
    deliveries = await queue.claim_notifications(
        now=now + datetime.timedelta(days=1), limit=10, lease_duration=datetime.timedelta(minutes=2)
    )
    assert len(deliveries) == 1
    assert await store.allows_delivery(deliveries[0].id)
    await store.set_preference(reader.id, "nomad", enabled=False, expected_revision=1)
    assert not await store.allows_delivery(deliveries[0].id)
    await store.set_preference(reader.id, "nomad", enabled=True, expected_revision=2)
    assert not await store.allows_delivery(deliveries[0].id)
    reclaimed = await queue.claim_notifications(
        now=now + datetime.timedelta(days=2), limit=10, lease_duration=datetime.timedelta(minutes=2)
    )
    assert not reclaimed
