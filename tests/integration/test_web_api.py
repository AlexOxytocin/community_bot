from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from PIL import Image
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from community_bot.application import assignments as assignment_app
from community_bot.application.community_stats import (
    AchievementProgress,
    ActivityBucket,
    ActivityValues,
    CommunityStatsUnavailableError,
    Pulse,
    ReactionBreakdown,
    StatsLeaderboard,
    StatsLeaderboardItem,
)
from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.application.membership import ResolvedTelegramResource, TelegramProfilePhoto
from community_bot.application.registration import (
    InvitationCreateCommand,
    InviteTokenCodec,
    RegistrationService,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import Settings
from community_bot.domain.members import (
    ADMINISTRATOR_MANAGEMENT_PERMISSION,
    ADMINISTRATOR_PERMISSIONS,
    COMMUNITY_TASK_CREATE_PERMISSION,
    COMMUNITY_TASK_REVIEW_PERMISSION,
    MEMBER_INVITATION_PERMISSION,
    SUPERADMINISTRATOR_PERMISSION,
    MemberRole,
    MemberStatus,
)
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AccountTransactionModel,
    AssignmentDisputeModel,
    AssignmentModel,
    AssignmentResultVersionModel,
    AssignmentSubmissionDraftModel,
    AuditEventModel,
    ConversationStateModel,
    DisputeEvidenceModel,
    DisputeResolutionModel,
    InvitationMembershipResourceModel,
    InvitationModel,
    InvitationRedemptionModel,
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberAvatarModel,
    MemberModel,
    MemberSanctionModel,
    MembershipResourceModel,
    ModerationCaseModel,
    NotificationModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    RegistrationApplicationModel,
    ReliabilityEventModel,
    TaskCategoryModel,
    TaskCreationDraftModel,
    TaskModel,
    TaskTemplateModel,
    WebSessionModel,
)
from community_bot.infrastructure.db.models import TestRunModel as DbTestRunModel
from community_bot.infrastructure.db.models import (
    TestRunParticipantModel as DbTestRunParticipantModel,
)
from community_bot.infrastructure.outbox.postgres import PostgresNotificationQueue
from community_bot.transport.web import _accept_update_id, _submission_update_id, create_web_app
from tests.integration.test_assignments import _community_task, _freeform_task, _published_task
from tests.integration.test_moderation import _open_dispute_fixture
from tests.integration.test_reputation import add_member, add_paid_interaction, prepare_config
from tests.integration.test_task_creation import prepare_member

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BOT_TOKEN = "123456:INTEGRATION_TOKEN"
ORIGIN = "https://mini.example"
CONFIG_PATH = Path(__file__).parents[2] / "config" / "product-config.v1.json"
PROJECT_ROOT = Path(__file__).parents[2]


_USERNAME_ABSENT = object()


class FakeMembershipChecker:
    """Controllable Telegram membership boundary for integration tests."""

    def __init__(self) -> None:
        """Start available and retain exact outbound request arguments."""
        """Start with no confirmed chat members."""
        self.members: set[tuple[int, int]] = set()
        self.profile_photos: dict[int, TelegramProfilePhoto] = {}
        self.profile_photo_requests: list[int] = []
        self.resolved_chat = ResolvedTelegramResource(
            telegram_chat_id=-100_200,
            telegram_username="extra_resource",
            title="Дополнительный ресурс",  # noqa: RUF001
        )

    async def is_member(self, *, chat_id: int, telegram_user_id: int) -> bool:
        """Return the configured membership decision."""
        return (chat_id, telegram_user_id) in self.members

    async def resolve_chat(self, reference: str) -> ResolvedTelegramResource:
        """Return one pre-validated chat."""
        del reference
        return self.resolved_chat

    async def profile_photo(self, telegram_user_id: int) -> TelegramProfilePhoto | None:
        """Return a configured profile photo and record the server-side lookup."""
        self.profile_photo_requests.append(telegram_user_id)
        return self.profile_photos.get(telegram_user_id)

    async def close(self) -> None:
        """Match the production adapter lifecycle."""
        return


class FakeCommunityStatsGateway:
    """Record authorized private reads without any external network call."""

    def __init__(self) -> None:
        """Start available and retain exact outbound request arguments."""
        self.pulse_requests: list[dict[str, object]] = []
        self.leaderboard_requests: list[dict[str, object]] = []
        self.unavailable = False

    async def pulse(self, **request) -> Pulse:  # noqa: ANN003
        """Return deterministic pulse data or the configured outage."""
        self.pulse_requests.append(request)
        if self.unavailable:
            raise CommunityStatsUnavailableError
        return Pulse(
            tracking_started_at=datetime.datetime(2026, 8, 28, tzinfo=datetime.UTC),
            calculated_at=datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.UTC),
            summary=ActivityValues(7, 3, 4),
            series=(ActivityBucket(7, 3, 4, datetime.date(2026, 8, 28)),),
            reaction_breakdown=(ReactionBreakdown({"type": "emoji", "emoji": "👍"}, 3, 4),),
            achievements=(
                AchievementProgress(
                    code="speaker",
                    level=1,
                    current=10,
                    next_level_at=30,
                    unlocked=True,
                ),
            ),
        )

    async def leaderboard(self, **request) -> StatsLeaderboard:  # noqa: ANN003
        """Return one mapped and one unknown Telegram identity."""
        self.leaderboard_requests.append(request)
        if self.unavailable:
            raise CommunityStatsUnavailableError
        return StatsLeaderboard(
            items=(
                StatsLeaderboardItem(52_081, 9, 1),
                StatsLeaderboardItem(99_999, 8, 2),
            ),
            tracking_started_at=datetime.datetime(2026, 8, 28, tzinfo=datetime.UTC),
            calculated_at=datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.UTC),
        )

    async def close(self) -> None:
        """Match the production gateway lifecycle."""
        return


def proof(
    user_id: int, *, now: datetime.datetime, username: str | object | None = _USERNAME_ABSENT
) -> bytes:
    user = {"id": user_id, "first_name": "Web"}
    if username is not _USERNAME_ABSENT:
        user["username"] = username
    fields = {
        "auth_date": str(int(now.timestamp())),
        "query_id": "integration-query",
        "user": json.dumps(user, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields).encode()


async def active_member(database: Database, telegram_user_id: int) -> MemberModel:
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        member = MemberModel(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            telegram_username="web_member",
            display_name="Web Member",
            timezone="UTC",
            role=MemberRole.ADMINISTRATOR.value,
            status=MemberStatus.ACTIVE.value,
            permissions_json=sorted(ADMINISTRATOR_PERMISSIONS),
        )
        session.add(member)
        await session.flush()
    coordinator = ProductConfigBootstrapCoordinator(
        database.unit_of_work, load_product_config_candidate
    )
    await coordinator.prepare(
        candidate_path=CONFIG_PATH,
        actor_member_id=member.id,
        activation_command_id=uuid4(),
        reason="Web API integration config.",
    )
    return member


async def test_community_stats_connects_history_after_member_registration(
    database_url: str,
) -> None:
    database = Database(database_url)
    actor = await active_member(database, 52_080)
    gateway = FakeCommunityStatsGateway()
    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            database_url=database_url,
            community_telegram_chat_id=-100_200,
            community_telegram_join_url="https://t.me/community_test",
        ),
        database=database,
        community_stats_gateway=gateway,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(actor.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204

        before_registration = await client.get(
            "/api/v1/community-stats/leaderboard",
            params={"period": "all", "metric": "messages"},
        )
        assert before_registration.status_code == 200, before_registration.text
        assert before_registration.json()["items"] == []

        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions.begin() as session:
            target = MemberModel(
                id=uuid4(),
                telegram_user_id=52_081,
                telegram_username="stats_target",
                display_name="Stats Target",
                timezone="UTC",
                role=MemberRole.MEMBER.value,
                status=MemberStatus.ACTIVE.value,
                permissions_json=[],
            )
            session.add(target)
            await session.flush()
            category_id = await session.scalar(select(TaskCategoryModel.id).limit(1))
            assert category_id is not None
            published_at = datetime.datetime.now(datetime.UTC)
            for index in range(5):
                session.add(
                    TaskModel(
                        origin="member",
                        creator_id=target.id,
                        author_display_name=target.display_name,
                        category_id=category_id,
                        time_size="s",
                        title=f"Stats achievement task {index + 1}",
                        description="Published task counted by the Manager achievement.",
                        completion_criteria="Return a concrete result.",
                        materials_json={},
                        input_payload_json={},
                        credit_reward_per_performer=2,
                        performer_slots=1,
                        reserved_credit_total=2,
                        estimated_minutes=20,
                        minimum_level=1,
                        format="online",
                        deadline_at=published_at + datetime.timedelta(days=1),
                        status="published",
                        safety_snapshot_json={},
                        publish_command_id=uuid4(),
                        published_at=published_at,
                    )
                )
            transaction_time = published_at - datetime.timedelta(minutes=5)
            session.add_all(
                [
                    AccountTransactionModel(
                        member_id=target.id,
                        credit_delta=10,
                        experience_delta=0,
                        transaction_type="starting_grant",
                        idempotency_key=f"stats-achievement:{target.id}:starting",
                        payload_hash="a" * 64,
                        created_at=transaction_time,
                    ),
                    AccountTransactionModel(
                        member_id=target.id,
                        credit_delta=75,
                        experience_delta=0,
                        transaction_type="manual_credit_grant",
                        idempotency_key=f"stats-achievement:{target.id}:grant",
                        payload_hash="b" * 64,
                        created_by_member_id=actor.id,
                        reason="Integration achievement fixture.",
                        created_at=transaction_time + datetime.timedelta(seconds=1),
                    ),
                    AccountTransactionModel(
                        member_id=target.id,
                        credit_delta=-45,
                        experience_delta=0,
                        transaction_type="admin_adjustment",
                        idempotency_key=f"stats-achievement:{target.id}:spend",
                        payload_hash="c" * 64,
                        created_by_member_id=actor.id,
                        reason="Integration achievement fixture.",
                        created_at=transaction_time + datetime.timedelta(seconds=2),
                    ),
                ]
            )
            target.credit_balance_cached = 40

        pulse = await client.get(
            "/api/v1/community-stats/pulse",
            params={"member_id": str(target.id), "period": "week", "topic_id": 321},
        )
        assert pulse.status_code == 200, pulse.text
        assert pulse.json()["member_id"] == str(target.id)
        assert pulse.json()["summary"] == {
            "messages": 7,
            "reactions_given": 3,
            "reactions_received": 4,
        }
        achievements = {item["code"]: item for item in pulse.json()["achievements"]}
        assert achievements["wealth"] == {
            "code": "wealth",
            "level": 3,
            "current": 70,
            "next_level_at": 100,
            "unlocked": True,
        }
        assert achievements["manager"] == {
            "code": "manager",
            "level": 3,
            "current": 5,
            "next_level_at": 10,
            "unlocked": True,
        }
        assert gateway.pulse_requests == [
            {
                "chat_id": -100_200,
                "user_id": target.telegram_user_id,
                "period": "week",
                "topic_id": 321,
            }
        ]

        hidden = await client.get(
            "/api/v1/community-stats/pulse",
            params={"member_id": str(uuid4()), "period": "week"},
        )
        assert hidden.status_code == 404
        assert len(gateway.pulse_requests) == 1

        leaderboard = await client.get(
            "/api/v1/community-stats/leaderboard",
            params={"period": "month", "metric": "messages", "topic_id": 321},
        )
        assert leaderboard.status_code == 200, leaderboard.text
        assert leaderboard.json()["items"] == [
            {
                "member_id": str(target.id),
                "display_name": "Stats Target",
                "value": 9,
                "rank": 1,
            }
        ]
        assert gateway.leaderboard_requests[1]["topic_id"] == 321
        native = await client.get(
            "/api/v1/community-stats/leaderboard",
            params={"period": "all", "metric": "karma"},
        )
        assert native.status_code == 200, native.text
        assert {item["member_id"] for item in native.json()["items"]} == {
            str(actor.id),
            str(target.id),
        }
        assert len(gateway.leaderboard_requests) == 2
        wealth_ranking = await client.get(
            "/api/v1/community-stats/leaderboard",
            params={"period": "all", "metric": "achievement:wealth"},
        )
        assert wealth_ranking.status_code == 200, wealth_ranking.text
        assert wealth_ranking.json()["items"] == [
            {
                "member_id": str(target.id),
                "display_name": "Stats Target",
                "value": 3,
                "rank": 1,
            }
        ]
        assert len(gateway.leaderboard_requests) == 2
        assert (
            await client.get(
                "/api/v1/community-stats/leaderboard",
                params={
                    "period": "all",
                    "metric": "achievement:speaker",
                    "topic_id": 321,
                },
            )
        ).status_code == 422

        gateway.unavailable = True
        unavailable = await client.get("/api/v1/community-stats/pulse", params={"period": "week"})
        assert unavailable.status_code == 503
        assert unavailable.json() == {"code": "community_stats_unavailable"}


async def test_onboarding_uses_invitation_restricts_pending_and_activates_after_review(
    database_url: str,
) -> None:
    database = Database(database_url)
    administrator = await active_member(database, 52_070)
    secret = "integration-onboarding-secret-that-is-long-enough"
    codec = InviteTokenCodec(secret)
    service = RegistrationService(database.unit_of_work, codec)
    invitation = await service.create_invitation(
        InvitationCreateCommand(
            update_id=70_001,
            actor_telegram_user_id=administrator.telegram_user_id,
            intended_telegram_user_id=52_071,
        )
    )
    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            database_url=database_url,
            invite_token_secret=secret,
        ),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(52_071, now=datetime.datetime.now(datetime.UTC)),
            headers={
                "content-type": "text/plain; charset=utf-8",
                "origin": ORIGIN,
                "x-community-invitation": invitation.token,
            },
        )
        assert authenticated.status_code == 204, authenticated.text
        assert (await client.get("/api/v1/me")).status_code == 403
        assert (await client.get("/api/v1/tasks")).status_code == 403
        assert (await client.get("/api/v1/task-cities?q=Buenos&limit=3")).status_code == 200

        state = (await client.get("/api/v1/onboarding")).json()
        assert (state["application_status"], state["step"], state["payload"]) == (
            "draft",
            "consent",
            {},
        )

        async def answer(step: str, value: str, key: int) -> dict[str, object]:
            response = await client.post(
                "/api/v1/onboarding/answer",
                json={"step": step, "value": value},
                headers={"origin": ORIGIN, "idempotency-key": str(key)},
            )
            assert response.status_code == 200, response.text
            return response.json()

        assert (await answer("consent", "accept", 70_010))["step"] == "display_name"
        assert (await answer("display_name", "Новый участник", 70_011))["step"] == "city"
        city = await answer("city", "Buenos Aires — Argentina", 70_012)
        assert city["step"] == "short_bio"
        city_payload = city["payload"]
        assert isinstance(city_payload, dict)
        assert city_payload["timezone"] == "America/Argentina/Buenos_Aires"
        returned = await client.post(
            "/api/v1/onboarding/back",
            headers={"origin": ORIGIN, "idempotency-key": "70013"},
        )
        assert returned.status_code == 200
        assert returned.json()["step"] == "city"
        assert returned.json()["payload"]["city"] == "Buenos Aires — Argentina"
        await answer("city", "Buenos Aires — Argentina", 70_014)
        await answer("short_bio", "Тестирую регистрацию нового участника.", 70_015)
        preview = await answer("skill_tags", "QA\nTelegram Mini Apps", 70_016)
        assert preview["step"] == "preview"

        submitted = await client.post(
            "/api/v1/onboarding/submit",
            headers={"origin": ORIGIN, "idempotency-key": "70017"},
        )
        replay = await client.post(
            "/api/v1/onboarding/submit",
            headers={"origin": ORIGIN, "idempotency-key": "70017"},
        )
        assert submitted.status_code == replay.status_code == 200
        assert submitted.json()["application_status"] == "submitted"
        assert replay.json() == submitted.json()

        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session:
            pending = await session.scalar(
                select(MemberModel).where(MemberModel.telegram_user_id == 52_071)
            )
            assert pending is not None
            assert pending.status == MemberStatus.PENDING.value
            target_member_id = pending.id
            assert await session.scalar(select(func.count(InvitationRedemptionModel.id))) == 1
            application_count = await session.scalar(
                select(func.count(RegistrationApplicationModel.member_id))
            )
            assert application_count == 1

        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as admin_client:
            admin_auth = await admin_client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    administrator.telegram_user_id,
                    now=datetime.datetime.now(datetime.UTC),
                ),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert admin_auth.status_code == 204
            queue = await admin_client.get("/api/v1/moderation/registrations?limit=20")
            assert queue.status_code == 200
            assert queue.json()["items"] == [
                {
                    "member_id": str(target_member_id),
                    "telegram_username": None,
                    "display_name": "Новый участник",
                    "city": "Buenos Aires — Argentina",
                    "timezone": "America/Argentina/Buenos_Aires",
                    "short_bio": "Тестирую регистрацию нового участника.",
                    "skill_tags": ["QA", "Telegram Mini Apps"],
                }
            ]
            rejected_response = await admin_client.post(
                f"/api/v1/moderation/registrations/{target_member_id}/decision",
                headers={"origin": ORIGIN, "idempotency-key": "70024"},
                json={"decision": "reject", "comment": "Уточните описание профиля."},
            )
            assert rejected_response.status_code == 204
            assert (await admin_client.get("/api/v1/moderation/registrations")).json() == {
                "items": []
            }
        rejected = (await client.get("/api/v1/onboarding")).json()
        assert rejected["application_status"] == "rejected"
        assert rejected["review_comment"] == "Уточните описание профиля."
        reopened = await client.post(
            "/api/v1/onboarding/reopen",
            headers={"origin": ORIGIN, "idempotency-key": "70017"},
        )
        assert reopened.status_code == 200
        assert (reopened.json()["application_status"], reopened.json()["step"]) == (
            "draft",
            "display_name",
        )
        await answer("display_name", "Новый участник", 70_018)
        await answer("city", "Buenos Aires — Argentina", 70_019)
        await answer("short_bio", "", 70_020)
        await answer("skill_tags", "", 70_021)
        resubmitted = await client.post(
            "/api/v1/onboarding/submit",
            headers={"origin": ORIGIN, "idempotency-key": "70022"},
        )
        assert resubmitted.status_code == 200
        assert resubmitted.json()["application_status"] == "submitted"

        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as admin_client:
            admin_auth = await admin_client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    administrator.telegram_user_id,
                    now=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1),
                ),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert admin_auth.status_code == 204
            approved_response = await admin_client.post(
                f"/api/v1/moderation/registrations/{target_member_id}/decision",
                headers={"origin": ORIGIN, "idempotency-key": "70025"},
                json={"decision": "approve", "comment": None},
            )
            assert approved_response.status_code == 204
        profile = await client.get("/api/v1/me")
        assert profile.status_code == 200, profile.text
        assert profile.json()["display_name"] == "Новый участник"
        assert profile.json()["timezone"] == "America/Argentina/Buenos_Aires"
        assert profile.json()["short_bio"] is None
        assert profile.json()["skill_tags"] == []
        assert (await client.get("/api/v1/tasks")).status_code == 200

    await database.dispose()


async def test_personal_invitation_is_username_bound_one_use_and_auto_approves(
    database_url: str,
) -> None:
    database = Database(database_url)
    administrator = await active_member(database, 52_090)
    secret = "personal-invitation-secret-that-is-long-enough"
    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            telegram_bot_username="community_test_bot",
            mini_app_origin=ORIGIN,
            database_url=database_url,
            invite_token_secret=secret,
        ),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as admin_client:
        assert (
            await admin_client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    administrator.telegram_user_id,
                    now=datetime.datetime.now(datetime.UTC),
                    username="web_member",
                ),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        created = await admin_client.post(
            "/api/v1/administration/invitations",
            json={"telegram_username": "New_User"},
            headers={"origin": ORIGIN, "idempotency-key": "90001"},
        )
        assert created.status_code == 201, created.text
        created_payload = created.json()
        assert created_payload["telegram_username"] == "new_user"
        assert created_payload["invitation_url"].startswith(
            "https://t.me/community_test_bot?startapp="
        )
        token = parse_qs(urlsplit(created_payload["invitation_url"]).query)["startapp"][0]
        listed = (await admin_client.get("/api/v1/administration/invitations")).json()
        assert listed["pending_count"] == 1
        assert listed["items"][0]["status"] == "waiting"

        revoked_created = await admin_client.post(
            "/api/v1/administration/invitations",
            json={"telegram_username": "@revoked_user"},
            headers={"origin": ORIGIN, "idempotency-key": "90002"},
        )
        assert revoked_created.status_code == 201
        revoked_payload = revoked_created.json()
        revoked = await admin_client.post(
            f"/api/v1/administration/invitations/{revoked_payload['invitation_id']}/revoke",
            json={},
            headers={"origin": ORIGIN, "idempotency-key": "90003"},
        )
        assert revoked.status_code == 204
        after_revoke = (await admin_client.get("/api/v1/administration/invitations")).json()
        revoked_item = next(
            item
            for item in after_revoke["items"]
            if item["invitation_id"] == revoked_payload["invitation_id"]
        )
        assert revoked_item["status"] == "revoked"
        revoked_token = parse_qs(urlsplit(revoked_payload["invitation_url"]).query)["startapp"][0]
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as revoked_client:
            revoked_attempt = await revoked_client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    52_094,
                    now=datetime.datetime.now(datetime.UTC),
                    username="revoked_user",
                ),
                headers={
                    "content-type": "text/plain; charset=utf-8",
                    "origin": ORIGIN,
                    "x-community-invitation": revoked_token,
                },
            )
            assert revoked_attempt.status_code == 403

        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as wrong_client:
            mismatch = await wrong_client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    52_091,
                    now=datetime.datetime.now(datetime.UTC),
                    username="other_user",
                ),
                headers={
                    "content-type": "text/plain; charset=utf-8",
                    "origin": ORIGIN,
                    "x-community-invitation": token,
                },
            )
            assert mismatch.status_code == 403
            assert mismatch.json() == {"code": "invalid_invitation"}

        contenders = [
            AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) for _ in range(2)
        ]
        try:
            responses = await asyncio.gather(
                *(
                    contender.post(
                        "/api/v1/auth/telegram",
                        content=proof(
                            52_092 + index,
                            now=datetime.datetime.now(datetime.UTC),
                            username="NEW_USER",
                        ),
                        headers={
                            "content-type": "text/plain; charset=utf-8",
                            "origin": ORIGIN,
                            "x-community-invitation": token,
                        },
                    )
                    for index, contender in enumerate(contenders)
                )
            )
            assert sorted(response.status_code for response in responses) == [204, 403]
            winner_index = next(
                index for index, response in enumerate(responses) if response.status_code == 204
            )
            member_client = contenders[winner_index]
            state = (await member_client.get("/api/v1/onboarding")).json()
            assert state["personal_invitation"] is True

            async def answer(step: str, value: str, key: int) -> dict[str, object]:
                response = await member_client.post(
                    "/api/v1/onboarding/answer",
                    json={"step": step, "value": value},
                    headers={"origin": ORIGIN, "idempotency-key": str(key)},
                )
                assert response.status_code == 200, response.text
                return response.json()

            await answer("consent", "accept", 90_010)
            await answer("display_name", "Новый участник", 90_011)
            await answer("city", "Buenos Aires — Argentina", 90_012)
            await answer("short_bio", "", 90_013)
            preview = await answer("skill_tags", "", 90_014)
            assert preview["step"] == "preview"
            activated = await member_client.post(
                "/api/v1/onboarding/submit",
                headers={"origin": ORIGIN, "idempotency-key": "90015"},
            )
            assert activated.status_code == 200, activated.text
            assert activated.json()["application_status"] == "approved"
            assert (await member_client.get("/api/v1/me")).status_code == 200
        finally:
            for contender in contenders:
                await contender.aclose()

        refreshed = (await admin_client.get("/api/v1/administration/invitations")).json()
        assert refreshed["pending_count"] == 0
        joined_item = next(
            item
            for item in refreshed["items"]
            if item["invitation_id"] == created_payload["invitation_id"]
        )
        assert joined_item["status"] == "joined"
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session:
            invitation = await session.get(InvitationModel, UUID(created_payload["invitation_id"]))
            assert invitation is not None
            assert invitation.code_hash != token
            assert invitation.intended_telegram_username == "new_user"
            redemption = await session.scalar(
                select(InvitationRedemptionModel).where(
                    InvitationRedemptionModel.invitation_id == invitation.id
                )
            )
            assert redemption is not None
            member = await session.get(MemberModel, redemption.member_id)
            application = await session.get(RegistrationApplicationModel, redemption.member_id)
            assert member is not None
            assert member.status == MemberStatus.ACTIVE.value
            assert member.invited_by_member_id == administrator.id
            assert application is not None
            assert application.status == "approved"
            audit = await session.scalar(
                select(AuditEventModel).where(
                    AuditEventModel.action == "registration_auto_approved",
                    AuditEventModel.entity_id == str(member.id),
                )
            )
            assert audit is not None

    await database.dispose()


async def test_membership_requirements_do_not_consume_invite_and_recheck_on_entry(
    database_url: str,
) -> None:
    database = Database(database_url)
    owner = await active_member(database, 52_190)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        model = await session.get(MemberModel, owner.id)
        assert model is not None
        model.permissions_json = sorted(ADMINISTRATOR_PERMISSIONS | {SUPERADMINISTRATOR_PERMISSION})

    checker = FakeMembershipChecker()
    secret = "membership-invitation-secret-that-is-long-enough"
    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            telegram_bot_username="community_test_bot",
            mini_app_origin=ORIGIN,
            database_url=database_url,
            invite_token_secret=secret,
            community_telegram_chat_id=-100_100,
            community_telegram_join_url="https://t.me/allo_neural",
        ),
        database=database,
        membership_checker=checker,
    )
    checker.members.add((-100_100, owner.telegram_user_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as owner_client:
        authenticated = await owner_client.post(
            "/api/v1/auth/telegram",
            content=proof(owner.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        resources = await owner_client.get("/api/v1/administration/membership-resources")
        assert resources.status_code == 200
        assert resources.json()["items"][0]["title"] == "Алло, Нейросеточная?"
        assert resources.json()["items"][0]["required"] is True
        assert resources.json()["can_add"] is True

        added = await owner_client.post(
            "/api/v1/administration/membership-resources",
            json={
                "telegram_chat": "@extra_resource",
                "join_url": "https://t.me/extra_resource",
            },
            headers={"origin": ORIGIN, "idempotency-key": "91001"},
        )
        assert added.status_code == 201, added.text
        resource_id = added.json()["resource_id"]
        created = await owner_client.post(
            "/api/v1/administration/invitations",
            json={
                "telegram_username": "member_check",
                "required_resource_ids": [resource_id],
            },
            headers={"origin": ORIGIN, "idempotency-key": "91002"},
        )
        assert created.status_code == 201, created.text
        invitation_id = UUID(created.json()["invitation_id"])
        token = parse_qs(urlsplit(created.json()["invitation_url"]).query)["startapp"][0]

        user_id = 52_191
        request_headers = {
            "content-type": "text/plain; charset=utf-8",
            "origin": ORIGIN,
            "x-community-invitation": token,
        }
        signed_proof = proof(
            user_id,
            now=datetime.datetime.now(datetime.UTC),
            username="member_check",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as member_client:
            denied = await member_client.post(
                "/api/v1/auth/telegram", content=signed_proof, headers=request_headers
            )
            assert denied.status_code == 403
            assert denied.json()["code"] == "membership_required"
            assert {item["title"] for item in denied.json()["resources"]} == {
                "Алло, Нейросеточная?",
                "Дополнительный ресурс",  # noqa: RUF001
            }
            async with sessions() as session:
                invitation = await session.get(InvitationModel, invitation_id)
                assert invitation is not None
                assert invitation.uses_count == 0

            checker.members.update({(-100_100, user_id), (-100_200, user_id)})
            accepted = await member_client.post(
                "/api/v1/auth/telegram", content=signed_proof, headers=request_headers
            )
            assert accepted.status_code == 204, accepted.text
            async with sessions() as session:
                invitation = await session.get(InvitationModel, invitation_id)
                assert invitation is not None
                assert invitation.uses_count == 1
                assert (
                    await session.scalar(
                        select(InvitationMembershipResourceModel).where(
                            InvitationMembershipResourceModel.invitation_id == invitation_id
                        )
                    )
                    is not None
                )
                assert await session.get(MembershipResourceModel, UUID(resource_id)) is not None

            checker.members.remove((-100_100, user_id))
            entry = await member_client.get("/api/v1/me")
            assert entry.status_code == 403
            assert entry.json()["code"] == "membership_required"
            assert entry.json()["resources"] == [
                {
                    "resource_id": None,
                    "title": "Алло, Нейросеточная?",
                    "join_url": "https://t.me/allo_neural",
                    "required": True,
                    "joined": False,
                }
            ]

    await database.dispose()


async def test_web_profile_update_is_exact_concurrent_and_conversation_safe(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await active_member(database, 52_081)
    conversation_payload = {"reference_id": str(uuid4()), "draft": "keep-exactly"}
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add(
            ConversationStateModel(
                member_id=member.id,
                flow_type="task",
                current_step="text",
                payload_json=conversation_payload,
                revision=7,
            )
        )
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    headers = {"origin": ORIGIN, "idempotency-key": "8101"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        saved = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Rosario — Argentina"},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["city"] == "Rosario — Argentina"
        assert saved.json()["timezone"] == "America/Argentina/Cordoba"
        assert saved.json()["display_name"] == "Web Member"

        replay = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Rosario — Argentina"},
            headers=headers,
        )
        assert replay.status_code == 200
        conflict = await client.put(
            "/api/v1/me/profile",
            json={"field": "short_bio", "value": "Другой command"},
            headers=headers,
        )
        assert conflict.status_code == 409
        assert conflict.json() == {"code": "profile_unavailable"}

        invalid = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "x"},
            headers={"origin": ORIGIN, "idempotency-key": "8102"},
        )
        assert invalid.status_code == 422
        free_text = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Rosario"},
            headers={"origin": ORIGIN, "idempotency-key": "8107"},
        )
        assert free_text.status_code == 422
        cleared = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": ""},
            headers={"origin": ORIGIN, "idempotency-key": "8108"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["city"] is None
        assert cleared.json()["timezone"] == "UTC"
        extra_identity = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Córdoba", "member_id": str(member.id)},
            headers={"origin": ORIGIN, "idempotency-key": "8103"},
        )
        assert extra_identity.status_code == 422

        foreign_key = "8104"
        foreign_update_id = _submission_update_id(
            member.id,
            member.id,
            "update",
            foreign_key,
            namespace=b"profile-update-v1",
        )
        async with sessions.begin() as session:
            session.add(
                ProcessedTelegramUpdateModel(
                    update_id=foreign_update_id,
                    update_type="profile_edit_save",
                    actor_member_id=member.id,
                    outcome_code="profile_updated",
                )
            )
        foreign = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Córdoba"},
            headers={"origin": ORIGIN, "idempotency-key": foreign_key},
        )
        assert foreign.status_code == 409

        city, bio = await asyncio.gather(
            client.put(
                "/api/v1/me/profile",
                json={"field": "city", "value": "Córdoba — Argentina"},
                headers={"origin": ORIGIN, "idempotency-key": "8105"},
            ),
            client.put(
                "/api/v1/me/profile",
                json={"field": "short_bio", "value": "Запустить пилот"},
                headers={"origin": ORIGIN, "idempotency-key": "8106"},
            ),
        )
        assert city.status_code == bio.status_code == 200
        authoritative = (await client.get("/api/v1/me")).json()
        assert authoritative["city"] == "Córdoba — Argentina"
        assert authoritative["timezone"] == "America/Argentina/Cordoba"
        assert authoritative["short_bio"] == "Запустить пилот"
        legacy_fields = ("availability", "current_goal", "help_categories")
        assert set(authoritative).isdisjoint(legacy_fields)
        for index, field in enumerate((*legacy_fields, "timezone"), start=8110):
            rejected = await client.put(
                "/api/v1/me/profile",
                json={"field": field, "value": "legacy value"},
                headers={"origin": ORIGIN, "idempotency-key": str(index)},
            )
            assert rejected.status_code == 422
            assert rejected.json() == {"code": "invalid_request"}
        member_list = (await client.get("/api/v1/members")).json()["items"]
        public_profile = (await client.get(f"/api/v1/members/{member.id}")).json()
        assert member_list
        public_only_fields = (*legacy_fields, "timezone")
        assert set(member_list[0]).isdisjoint(public_only_fields)
        assert set(public_profile).isdisjoint(public_only_fields)

        created = await client.put(
            "/api/v1/me/profile",
            json={
                "field": "profile_links",
                "action": "create",
                "label": " GitHub ",
                "url": "https://github.com/web",
            },
            headers={"origin": ORIGIN, "idempotency-key": "8120"},
        )
        assert created.status_code == 200, created.text
        first_link = created.json()["profile_links"][0]
        assert first_link["label"] == "GitHub"
        assert (
            await client.put(
                "/api/v1/me/profile",
                json={
                    "field": "profile_links",
                    "action": "create",
                    "label": " GitHub ",
                    "url": "https://github.com/web",
                },
                headers={"origin": ORIGIN, "idempotency-key": "8120"},
            )
        ).json()["profile_links"] == [first_link]
        conflicting_link = await client.put(
            "/api/v1/me/profile",
            json={"field": "profile_links", "action": "delete", "link_id": first_link["id"]},
            headers={"origin": ORIGIN, "idempotency-key": "8120"},
        )
        assert conflicting_link.status_code == 409
        edited = await client.put(
            "/api/v1/me/profile",
            json={
                "field": "profile_links",
                "action": "update",
                "link_id": first_link["id"],
                "label": "Portfolio",
                "url": "https://example.com/work",
            },
            headers={"origin": ORIGIN, "idempotency-key": "8121"},
        )
        assert edited.json()["profile_links"][0]["id"] == first_link["id"]
        deleted = await client.put(
            "/api/v1/me/profile",
            json={"field": "profile_links", "action": "delete", "link_id": first_link["id"]},
            headers={"origin": ORIGIN, "idempotency-key": "8122"},
        )
        assert deleted.json()["profile_links"] == []
        for index in range(4):
            response = await client.put(
                "/api/v1/me/profile",
                json={
                    "field": "profile_links",
                    "action": "create",
                    "label": f"Link {index}",
                    "url": f"https://example.com/{index}",
                },
                headers={"origin": ORIGIN, "idempotency-key": str(8130 + index)},
            )
            assert response.status_code == 200
        contenders = await asyncio.gather(
            *(
                client.put(
                    "/api/v1/me/profile",
                    json={
                        "field": "profile_links",
                        "action": "create",
                        "label": f"Last {index}",
                        "url": f"https://example.com/last-{index}",
                    },
                    headers={"origin": ORIGIN, "idempotency-key": str(8140 + index)},
                )
                for index in range(2)
            )
        )
        assert sorted(item.status_code for item in contenders) == [200, 422]
        authoritative_links = (await client.get("/api/v1/me")).json()["profile_links"]
        assert len(authoritative_links) == 5
        public_links = (await client.get(f"/api/v1/members/{member.id}")).json()["profile_links"]
        assert public_links == authoritative_links

        async with sessions.begin() as session:
            stored_member = await session.get(MemberModel, member.id)
            assert stored_member is not None
            assert stored_member.timezone == "America/Argentina/Cordoba"
            stored_member.telegram_username = "bad!"
        malformed_public = await client.get(f"/api/v1/members/{member.id}")
        assert malformed_public.status_code == 200
        assert malformed_public.json()["telegram_username"] is None
        async with sessions.begin() as session:
            stored_member = await session.get(MemberModel, member.id)
            assert stored_member is not None
            stored_member.status = MemberStatus.PAUSED.value
        paused_profile = await client.get("/api/v1/me")
        assert paused_profile.status_code == 200
        assert paused_profile.json()["member_id"] == str(member.id)
        denied = await client.put(
            "/api/v1/me/profile",
            json={"field": "city", "value": "Mendoza"},
            headers={"origin": ORIGIN, "idempotency-key": "8107"},
        )
        assert denied.status_code == 403

    async with sessions() as session:
        conversation = await session.get(ConversationStateModel, member.id)
        assert conversation is not None
        assert (
            conversation.flow_type,
            conversation.current_step,
            conversation.payload_json,
            conversation.revision,
        ) == ("task", "text", conversation_payload, 7)
        profile_audits = await session.scalar(
            select(func.count(AuditEventModel.id)).where(
                AuditEventModel.actor_member_id == member.id,
                AuditEventModel.action == "profile_updated",
            )
        )
        web_receipts = await session.scalar(
            select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                ProcessedTelegramUpdateModel.actor_member_id == member.id,
                ProcessedTelegramUpdateModel.update_type == "profile_web_update",
            )
        )
        assert profile_audits == web_receipts == 12
    await database.dispose()


async def test_member_avatar_is_authenticated_authorized_and_server_proxied(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await active_member(database, 52_091)
    checker = FakeMembershipChecker()
    photo_content = b"\xff\xd8\xfftelegram-profile-photo\xff\xd9"
    checker.profile_photos[member.telegram_user_id] = TelegramProfilePhoto(photo_content)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
        membership_checker=checker,
    )
    avatar_path = f"/api/v1/members/{member.id}/avatar"
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get(avatar_path)).status_code == 401
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(member.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204

        avatar = await client.get(avatar_path)
        assert avatar.status_code == 200
        assert avatar.content == photo_content
        assert avatar.headers["content-type"] == "image/jpeg"
        assert avatar.headers["cache-control"] == "private, max-age=900"
        assert checker.profile_photo_requests == [member.telegram_user_id]

        checker.profile_photos.clear()
        absent = await client.get(avatar_path)
        assert absent.status_code == 404
        assert absent.headers["cache-control"] == "private, max-age=300"
        assert (await client.get(f"/api/v1/members/{uuid4()}/avatar")).status_code == 404

    await database.dispose()


async def test_member_can_persist_replace_and_remove_custom_profile_avatar(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await active_member(database, 52_092)
    checker = FakeMembershipChecker()
    telegram_photo = b"\xff\xd8\xfftelegram-fallback\xff\xd9"
    checker.profile_photos[member.telegram_user_id] = TelegramProfilePhoto(telegram_photo)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
        membership_checker=checker,
    )
    source_buffer = BytesIO()
    source = Image.new("RGB", (900, 600), (34, 139, 230))
    source_exif = Image.Exif()
    source_exif[0x010E] = "must not persist"
    source.save(source_buffer, "JPEG", quality=95, exif=source_exif)
    source_content = source_buffer.getvalue()
    avatar_path = f"/api/v1/members/{member.id}/avatar"

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(member.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        assert (await client.get("/api/v1/me/avatar")).json() == {
            "custom": False,
            "revision": None,
        }
        assert (
            await client.put(
                "/api/v1/me/avatar",
                content=source_content,
                headers={"content-type": "image/jpeg"},
            )
        ).status_code == 403
        invalid = await client.put(
            "/api/v1/me/avatar",
            content=b"not-an-image",
            headers={"content-type": "image/jpeg", "origin": ORIGIN},
        )
        assert invalid.status_code == 422

        uploaded = await client.put(
            "/api/v1/me/avatar",
            content=source_content,
            headers={"content-type": "image/jpeg", "origin": ORIGIN},
        )
        assert uploaded.status_code == 200
        assert uploaded.json() == {"custom": True, "revision": 1}
        repeated = await client.put(
            "/api/v1/me/avatar",
            content=source_content,
            headers={"content-type": "image/jpeg", "origin": ORIGIN},
        )
        assert repeated.json() == {"custom": True, "revision": 1}

        avatar = await client.get(avatar_path)
        assert avatar.status_code == 200
        assert avatar.headers["x-community-avatar-source"] == "custom"
        assert checker.profile_photo_requests == []
        with Image.open(BytesIO(avatar.content)) as normalized:
            assert normalized.size == (512, 512)
            assert normalized.format == "JPEG"
            assert not normalized.getexif()

        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session:
            stored = await session.get(MemberAvatarModel, member.id)
            assert stored is not None
            assert stored.content == avatar.content
            assert stored.content_type == "image/jpeg"
            assert stored.revision == 1

        await database.dispose()
        reopened = Database(database_url)
        persisted = await RegistrationService(reopened.unit_of_work).profile_avatar(member.id)
        assert persisted is not None
        assert persisted.content == avatar.content
        await reopened.dispose()

        restored = await client.delete("/api/v1/me/avatar", headers={"origin": ORIGIN})
        assert restored.status_code == 200
        assert restored.json() == {"custom": False, "revision": None}
        fallback = await client.get(avatar_path)
        assert fallback.content == telegram_photo
        assert fallback.headers["x-community-avatar-source"] == "telegram"
        assert checker.profile_photo_requests == [member.telegram_user_id]

    await database.dispose()


async def test_telegram_username_sync_is_serialized_audited_and_atomic(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await active_member(database, 52_082)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    now = datetime.datetime.now(datetime.UTC)

    async def authenticate(username: str | object | None) -> Response:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
            return await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=now, username=username),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )

    assert (await authenticate("Updated_Name")).status_code == 204
    assert (await authenticate("Updated_Name")).status_code == 401
    concurrent = await asyncio.gather(authenticate("Final_Name"), authenticate(_USERNAME_ABSENT))
    assert [item.status_code for item in concurrent] == [204, 204]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored = await session.get(MemberModel, member.id)
        assert stored is not None
        assert stored.telegram_username in {"Final_Name", None}
        audits = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.actor_member_id == member.id,
                    AuditEventModel.action == "telegram_username_changed",
                )
            )
        ).all()
        assert [item.reason for item in audits] == ["updated", "updated", "cleared"] or [
            item.reason for item in audits
        ] == ["updated", "cleared", "updated"]
        assert all(item.before_json is None and item.after_json is None for item in audits)
        current_username = stored.telegram_username
    token_digest = hashlib.sha256(b"failing-session").digest()
    assert (
        await database.create_web_session(
            telegram_user_id=member.telegram_user_id,
            telegram_username=current_username,
            proof_digest=hashlib.sha256(b"first-proof").digest(),
            proof_expires_at=now + datetime.timedelta(minutes=5),
            token_digest=token_digest,
            authenticated_at=now,
            expires_at=now + datetime.timedelta(minutes=5),
        )
        == member.id
    )
    with pytest.raises(SQLAlchemyError):
        await database.create_web_session(
            telegram_user_id=member.telegram_user_id,
            telegram_username="Rolled_Back",
            proof_digest=hashlib.sha256(b"second-proof").digest(),
            proof_expires_at=now + datetime.timedelta(minutes=5),
            token_digest=token_digest,
            authenticated_at=now,
            expires_at=now + datetime.timedelta(minutes=5),
        )
    async with sessions() as session:
        stored = await session.get(MemberModel, member.id)
        assert stored is not None
        assert stored.telegram_username in {"Final_Name", None}
        assert await session.get(WebSessionModel, token_digest) is not None
        assert (
            await session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.actor_member_id == member.id,
                    AuditEventModel.action == "telegram_username_changed",
                )
            )
            == 3
        )
    unknown = await database.create_web_session(
        telegram_user_id=9_999_999,
        telegram_username="Unknown_User",
        proof_digest=hashlib.sha256(b"unknown-proof").digest(),
        proof_expires_at=now + datetime.timedelta(minutes=5),
        token_digest=hashlib.sha256(b"unknown-session").digest(),
        authenticated_at=now,
        expires_at=now + datetime.timedelta(minutes=5),
    )
    assert unknown is None
    await database.dispose()


async def test_karma_vote_api_is_actor_scoped_exact_and_authoritative(
    database_url: str,
) -> None:
    database = Database(database_url)
    actor = await add_member(database, 52_091, display_name="Karma Actor")
    target = await add_member(database, 52_092, display_name="Karma Target")
    await prepare_config(database, actor.id)
    await add_paid_interaction(database, actor, target)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(actor.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        assert (await client.get(f"/api/v1/members/{target.id}")).json()["can_rate_karma"] is True
        assert (await client.get(f"/api/v1/members/{actor.id}")).json()["can_rate_karma"] is False

        async def action(
            key: str,
            body: dict[str, object],
            *,
            target_id: UUID = target.id,
        ) -> Response:
            return await client.post(
                f"/api/v1/members/{target_id}/karma-vote",
                headers={"origin": ORIGIN, "idempotency-key": key},
                json=body,
            )

        invalid_actor = await action("8201", {"action": "begin", "actor_member_id": str(actor.id)})
        assert invalid_actor.json() == {"code": "invalid_request"}
        async with sessions.begin() as session:
            session.add(
                ConversationStateModel(
                    member_id=actor.id,
                    flow_type="profile_edit",
                    current_step="skill_tags",
                    payload_json={"skill_tags": ["legacy"]},
                    revision=50,
                )
            )
        begun = await action("8201", {"action": "begin"})
        assert (begun.status_code, begun.json()) == (
            200,
            {
                "action": "begin",
                "target_id": str(target.id),
                "step": "value",
                "revision": 0,
                "aggregate": None,
            },
        )
        valued = await action("8202", {"action": "save_value", "expected_revision": 0, "value": 1})
        assert (valued.status_code, valued.json()["revision"], valued.json()["step"]) == (
            200,
            1,
            "comment",
        )
        assert (await action("8201", {"action": "begin"})).json() == begun.json()
        for response in (
            await action("8201", {"action": "save_value", "expected_revision": 0, "value": 1}),
            await action("8201", {"action": "begin"}, target_id=uuid4()),
            await action("8202", {"action": "save_value", "expected_revision": 0, "value": -1}),
            await action("8202", {"action": "save_value", "expected_revision": 1, "value": 1}),
        ):
            assert (response.status_code, response.json()) == (
                409,
                {"code": "karma_vote_unavailable"},
            )
        commented = await action(
            "8203",
            {
                "action": "save_comment",
                "expected_revision": 1,
                "comment": "Надёжная помощь в общем задании.",
            },
        )
        assert (commented.status_code, commented.json()["revision"]) == (200, 2)
        foreign_target = await action(
            "8206",
            {
                "action": "save_comment",
                "expected_revision": 2,
                "comment": "Надёжная помощь в общем задании.",
            },
            target_id=uuid4(),
        )
        assert (foreign_target.status_code, foreign_target.json()) == (
            409,
            {"code": "karma_vote_unavailable"},
        )
        confirms = await asyncio.gather(
            action("8204", {"action": "confirm", "expected_revision": 2}),
            action("8205", {"action": "confirm", "expected_revision": 2}),
        )
        assert sorted(item.status_code for item in confirms) == [200, 409]
        confirmed = next(item for item in confirms if item.status_code == 200)
        confirmed_key = "8204" if confirms[0].status_code == 200 else "8205"
        assert confirmed.json()["aggregate"] == {"score": 1, "count": 1}
        delayed_value = await action(
            "8202", {"action": "save_value", "expected_revision": 0, "value": 1}
        )
        assert delayed_value.json() == valued.json()
        assert (
            await action(
                "8203",
                {
                    "action": "save_comment",
                    "expected_revision": 1,
                    "comment": "Надёжная помощь в общем задании.",
                },
            )
        ).json() == commented.json()
        replay = await action(confirmed_key, {"action": "confirm", "expected_revision": 2})
        assert replay.json() == confirmed.json()
        profile = await client.get(f"/api/v1/members/{target.id}")
        assert profile.status_code == 200
        assert profile.json()["karma"] == {"score": 1, "count": 1}
        assert not {"comment", "rater_id", "history", "telegram_user_id"}.intersection(
            profile.json()
        )

    async with sessions() as session:
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 1
        assert await session.scalar(select(func.count(KarmaVoteHistoryModel.id))) == 1
        assert (
            await session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.action == "karma_vote_saved"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                    ProcessedTelegramUpdateModel.update_type == "karma_web"
                )
            )
            == 4
        )
    await database.dispose()


async def test_karma_vote_api_hides_targets_and_reauthorizes_confirm(database_url: str) -> None:
    database = Database(database_url)
    actor = await add_member(database, 52_093)
    target = await add_member(database, 52_094)
    hidden = await add_member(database, 52_095, status=MemberStatus.PAUSED)
    await prepare_config(database, actor.id)
    await add_paid_interaction(database, actor, target)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        await client.post(
            "/api/v1/auth/telegram",
            content=proof(actor.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )

        async def post(target_id: UUID, key: str, body: dict[str, object]) -> Response:
            return await client.post(
                f"/api/v1/members/{target_id}/karma-vote",
                headers={"origin": ORIGIN, "idempotency-key": key},
                json=body,
            )

        absent = await post(uuid4(), "8210", {"action": "begin"})
        hidden_response = await post(hidden.id, "8211", {"action": "begin"})
        assert [(item.status_code, item.json()) for item in (absent, hidden_response)] == [
            (404, {"code": "not_found"}),
            (404, {"code": "not_found"}),
        ]
        draft = (await post(target.id, "8212", {"action": "begin"})).json()
        draft = (
            await post(
                target.id,
                "8213",
                {"action": "save_value", "expected_revision": draft["revision"], "value": 1},
            )
        ).json()
        draft = (
            await post(
                target.id,
                "8214",
                {
                    "action": "save_comment",
                    "expected_revision": draft["revision"],
                    "comment": "Ограничение после заполнения черновика.",
                },
            )
        ).json()
        async with sessions.begin() as session:
            session.add(
                MemberSanctionModel(
                    target_member_id=actor.id,
                    author_member_id=target.id,
                    sanction_type="restriction",
                    restricted_actions_json=["karma_vote"],
                    reason="Integration authorization recheck.",
                    starts_at=datetime.datetime.now(datetime.UTC),
                    ends_at=None,
                    previous_status=MemberStatus.ACTIVE.value,
                    applied_status=MemberStatus.ACTIVE.value,
                    state="active",
                    command_id=uuid4(),
                )
            )
        denied = await post(
            target.id,
            "8215",
            {"action": "confirm", "expected_revision": draft["revision"]},
        )
        assert (denied.status_code, denied.json()) == (404, {"code": "not_found"})
    async with sessions() as session:
        stored = await session.get(ConversationStateModel, actor.id)
        assert stored is not None
        assert stored.flow_type == "karma"
        assert stored.revision == 2
        assert await session.scalar(select(func.count(KarmaVoteModel.id))) == 0
        assert (
            await session.scalar(
                select(func.count(ProcessedTelegramUpdateModel.update_id)).where(
                    ProcessedTelegramUpdateModel.update_type == "karma_web"
                )
            )
            == 3
        )
    await database.dispose()


async def test_task_creation_resource_recovers_and_publishes_exactly_once(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=52_070)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=now),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        headers = {"origin": ORIGIN, "idempotency-key": "7001"}
        invalid_type = await client.post(
            "/api/v1/task-creation", content=b'{"action":"start"}', headers=headers
        )
        assert invalid_type.status_code == 422
        assert (
            await client.post("/api/v1/task-creation", json={"action": "start"}, headers=headers)
        ).status_code == 204
        state = (await client.get("/api/v1/task-creation")).json()
        draft_id = state["draft"]["id"]
        assert state["credit_balance"] == 10
        assert state["categories"][0]["code"]
        assert state["categories"][0]["description"]
        assert state["draft"]["values"]["format"] == "online"
        city_search = await client.get("/api/v1/task-cities", params={"q": "Buenos Aires"})
        assert city_search.status_code == 200
        canonical_city_item = next(
            item
            for item in city_search.json()["items"]
            if item["value"] == "Buenos Aires — Argentina"
        )
        canonical_city = canonical_city_item["value"]
        assert canonical_city_item["timezone"] == "America/Argentina/Buenos_Aires"
        selected_city_search = await client.get("/api/v1/task-cities", params={"q": canonical_city})
        assert selected_city_search.status_code == 200
        assert selected_city_search.json()["items"] == [canonical_city_item]
        collisions = await client.get("/api/v1/task-cities", params={"q": "Dondo", "limit": 10})
        collision_values = [item["value"] for item in collisions.json()["items"]]
        assert collisions.status_code == 200
        assert collision_values.count("Dondo — Angola · 05") == 1
        assert len(collision_values) == len(set(collision_values))
        form = {
            "category_id": state["categories"][0]["id"],
            "task_kind": "group",
            "time_size": "s",
            "title": "  Помочь с проверкой  ",  # noqa: RUF001
            "description": "  Проверить понятный результат и вернуть замечания.  ",
            "completion_criteria": "  Есть конкретный список замечаний.  ",
            "credit_reward_per_performer": 3,
            "deadline_at": (now + datetime.timedelta(days=2)).isoformat(),
            "format": "online",
            "materials": {"url": "  https://example.com/task  "},
            "performer_slots": 2,
        }
        save = {"action": "save", "draft_id": draft_id, "expected_revision": 0, "form": form}
        save_headers = {"origin": ORIGIN, "idempotency-key": "7002"}
        normalized = save | {
            "form": form
            | {
                "title": form["title"].strip(),
                "description": form["description"].strip(),
                "completion_criteria": form["completion_criteria"].strip(),
                "materials": {"url": form["materials"]["url"].strip()},
            }
        }
        assert (
            await client.post("/api/v1/task-creation", json=normalized, headers=save_headers)
        ).status_code == 204
        monkeypatch.setattr(
            "community_bot.application.tasks._utc_now",
            lambda: now + datetime.timedelta(days=3),
        )
        assert (
            await client.post("/api/v1/task-creation", json=save, headers=save_headers)
        ).status_code == 204
        monkeypatch.setattr("community_bot.application.tasks._utc_now", lambda: now)
        conflict = save | {"form": form | {"title": "Другой payload"}}
        assert (
            await client.post("/api/v1/task-creation", json=conflict, headers=save_headers)
        ).status_code == 409
        preview = (await client.get("/api/v1/task-creation")).json()
        assert preview["preview"]["reward_total"] == 6
        assert preview["draft"]["values"]["title"] == "Помочь с проверкой"  # noqa: RUF001
        assert preview["draft"]["values"]["materials"] == {"url": "https://example.com/task"}
        assert preview["draft"]["values"]["city"] is None

        offline = save | {
            "expected_revision": 1,
            "form": form | {"format": "offline", "city": canonical_city},
        }
        assert (
            await client.post(
                "/api/v1/task-creation",
                json=offline,
                headers={"origin": ORIGIN, "idempotency-key": "7003"},
            )
        ).status_code == 204
        tampered = offline | {
            "expected_revision": 2,
            "form": form | {"format": "offline", "city": "Buenos Aires"},
        }
        assert (
            await client.post(
                "/api/v1/task-creation",
                json=tampered,
                headers={"origin": ORIGIN, "idempotency-key": "7004"},
            )
        ).status_code == 422
        after_tamper = (await client.get("/api/v1/task-creation")).json()
        assert after_tamper["draft"]["revision"] == 2
        assert after_tamper["draft"]["values"]["city"] == canonical_city

        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions.begin() as session:
            stored = await session.get(TaskCreationDraftModel, UUID(draft_id))
            assert stored is not None
            stored.deadline_at = now - datetime.timedelta(minutes=1)
        expired = (await client.get("/api/v1/task-creation")).json()
        assert expired["needs_edit"] is True
        assert expired["preview"] is None
        repaired = offline | {
            "expected_revision": 2,
            "form": form
            | {
                "format": "offline",
                "city": canonical_city,
                "materials": {},
            },
        }
        assert (
            await client.post(
                "/api/v1/task-creation",
                json=repaired,
                headers={"origin": ORIGIN, "idempotency-key": "7005"},
            )
        ).status_code == 204
        repaired_state = (await client.get("/api/v1/task-creation")).json()
        assert repaired_state["draft"]["values"]["materials"] == {}
        assert repaired_state["preview"] is not None
        publish = {"action": "publish", "draft_id": draft_id, "expected_revision": 3}
        publish_headers = {"origin": ORIGIN, "idempotency-key": "7006"}
        first = await client.post("/api/v1/task-creation", json=publish, headers=publish_headers)
        replay = await client.post("/api/v1/task-creation", json=publish, headers=publish_headers)
        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()

        async with sessions.begin() as session:
            run = DbTestRunModel(marker="TEST-CB70-PUBLISH", started_by_member_id=member.id)
            session.add(run)
            await session.flush()
            session.add(DbTestRunParticipantModel(run_id=run.id, member_id=member.id))
        stale_replay = await client.post(
            "/api/v1/task-creation", json=publish, headers=publish_headers
        )
        assert stale_replay.status_code == 409

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TaskModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ConversationStateModel)) == 0


async def test_community_task_creation_and_moderation_are_permission_scoped(
    database_url: str,
) -> None:
    database = Database(database_url)
    performer = await prepare_member(database, telegram_user_id=52_072)
    creator = await add_member(
        database,
        52_073,
        role=MemberRole.ADMINISTRATOR,
        permissions=[COMMUNITY_TASK_CREATE_PERMISSION],
    )
    reviewer = await add_member(
        database,
        52_074,
        role=MemberRole.ADMINISTRATOR,
        permissions=[COMMUNITY_TASK_REVIEW_PERMISSION],
    )
    denied = await add_member(database, 52_075, role=MemberRole.ADMINISTRATOR)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    now = datetime.datetime.now(datetime.UTC)
    authentication_sequence = 0

    async def authenticate(client: AsyncClient, telegram_user_id: int) -> None:
        nonlocal authentication_sequence
        authentication_sequence += 1
        response = await client.post(
            "/api/v1/auth/telegram",
            content=proof(
                telegram_user_id,
                now=now + datetime.timedelta(seconds=authentication_sequence),
            ),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert response.status_code == 204

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as creator_client:
        await authenticate(creator_client, creator.telegram_user_id)
        state = (await creator_client.get("/api/v1/task-creation")).json()
        community = next(
            item for item in state["categories"] if item["code"] == "community_development"
        )
        assert state["community_reward_max"] == 10
        assert (
            await creator_client.post(
                "/api/v1/task-creation",
                json={"action": "start"},
                headers={"origin": ORIGIN, "idempotency-key": "7201"},
            )
        ).status_code == 204
        draft = (await creator_client.get("/api/v1/task-creation")).json()["draft"]
        form = {
            "category_id": community["id"],
            "task_kind": "solo",
            "time_size": "l",
            "title": "Подготовить план встречи сообщества",
            "description": "Собрать предложения участников и оформить понятный план встречи.",
            "completion_criteria": "План содержит темы, порядок обсуждения и ответственных.",
            "credit_reward_per_performer": 10,
            "deadline_at": (now + datetime.timedelta(days=2)).isoformat(),
            "format": "online",
            "materials": {},
            "performer_slots": 1,
        }
        over_limit = await creator_client.post(
            "/api/v1/task-creation",
            json={
                "action": "save",
                "draft_id": draft["id"],
                "expected_revision": 0,
                "form": form | {"credit_reward_per_performer": 11},
            },
            headers={"origin": ORIGIN, "idempotency-key": "7202"},
        )
        assert over_limit.status_code == 409
        saved = await creator_client.post(
            "/api/v1/task-creation",
            json={
                "action": "save",
                "draft_id": draft["id"],
                "expected_revision": 0,
                "form": form,
            },
            headers={"origin": ORIGIN, "idempotency-key": "7203"},
        )
        assert saved.status_code == 204, saved.text
        preview = (await creator_client.get("/api/v1/task-creation")).json()
        assert preview["draft"]["origin"] == "community"
        assert preview["preview"]["origin"] == "community"
        assert preview["preview"]["author_display_name"] == "Сообщество"
        assert preview["preview"]["reward_total"] == 0
        published = await creator_client.post(
            "/api/v1/task-creation",
            json={
                "action": "publish",
                "draft_id": draft["id"],
                "expected_revision": 1,
            },
            headers={"origin": ORIGIN, "idempotency-key": "7204"},
        )
        assert published.status_code == 200, published.text
        task_id = UUID(published.json()["task_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as denied_client:
        await authenticate(denied_client, denied.telegram_user_id)
        denied_state = (await denied_client.get("/api/v1/task-creation")).json()
        assert "community_development" not in {item["code"] for item in denied_state["categories"]}
        assert (await denied_client.get("/api/v1/moderation/community-reviews")).status_code == 403
        assert (
            await denied_client.post(
                "/api/v1/task-creation",
                json={"action": "start"},
                headers={"origin": ORIGIN, "idempotency-key": "7205"},
            )
        ).status_code == 204
        denied_draft = (await denied_client.get("/api/v1/task-creation")).json()["draft"]
        direct_save = await denied_client.post(
            "/api/v1/task-creation",
            json={
                "action": "save",
                "draft_id": denied_draft["id"],
                "expected_revision": 0,
                "form": form,
            },
            headers={"origin": ORIGIN, "idempotency-key": "7206"},
        )
        assert direct_save.status_code == 409

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        task = await session.get(TaskModel, task_id)
        assert task is not None
        assert (
            task.origin,
            task.creator_id,
            task.created_by_admin_id,
            task.reviewer_admin_id,
            task.community_approved_by_admin_id,
            task.author_display_name,
            task.reserved_credit_total,
        ) == ("community", None, creator.id, None, creator.id, "Сообщество", 0)
        assignment = AssignmentModel(
            task_id=task.id,
            performer_id=performer.id,
            slot_number=1,
            status="submitted",
            accepted_at=now,
            submitted_at=now,
            review_deadline_at=now + datetime.timedelta(hours=72),
        )
        session.add(assignment)
        await session.flush()
        session.add(
            AssignmentResultVersionModel(
                assignment_id=assignment.id,
                version=1,
                payload_json={"result": "Готовый план встречи и список ответственных."},
                submit_command_id=uuid4(),
            )
        )
        assignment_id = assignment.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as denied_client:
        await authenticate(denied_client, denied.telegram_user_id)
        denied_decision = await denied_client.post(
            f"/api/v1/assignment-reviews/{assignment_id}/decision",
            json={"decision": "full"},
            headers={"origin": ORIGIN, "idempotency-key": "7207"},
        )
        assert denied_decision.status_code == 409

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as reviewer_client:
        await authenticate(reviewer_client, reviewer.telegram_user_id)
        queue = await reviewer_client.get("/api/v1/moderation/community-reviews")
        assert queue.status_code == 200, queue.text
        assert [UUID(item["id"]) for item in queue.json()["items"]] == [assignment_id]
        detail = await reviewer_client.get(f"/api/v1/moderation/community-reviews/{assignment_id}")
        assert detail.status_code == 200
        assert UUID(detail.json()["performer_id"]) == performer.id
        assert detail.json()["result"] == "Готовый план встречи и список ответственных."
        decision_headers = {"origin": ORIGIN, "idempotency-key": "7208"}
        decision = await reviewer_client.post(
            f"/api/v1/assignment-reviews/{assignment_id}/decision",
            json={"decision": "full"},
            headers=decision_headers,
        )
        replay = await reviewer_client.post(
            f"/api/v1/assignment-reviews/{assignment_id}/decision",
            json={"decision": "full"},
            headers=decision_headers,
        )
        assert decision.status_code == replay.status_code == 204
        assert (await reviewer_client.get("/api/v1/moderation/community-reviews")).json() == {
            "items": []
        }

    async with sessions() as session:
        stored_assignment = await session.get(AssignmentModel, assignment_id)
        stored_performer = await session.get(MemberModel, performer.id)
        transactions = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.assignment_id == assignment_id
                )
            )
        ).all()
        assert stored_assignment is not None
        assert stored_performer is not None
        assert stored_assignment.status == "approved"
        assert stored_assignment.terminal_outcome == "full"
        assert stored_performer.credit_balance_cached == 20
        assert [
            (item.transaction_type, item.credit_delta, item.experience_delta)
            for item in transactions
        ] == [("community_task_reward", 10, 10)]
    await database.dispose()
    await migrate(database_url, "downgrade 0028")
    downgraded = create_async_engine(database_url)
    async with downgraded.connect() as connection:
        creator_permissions = await connection.scalar(
            text("SELECT permissions_json FROM members WHERE id=:id"),
            {"id": creator.id},
        )
        reviewer_permissions = await connection.scalar(
            text("SELECT permissions_json FROM members WHERE id=:id"),
            {"id": reviewer.id},
        )
        retained_task = await connection.scalar(
            text("SELECT count(*) FROM tasks WHERE id=:id AND origin='community'"),
            {"id": task_id},
        )
        assert creator_permissions == []
        assert reviewer_permissions == []
        assert retained_task == 1
    await downgraded.dispose()
    await migrate(database_url, "upgrade 0029")


async def test_task_creation_start_new_atomically_supersedes_and_replays_once(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await prepare_member(database, telegram_user_id=52_071)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=now + datetime.timedelta(seconds=1)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        assert (
            await client.post(
                "/api/v1/task-creation",
                json={"action": "start"},
                headers={"origin": ORIGIN, "idempotency-key": "7101"},
            )
        ).status_code == 204
        first_state = (await client.get("/api/v1/task-creation")).json()["draft"]
        first_id = first_state["id"]
        replacement = {
            "action": "start_new",
            "draft_id": first_id,
            "expected_revision": first_state["revision"],
        }
        replacement_headers = {"origin": ORIGIN, "idempotency-key": "7102"}
        first = await client.post(
            "/api/v1/task-creation", json=replacement, headers=replacement_headers
        )
        replay = await client.post(
            "/api/v1/task-creation", json=replacement, headers=replacement_headers
        )
        assert first.status_code == replay.status_code == 204
        second_id = (await client.get("/api/v1/task-creation")).json()["draft"]["id"]
        assert second_id != first_id
        conflict = await client.post(
            "/api/v1/task-creation",
            json=replacement,
            headers={"origin": ORIGIN, "idempotency-key": "7103"},
        )
        assert conflict.status_code == 409

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        drafts = (
            await session.scalars(
                select(TaskCreationDraftModel)
                .where(TaskCreationDraftModel.creator_id == member.id)
                .order_by(TaskCreationDraftModel.created_at)
            )
        ).all()
        assert [draft.is_current for draft in drafts] == [False, True]
        assert str(drafts[-1].id) == second_id
        hidden_run = DbTestRunModel(
            marker="TEST-CB100-HIDDEN-DRAFT", started_by_member_id=member.id
        )
        session.add(hidden_run)
        await session.flush()
        drafts[-1].test_run_id = hidden_run.id
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=now),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        hidden = await client.post(
            "/api/v1/task-creation",
            json={"action": "start_new", "draft_id": second_id, "expected_revision": 0},
            headers={"origin": ORIGIN, "idempotency-key": "7104"},
        )
        assert hidden.status_code == 409

    async with sessions() as session:
        drafts = (
            await session.scalars(
                select(TaskCreationDraftModel)
                .where(TaskCreationDraftModel.creator_id == member.id)
                .order_by(TaskCreationDraftModel.created_at)
            )
        ).all()
        assert len(drafts) == 2
        assert [draft.is_current for draft in drafts] == [False, True]
        assert str(drafts[-1].id) == second_id
    await database.dispose()


async def schema_snapshot(engine: AsyncEngine) -> tuple[set[str], dict[str, int]]:
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        counts = {
            table: int(
                await connection.scalar(
                    text(f'SELECT count(*) FROM "{table}"')  # noqa: S608 - reflected names.
                )
                or 0
            )
            for table in tables - {"alembic_version"}
        }
    return tables, counts


async def test_web_moderation_cases_authorizes_filters_and_projects_safe_queue(
    database_url: str,
) -> None:
    database = Database(database_url)
    administrator = await active_member(database, 52_101)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    now = datetime.datetime.now(datetime.UTC)
    async with sessions.begin() as session:
        moderator = MemberModel(
            id=uuid4(),
            telegram_user_id=52_102,
            display_name="Moderator",
            timezone="UTC",
            role=MemberRole.MODERATOR.value,
            status=MemberStatus.ACTIVE.value,
        )
        member = MemberModel(
            id=uuid4(),
            telegram_user_id=52_103,
            display_name="Member",
            timezone="UTC",
            role=MemberRole.MEMBER.value,
            status=MemberStatus.ACTIVE.value,
        )
        paused_moderator = MemberModel(
            id=uuid4(),
            telegram_user_id=52_104,
            display_name="Paused moderator",
            timezone="UTC",
            role=MemberRole.MODERATOR.value,
            status=MemberStatus.PAUSED.value,
        )
        restricted_moderator = MemberModel(
            id=uuid4(),
            telegram_user_id=52_105,
            display_name="Restricted moderator",
            timezone="UTC",
            role=MemberRole.MODERATOR.value,
            status=MemberStatus.RESTRICTED.value,
        )
        creator = MemberModel(
            id=uuid4(),
            telegram_user_id=52_106,
            display_name="Creator",
            timezone="UTC",
            role=MemberRole.MEMBER.value,
            status=MemberStatus.ACTIVE.value,
        )
        session.add_all((moderator, member, paused_moderator, restricted_moderator, creator))
        category = await session.scalar(select(TaskCategoryModel).limit(1))
        template = await session.scalar(select(TaskTemplateModel).limit(1))
        assert category is not None
        assert template is not None
        task = TaskModel(
            origin="member",
            template_id=template.id,
            template_version=template.version,
            creator_id=creator.id,
            author_display_name=creator.display_name,
            category_id=category.id,
            title="Moderation queue fixture",
            description="Safe public task.",
            completion_criteria="Complete the task.",
            materials_json={},
            input_payload_json={},
            credit_reward_per_performer=1,
            performer_slots=4,
            reserved_credit_total=4,
            estimated_minutes=10,
            minimum_level=1,
            format="online",
            deadline_at=now + datetime.timedelta(days=1),
            status="settling",
            safety_snapshot_json={},
            publish_command_id=uuid4(),
            published_at=now - datetime.timedelta(days=1),
        )
        session.add(task)
        await session.flush()
        performers = (moderator, member, paused_moderator, administrator)
        assignments = [
            AssignmentModel(
                task_id=task.id,
                performer_id=performer.id,
                slot_number=index,
                status="disputed",
                accepted_at=now - datetime.timedelta(hours=2),
            )
            for index, performer in enumerate(performers, start=1)
        ]
        session.add_all(assignments)
        await session.flush()
        case_rows = (
            (assignments[0], "fraud_review", "open", now - datetime.timedelta(minutes=4)),
            (assignments[1], "dispute", "open", now - datetime.timedelta(minutes=3)),
            (assignments[2], "dispute", "open", now - datetime.timedelta(minutes=2)),
            (assignments[3], "dispute", "resolved", now - datetime.timedelta(minutes=1)),
        )
        cases = []
        for assignment, case_type, status, opened_at in case_rows:
            case = ModerationCaseModel(
                assignment_id=assignment.id,
                case_type=case_type,
                status=status,
                opened_by_member_id=moderator.id,
                open_command_id=uuid4(),
                open_payload_hash="PRIVATE_HASH",
                reason="PRIVATE_REASON",
                opened_at=opened_at,
            )
            session.add(case)
            cases.append(case)
        await session.flush()
        fraud_id, visible_id, appealed_id, _resolved_id = (case.id for case in cases)

    settings = Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url)
    app = create_web_app(settings=settings, database=database)

    async def authenticate(telegram_user_id: int) -> str:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
            authenticated = await client.post(
                "/api/v1/auth/telegram",
                content=proof(telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert authenticated.status_code == 204
            token = client.cookies.get("__Host-community_session")
            assert token is not None
            return token

    tokens = {
        actor.telegram_user_id: await authenticate(actor.telegram_user_id)
        for actor in (administrator, moderator, member, paused_moderator, restricted_moderator)
    }

    async def response_for(telegram_user_id: int, path: str) -> Response:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
            return await client.get(
                path,
                headers={"cookie": f"__Host-community_session={tokens[telegram_user_id]}"},
            )

    async def persistent_snapshot() -> tuple[tuple[int, ...], tuple[tuple[object, ...], ...]]:
        async with sessions() as session:
            values = []
            for model in (
                ProcessedTelegramUpdateModel,
                AccountTransactionModel,
                AuditEventModel,
                OutboxEventModel,
            ):
                values.append(  # noqa: PERF401 - each scalar read must be awaited.
                    int(await session.scalar(select(func.count()).select_from(model)) or 0)
                )
            stored_cases = tuple(
                (
                    case.id,
                    case.status,
                    case.revision,
                    case.current_resolution_id,
                    case.resolved_at,
                    case.reason,
                    case.open_payload_hash,
                )
                for case in (
                    await session.scalars(
                        select(ModerationCaseModel).order_by(ModerationCaseModel.id)
                    )
                ).all()
            )
            return tuple(values), stored_cases

    before_state = await persistent_snapshot()

    moderator_first = await response_for(
        moderator.telegram_user_id, "/api/v1/moderation/cases?limit=1"
    )
    assert moderator_first.status_code == 200
    assert moderator_first.headers["cache-control"] == "no-store"
    assert [item["id"] for item in moderator_first.json()["items"]] == [str(visible_id)]
    moderator_page = await response_for(
        moderator.telegram_user_id, "/api/v1/moderation/cases?limit=2"
    )
    assert [item["id"] for item in moderator_page.json()["items"]] == [
        str(visible_id),
        str(appealed_id),
    ]
    administrator_first = await response_for(
        administrator.telegram_user_id, "/api/v1/moderation/cases?limit=1"
    )
    assert [item["id"] for item in administrator_first.json()["items"]] == [str(fraud_id)]

    allowlist = {
        "id",
        "assignment_id",
        "case_type",
        "status",
        "revision",
        "current_code",
        "opened_at",
        "resolved_at",
    }
    assert set(moderator_first.json()["items"][0]) == allowlist
    serialized = moderator_page.text.lower()
    for forbidden in ("private_reason", "private_hash", "evidence", "telegram", "audit", "outbox"):
        assert forbidden not in serialized

    for actor in (member, paused_moderator, restricted_moderator):
        denied = await response_for(actor.telegram_user_id, "/api/v1/moderation/cases")
        assert denied.status_code == 403
        assert denied.json() == {"code": "moderation_unavailable"}
        assert denied.headers["cache-control"] == "no-store"

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        anonymous = await client.get("/api/v1/moderation/cases")
    assert anonymous.status_code == 401
    assert anonymous.json() == {"code": "unauthorized"}
    for invalid_limit in (0, 51):
        invalid = await response_for(
            moderator.telegram_user_id,
            f"/api/v1/moderation/cases?limit={invalid_limit}",
        )
        assert invalid.status_code == 422
        assert invalid.json() == {"code": "invalid_request"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        fraud_mutation = await client.post(
            f"/api/v1/moderation/cases/{fraud_id}/resolution",
            headers={
                "cookie": (f"__Host-community_session={tokens[administrator.telegram_user_id]}"),
                "origin": ORIGIN,
                "idempotency-key": "750001",
            },
            json={
                "expected_revision": 0,
                "code": "fraud",
                "reason": "Этот route не обслуживает fraud review.",
            },
        )
    assert fraud_mutation.status_code == 409

    assert await persistent_snapshot() == before_state


async def test_web_moderation_resolves_scoped_dispute_once_with_safe_detail(
    database_url: str,
) -> None:
    database = Database(database_url)
    administrator = await add_member(database, 52_120, role=MemberRole.ADMINISTRATOR)
    await prepare_config(database, administrator.id)
    moderator = await add_member(database, 52_121, role=MemberRole.MODERATOR)
    creator = await add_member(database, 52_122)
    performer = await add_member(database, 52_123)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        run = DbTestRunModel(marker="TEST-MODERATION-RESOLUTION", started_by_member_id=moderator.id)
        session.add(run)
        await session.flush()
        session.add_all(
            (
                DbTestRunParticipantModel(run_id=run.id, member_id=moderator.id),
                DbTestRunParticipantModel(run_id=run.id, member_id=performer.id),
                DbTestRunParticipantModel(run_id=run.id, member_id=creator.id),
            )
        )
    case = await _open_dispute_fixture(database, creator, performer, test_run_id=run.id)
    async with sessions.begin() as session:
        assignment = await session.get(AssignmentModel, case.assignment_id)
        assert assignment is not None
        session.add(
            AssignmentResultVersionModel(
                assignment_id=assignment.id,
                version=1,
                payload_json={
                    "result": "Безопасный итог",
                    "private": "НЕ ПОКАЗЫВАТЬ",  # noqa: RUF001
                },
                submit_command_id=uuid4(),
            )
        )

    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )

    async def token(member: MemberModel) -> str:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
            response = await client.post(
                "/api/v1/auth/telegram",
                content=proof(member.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert response.status_code == 204
            value = client.cookies.get("__Host-community_session")
            assert value is not None
            return value

    moderator_token = await token(moderator)
    creator_token = await token(creator)
    administrator_token = await token(administrator)
    headers = {"cookie": f"__Host-community_session={moderator_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        hidden = await client.get(
            f"/api/v1/moderation/cases/{case.id}",
            headers={"cookie": f"__Host-community_session={creator_token}"},
        )
        assert hidden.status_code == 404
        outside_scope = await client.get(
            f"/api/v1/moderation/cases/{case.id}",
            headers={"cookie": f"__Host-community_session={administrator_token}"},
        )
        assert outside_scope.status_code == 404
        detail = await client.get(f"/api/v1/moderation/cases/{case.id}", headers=headers)
        assert detail.status_code == 200
        assert detail.headers["cache-control"] == "no-store"
        assert detail.json() == {
            "id": str(case.id),
            "status": "open",
            "revision": 0,
            "task_title": "Disputed task",
            "task_origin": "member",
            "credit_reward_per_performer": 2,
            "assignment_status": "disputed",
            "result_summary": "Безопасный итог",
            "dispute_reason": "The rejection is disputed.",
            "allowed_resolution_codes": [
                "full_payment",
                "partial_payment",
                "full_refund",
                "cancel_without_fault",
                "performer_no_show",
                "creator_abuse",
            ],
            "opened_at": case.opened_at.isoformat().replace("+00:00", "Z"),
        }
        assert "НЕ ПОКАЗЫВАТЬ" not in detail.text  # noqa: RUF001
        request_headers = headers | {"origin": ORIGIN, "idempotency-key": "751001"}
        payload = {
            "expected_revision": 0,
            "code": "partial_payment",
            "reason": "Подтверждена половина результата.",
        }
        first = await client.post(
            f"/api/v1/moderation/cases/{case.id}/resolution",
            headers=request_headers,
            json=payload,
        )
        replay = await client.post(
            f"/api/v1/moderation/cases/{case.id}/resolution",
            headers=request_headers,
            json=payload,
        )
        conflict = await client.post(
            f"/api/v1/moderation/cases/{case.id}/resolution",
            headers=request_headers,
            json=payload | {"reason": "Другой payload."},
        )
        stale = await client.post(
            f"/api/v1/moderation/cases/{case.id}/resolution",
            headers=headers | {"origin": ORIGIN, "idempotency-key": "751002"},
            json=payload,
        )
        creator_archive = await client.get(
            "/api/v1/owned-tasks",
            headers={"cookie": f"__Host-community_session={creator_token}"},
        )
        assert first.status_code == replay.status_code == 204
        assert conflict.status_code == stale.status_code == 409
        assert creator_archive.status_code == 200
        assert creator_archive.json()["items"][0]["status"] == "completed"
        assert creator_archive.json()["items"][0]["archived_at"] is not None

    async with sessions.begin() as session:
        creator_participant = await session.scalar(
            select(DbTestRunParticipantModel).where(
                DbTestRunParticipantModel.run_id == run.id,
                DbTestRunParticipantModel.member_id == creator.id,
            )
        )
        assert creator_participant is not None
        creator_participant.is_active = False

    async with sessions() as session:
        stored_case = await session.get(ModerationCaseModel, case.id)
        assignment = await session.get(AssignmentModel, case.assignment_id)
        task = None if assignment is None else await session.get(TaskModel, assignment.task_id)
        assert stored_case is not None
        assert stored_case.status == "resolved"
        assert stored_case.revision == 1
        assert assignment is not None
        assert assignment.status == "partially_approved"
        assert task is not None
        assert task.status == "completed"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DisputeResolutionModel)
                .where(DisputeResolutionModel.case_id == case.id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ReliabilityEventModel)
                .where(
                    ReliabilityEventModel.assignment_id == case.assignment_id,
                    ReliabilityEventModel.event_type != "accepted",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.business_key == f"moderation-case:{case.id}:resolution:1")
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessedTelegramUpdateModel)
                .where(ProcessedTelegramUpdateModel.update_type == "moderation")
            )
            == 1
        )
        event = await session.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.business_key == f"moderation-case:{case.id}:resolution:1"
            )
        )
        assert event is not None
        await session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id != event.id)
            .values(
                next_attempt_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
            )
        )
    queue = PostgresNotificationQueue(database.session_factory)
    materialized_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    claims = await queue.claim_outbox(
        now=materialized_at,
        limit=1,
        lease_duration=datetime.timedelta(seconds=30),
    )
    assert len(claims) == 1
    assert claims[0].aggregate_id == case.id
    await queue.materialize(claims[0], now=materialized_at, window=DeliveryWindow())
    async with sessions() as session:
        recipients = set(
            await session.scalars(
                select(NotificationModel.member_id).where(
                    NotificationModel.notification_type == "moderation_case_resolved"
                )
            )
        )
        assert recipients == {performer.id}
    await database.dispose()


async def migrate(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", *revision.split()],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


async def test_session_restart_reads_privacy_authority_and_concurrent_logout(
    database_url: str,
) -> None:
    database = Database(database_url)
    member = await active_member(database, 52_001)
    settings = Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url)
    app = create_web_app(settings=settings, database=database)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.post(
            "/api/v1/auth/telegram",
            content=proof(member.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert response.status_code == 204
        token = client.cookies.get("__Host-community_session")
        assert token is not None

        me = await client.get("/api/v1/me")
        assert me.status_code == 200, me.text
        assert me.headers["cache-control"] == "no-store"
        assert me.json()["member_id"] == str(member.id)
        assert "telegram_user_id" not in me.json()

        members = await client.get("/api/v1/members")
        detail = await client.get(f"/api/v1/members/{member.id}")
        tasks = await client.get("/api/v1/tasks")
        leaderboard = await client.get("/api/v1/leaderboard")
        assert [item.status_code for item in (members, detail, tasks, leaderboard)] == [
            200,
            200,
            200,
            200,
        ]
        assert "rater_id" not in detail.text
        assert "input_payload" not in tasks.text
        assert (await client.get("/api/v1/members", params={"query": "a"})).status_code == 200
        assert (await client.get("/api/v1/members", params={"query": "   "})).status_code == 200
        assert (await client.get("/api/v1/members", params={"query": "@"})).status_code == 200
        assert (
            await client.get("/api/v1/leaderboard", params={"period": "week"})
        ).status_code == 200
        assert (
            await client.get("/api/v1/leaderboard", params={"period": "quarter"})
        ).status_code == 422

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored = (await session.scalars(select(WebSessionModel))).one()
        assert (
            stored.token_digest
            == hashlib.sha256(__import__("base64").b64decode(f"{token}=", altchars=b"-_")).digest()
        )
        assert token.encode() not in stored.token_digest
        assert stored.expires_at - stored.authenticated_at == datetime.timedelta(days=30)
        assert (
            await database.web_session_member_id(
                token_digest=stored.token_digest,
                now=stored.expires_at - datetime.timedelta(microseconds=1),
            )
        ) == (member.id, stored.authenticated_at)
        assert (
            await database.web_session_member_id(
                token_digest=stored.token_digest, now=stored.expires_at
            )
            is None
        )
        assert (
            await database.web_session_member_id(
                token_digest=stored.token_digest,
                now=stored.expires_at + datetime.timedelta(microseconds=1),
            )
            is None
        )
        assert await session.scalar(select(func.count()).select_from(WebSessionModel)) == 1

    restarted = Database(database_url)
    restarted_app = create_web_app(settings=settings, database=restarted)
    async with AsyncClient(
        transport=ASGITransport(app=restarted_app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": token},
    ) as restarted_client:
        assert (await restarted_client.get("/api/v1/me")).status_code == 200

        async with sessions.begin() as session:
            stored_member = await session.get(MemberModel, member.id)
            assert stored_member is not None
            stored_member.status = MemberStatus.BANNED.value
        denied = await restarted_client.get("/api/v1/members")
        assert denied.status_code == 403
        assert denied.headers["cache-control"] == "no-store"
        assert (await restarted_client.get("/api/v1/me")).status_code == 403
        assert (await restarted_client.get("/api/v1/tasks")).status_code == 403
        assert (await restarted_client.get("/api/v1/leaderboard")).status_code == 403
        assert (await restarted_client.get(f"/api/v1/members/{uuid4()}")).status_code == 404
        async with sessions.begin() as session:
            stored_member = await session.get(MemberModel, member.id)
            assert stored_member is not None
            stored_member.status = MemberStatus.ACTIVE.value

        async with sessions.begin() as session:
            current_session = (await session.scalars(select(WebSessionModel))).one()
            await session.execute(
                update(WebSessionModel).values(
                    expires_at=max(
                        current_session.created_at,
                        current_session.authenticated_at,
                    )
                    + datetime.timedelta(microseconds=1)
                )
            )
        assert (await restarted_client.get("/api/v1/me")).status_code == 401
        async with sessions.begin() as session:
            await session.execute(
                update(WebSessionModel).values(
                    expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)
                )
            )
        assert (await restarted_client.get("/api/v1/me")).status_code == 200
        assert (await restarted_client.delete("/api/v1/session")).status_code == 403

    async def logout_once() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app),
            base_url=ORIGIN,
            cookies={"__Host-community_session": token},
        ) as logout_client:
            return await logout_client.delete("/api/v1/session", headers={"origin": ORIGIN})

    first, second = await asyncio.gather(logout_once(), logout_once())
    for response in (first, second):
        assert response.status_code == 204
        assert response.headers["cache-control"] == "no-store"
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]

    async with AsyncClient(
        transport=ASGITransport(app=restarted_app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": token},
    ) as denied_client:
        assert (await denied_client.get("/api/v1/me")).status_code == 401
    async with sessions() as session:
        stored = (await session.scalars(select(WebSessionModel))).one()
        assert stored.revoked_at is not None
    async with AsyncClient(transport=ASGITransport(app=restarted_app), base_url=ORIGIN) as client:
        assert (
            await client.delete("/api/v1/session", headers={"origin": ORIGIN})
        ).status_code == 204

    await restarted.dispose()
    await database.dispose()


async def test_catalog_detail_projection_accept_and_cancel_path(database_url: str) -> None:
    database = Database(database_url)
    author, task = await _published_task(database, update_base=52_500)
    performer = await prepare_member(database, telegram_user_id=52_600)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    projections: dict[UUID, dict[str, object]] = {}
    async with sessions.begin() as session:
        source = await session.get(TaskModel, task.id)
        assert source is not None
        snapshots = (
            {
                key: value
                for key, value in source.safety_snapshot_json.items()
                if key != "public_input_keys"
            },
            {**source.safety_snapshot_json, "public_input_keys": {"not": "a list"}},
            {**source.safety_snapshot_json, "public_input_keys": ["public_value", 7]},
            {**source.safety_snapshot_json, "public_input_keys": ["public_value", "unknown"]},
        )
        for index, snapshot in enumerate(snapshots):
            model = TaskModel(
                origin=source.origin,
                test_run_id=source.test_run_id,
                template_id=source.template_id,
                template_version=source.template_version,
                creator_id=source.creator_id,
                author_display_name=source.author_display_name,
                category_id=source.category_id,
                time_size=source.time_size,
                title=f"Privacy projection {index}",
                description=source.description,
                completion_criteria=source.completion_criteria,
                materials_json=source.materials_json,
                input_payload_json={
                    "public_value": "visible only with a valid allowlist",
                    "private_value": "must never leave PostgreSQL",
                },
                credit_reward_per_performer=source.credit_reward_per_performer,
                performer_slots=source.performer_slots,
                reserved_credit_total=source.reserved_credit_total,
                estimated_minutes=source.estimated_minutes,
                minimum_level=source.minimum_level,
                format=source.format,
                city=source.city,
                deadline_at=source.deadline_at,
                status="published",
                safety_snapshot_json=snapshot,
                publish_command_id=uuid4(),
                published_at=source.published_at,
            )
            session.add(model)
            await session.flush()
            projections[model.id] = (
                {"public_value": "visible only with a valid allowlist"} if index == 3 else {}
            )
        test_run = DbTestRunModel(marker="TEST-CB84-HIDDEN", started_by_member_id=performer.id)
        session.add(test_run)
        await session.flush()
        hidden_values = {
            column.key: getattr(source, column.key)
            for column in inspect(TaskModel).mapper.column_attrs
            if column.key not in {"id", "created_at", "updated_at"}
        }
        hidden_task = TaskModel(
            **(
                hidden_values
                | {
                    "test_run_id": test_run.id,
                    "title": "Hidden accepted assignment",
                    "publish_command_id": uuid4(),
                }
            )
        )
        session.add(hidden_task)
        await session.flush()
        hidden_assignment = AssignmentModel(
            task_id=hidden_task.id,
            performer_id=performer.id,
            slot_number=1,
            status="accepted",
            accepted_at=datetime.datetime.now(datetime.UTC),
        )
        session.add(hidden_assignment)
        await session.flush()
        hidden_assignment_id = hidden_assignment.id
    hidden_update_id = _submission_update_id(
        performer.id,
        hidden_assignment_id,
        "cancel",
        "9006",
        namespace=b"assignment-cancellation-v1",
    )

    settings = Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url)
    app = create_web_app(settings=settings, database=database)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(performer.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204

        catalog = await client.get("/api/v1/tasks")
        assert catalog.status_code == 200, catalog.text
        item = next(value for value in catalog.json()["items"] if value["id"] == str(task.id))
        assert item["created_at"] is not None
        assert item["description"]
        assert item["completion_criteria"]
        assert item["performer_instructions"]
        assert set(item["materials"]) <= {"text", "url"}
        for projection_id, expected in projections.items():
            projection = next(
                value for value in catalog.json()["items"] if value["id"] == str(projection_id)
            )
            assert projection["public_input"] == expected
        assert "must never leave PostgreSQL" not in catalog.text
        assert "private_value" not in catalog.text
        assert "input_payload" not in catalog.text

        accepted = await client.post(
            f"/api/v1/tasks/{task.id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "9001"},
        )
        assert accepted.status_code == 201, accepted.text
        assignment = accepted.json()
        assert assignment["task_id"] == str(task.id)
        assert assignment["status"] == "accepted"

        replay = await client.post(
            f"/api/v1/tasks/{task.id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "9001"},
        )
        existing = await client.post(
            f"/api/v1/tasks/{task.id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "9002"},
        )
        assert replay.status_code == existing.status_code == 201
        assert replay.json() == existing.json() == assignment
        unavailable = await client.post(
            f"/api/v1/tasks/{uuid4()}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "9003"},
        )
        assert unavailable.status_code == 409
        assert unavailable.json() == {"code": "assignment_unavailable"}
        assert unavailable.headers["cache-control"] == "no-store"

        hidden_path = f"/api/v1/assignments/{hidden_assignment_id}/cancellation"
        assert (await client.get(f"/api/v1/assignments/{hidden_assignment_id}")).status_code == 404
        hidden_cancel = await client.post(
            hidden_path,
            json={"reason": "Direct UUID must stay scoped"},
            headers={"origin": ORIGIN, "idempotency-key": "9006"},
        )
        assert hidden_cancel.status_code == 409
        async with sessions() as session:
            hidden_stored = await session.get(AssignmentModel, hidden_assignment_id)
            assert hidden_stored is not None
            assert hidden_stored.status == "accepted"
            assert await session.get(ProcessedTelegramUpdateModel, hidden_update_id) is None
            assert (
                await session.scalar(
                    select(func.count(OutboxEventModel.id)).where(
                        OutboxEventModel.business_key
                        == f"assignment:{hidden_assignment_id}:cancelled"
                    )
                )
                == 0
            )
        async with sessions.begin() as session:
            session.add(DbTestRunParticipantModel(run_id=test_run.id, member_id=performer.id))
        scoped_cancel = await client.post(
            hidden_path,
            json={"reason": "Direct UUID must stay scoped"},
            headers={"origin": ORIGIN, "idempotency-key": "9006"},
        )
        assert scoped_cancel.status_code == 204
        async with sessions.begin() as session:
            participant = await session.get(DbTestRunParticipantModel, (test_run.id, performer.id))
            assert participant is not None
            participant.is_active = False
        scoped_replay = await client.post(
            hidden_path,
            json={"reason": "Direct UUID must stay scoped"},
            headers={"origin": ORIGIN, "idempotency-key": "9006"},
        )
        assert scoped_replay.status_code == 409

        assignment_id = UUID(assignment["id"])
        path = f"/api/v1/assignments/{assignment_id}/cancellation"
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as foreign:
            assert (
                await foreign.post(
                    "/api/v1/auth/telegram",
                    content=proof(author.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                    headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
                )
            ).status_code == 204
            denied = await foreign.post(
                path,
                json={"reason": "Not my assignment"},
                headers={"origin": ORIGIN, "idempotency-key": "9004"},
            )
            assert denied.status_code == 409
        cancellation_headers = {"origin": ORIGIN, "idempotency-key": "9005"}
        cancelled = await client.post(
            path, json={"reason": "Cannot finish before deadline"}, headers=cancellation_headers
        )
        replay = await client.post(
            path, json={"reason": "Cannot finish before deadline"}, headers=cancellation_headers
        )
        conflict = await client.post(
            path, json={"reason": "Different reason"}, headers=cancellation_headers
        )
        assert cancelled.status_code == replay.status_code == 204
        assert conflict.status_code == 409

    first_update_id = _accept_update_id(performer.id, task.id, "9001")
    second_update_id = _accept_update_id(performer.id, task.id, "9002")
    cancellation_update_id = _submission_update_id(
        performer.id,
        assignment_id,
        "cancel",
        "9005",
        namespace=b"assignment-cancellation-v1",
    )
    async with sessions() as session:
        stored_assignment = await session.get(AssignmentModel, assignment_id)
        assert stored_assignment is not None
        assert stored_assignment.status == "cancelled"
        assert stored_assignment.cancellation_reason == "Cannot finish before deadline"
        assert (
            await session.scalar(
                select(func.count(AssignmentModel.id)).where(
                    AssignmentModel.id == assignment_id,
                    AssignmentModel.performer_id == performer.id,
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(ReliabilityEventModel.id)).where(
                    ReliabilityEventModel.assignment_id == assignment_id,
                    ReliabilityEventModel.event_type.in_(("accepted", "cancelled_performer")),
                )
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.entity_id == str(assignment_id),
                    AuditEventModel.action == "assignment_accepted",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.business_key == f"assignment:{assignment_id}:accepted"
                )
            )
            == 1
        )
        assert await session.get(ProcessedTelegramUpdateModel, first_update_id) is not None
        assert await session.get(ProcessedTelegramUpdateModel, second_update_id) is None
        assert await session.get(ProcessedTelegramUpdateModel, cancellation_update_id) is not None
        hidden_stored = await session.get(AssignmentModel, hidden_assignment_id)
        assert hidden_stored is not None
        assert hidden_stored.status == "cancelled"
        assert await session.get(ProcessedTelegramUpdateModel, hidden_update_id) is not None
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.business_key == f"assignment:{hidden_assignment_id}:cancelled"
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.business_key == f"assignment:{assignment_id}:cancelled"
                )
            )
            == 1
        )
    await database.dispose()


async def test_owned_tasks_api_is_creator_scoped_and_actor_native(database_url: str) -> None:
    database = Database(database_url)
    author, owned = await _published_task(database, update_base=52_610)
    foreign_author, foreign = await _published_task(database, update_base=52_620)
    performer = await prepare_member(database, telegram_user_id=52_630)
    performed_reviewed_at = datetime.datetime.now(datetime.UTC)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        author_model = await session.get(MemberModel, author.id)
        foreign_author_model = await session.get(MemberModel, foreign_author.id)
        owned_source = await session.get(TaskModel, owned.id)
        source = await session.get(TaskModel, foreign.id)
        assert author_model is not None
        assert foreign_author_model is not None
        assert source is not None
        assert owned_source is not None
        author_model.role = MemberRole.ADMINISTRATOR.value
        foreign_author_model.role = MemberRole.ADMINISTRATOR.value
        values = {
            column.key: getattr(source, column.key)
            for column in inspect(TaskModel).mapper.column_attrs
            if column.key not in {"id", "created_at", "updated_at"}
        }
        session.add(
            TaskModel(
                **(
                    values
                    | {
                        "origin": "community",
                        "creator_id": None,
                        "created_by_admin_id": foreign_author.id,
                        "reviewer_admin_id": author.id,
                        "community_approved_by_admin_id": foreign_author.id,
                        "reserved_credit_total": 0,
                        "publish_command_id": uuid4(),
                    }
                )
            )
        )
        session.add(
            AssignmentModel(
                task_id=owned.id,
                performer_id=performer.id,
                slot_number=1,
                status="accepted",
                accepted_at=datetime.datetime.now(datetime.UTC),
            )
        )
        session.add(
            AssignmentModel(
                task_id=foreign.id,
                performer_id=performer.id,
                slot_number=1,
                status="approved",
                accepted_at=performed_reviewed_at - datetime.timedelta(days=1),
                reviewed_at=performed_reviewed_at,
                slot_ever_paid=True,
            )
        )
        empty_owned = TaskModel(
            **(
                {
                    column.key: getattr(owned_source, column.key)
                    for column in inspect(TaskModel).mapper.column_attrs
                    if column.key not in {"id", "created_at", "updated_at"}
                }
                | {"title": "Задание без исполнителей", "publish_command_id": uuid4()}
            )
        )
        session.add(empty_owned)
        hidden_run = DbTestRunModel(
            marker="TEST-OWNED-CANCELLATION-HIDDEN", started_by_member_id=author.id
        )
        session.add(hidden_run)
        await session.flush()
        empty_owned_id = empty_owned.id
        hidden_owned = TaskModel(
            **(
                {
                    column.key: getattr(owned_source, column.key)
                    for column in inspect(TaskModel).mapper.column_attrs
                    if column.key not in {"id", "created_at", "updated_at"}
                }
                | {
                    "title": "Скрытое test-run задание",
                    "publish_command_id": uuid4(),
                    "test_run_id": hidden_run.id,
                }
            )
        )
        session.add(hidden_owned)
        await session.flush()
        hidden_owned_id = hidden_owned.id

    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(author.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204

        response = await client.get("/api/v1/owned-tasks", params={"member_id": str(performer.id)})
        assert response.status_code == 200, response.text
        cards = {item["id"]: item for item in response.json()["items"]}
        assert cards[str(owned.id)]["cancellation_action"] == "request"
        assert cards[str(owned.id)]["archived_at"] is None
        assert cards[str(owned.id)]["assignees"][0]["member_id"] == str(performer.id)
        assert cards[str(empty_owned_id)]["cancellation_action"] == "cancel"
        assert str(hidden_owned_id) not in cards
        cancel_path = f"/api/v1/owned-tasks/{empty_owned_id}/cancellation"
        cancel_headers = {"origin": ORIGIN, "idempotency-key": "52631"}
        cancelled = await client.post(cancel_path, headers=cancel_headers)
        replay = await client.post(cancel_path, headers=cancel_headers)
        assert cancelled.json() == replay.json() == {"status": "cancelled"}
        refreshed_cards = {
            item["id"]: item for item in (await client.get("/api/v1/owned-tasks")).json()["items"]
        }
        assert refreshed_cards[str(empty_owned_id)]["archived_at"] is not None
        request_path = f"/api/v1/owned-tasks/{owned.id}/cancellation"
        requested = await client.post(
            request_path,
            headers={"origin": ORIGIN, "idempotency-key": "52632"},
        )
        assert requested.json() == {"status": "pending"}
        foreign_cancel = await client.post(
            f"/api/v1/owned-tasks/{foreign.id}/cancellation",
            headers={"origin": ORIGIN, "idempotency-key": "52633"},
        )
        assert foreign_cancel.status_code == 409
        hidden_cancel = await client.post(
            f"/api/v1/owned-tasks/{hidden_owned_id}/cancellation",
            headers={"origin": ORIGIN, "idempotency-key": "52634"},
        )
        assert hidden_cancel.status_code == 409

        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(
                    performer.telegram_user_id,
                    now=datetime.datetime.now(datetime.UTC),
                ),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        creator_cards = (await client.get("/api/v1/owned-tasks")).json()["items"]
        assert all(item["id"] != str(foreign.id) for item in creator_cards)
        performed_response = await client.get(
            "/api/v1/owned-tasks",
            params={"scope": "performed", "member_id": str(author.id)},
        )
        assert performed_response.status_code == 200, performed_response.text
        performed_cards = performed_response.json()["items"]
        assert len(performed_cards) == 1
        assert performed_cards[0]["id"] == str(foreign.id)
        assert performed_cards[0]["status"] == "published"
        assert performed_cards[0]["archive_role"] == "performed"
        assert performed_cards[0]["performed_status"] == "approved"
        archived_at = datetime.datetime.fromisoformat(performed_cards[0]["archived_at"])
        assert archived_at == performed_reviewed_at
        assert performed_cards[0]["cancellation_action"] is None
        task_home = await client.get("/api/v1/task-home")
        assert task_home.status_code == 200, task_home.text
        assert task_home.json()["archive_count"] == 1

    await database.dispose()


async def test_web_submission_draft_is_bounded_exact_and_template_closed(database_url: str) -> None:
    database = Database(database_url)
    author, freeform_task = await _freeform_task(database, update_base=52_750)
    _template_author, template_task = await _published_task(database, update_base=52_850)
    performer = await prepare_member(database, telegram_user_id=52_751)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(performer.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        accepted = await client.post(
            f"/api/v1/tasks/{freeform_task.id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "92750"},
        )
        assert accepted.status_code == 201, accepted.text
        assignment_id = accepted.json()["id"]
        detail = await client.get(f"/api/v1/assignments/{assignment_id}")
        assert detail.json()["task_creator_id"] == str(author.id)
        assert detail.json()["task_author_display_name"] == author.display_name
        assert detail.json()["submission_contract"] == "freeform_result_v1"
        assert detail.json()["can_submit"] is True
        assert detail.json()["can_cancel"] is True
        async with sessions.begin() as session:
            stored_task = await session.get(TaskModel, freeform_task.id)
            assert stored_task is not None
            values = {
                column.key: getattr(stored_task, column.key)
                for column in inspect(TaskModel).mapper.column_attrs
                if column.key not in {"id", "created_at", "updated_at"}
            }
            late_task = TaskModel(
                **(
                    values
                    | {
                        "title": "Accepted after deadline",
                        "deadline_at": datetime.datetime.now(datetime.UTC)
                        + datetime.timedelta(milliseconds=100),
                        "publish_command_id": uuid4(),
                    }
                )
            )
            session.add(late_task)
            await session.flush()
            late_assignment = AssignmentModel(
                task_id=late_task.id,
                performer_id=performer.id,
                slot_number=1,
                status="accepted",
                accepted_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1),
            )
            session.add(late_assignment)
            await session.flush()
            late_assignment_id = late_assignment.id
        await asyncio.sleep(0.2)
        late_detail = await client.get(f"/api/v1/assignments/{late_assignment_id}")
        assert late_detail.json()["assignment_status"] == "accepted"
        assert late_detail.json()["can_submit"] is False
        assert late_detail.json()["can_cancel"] is True

        template_accepted = await client.post(
            f"/api/v1/tasks/{template_task.id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "92756"},
        )
        assert template_accepted.status_code == 201
        template_assignment_id = template_accepted.json()["id"]
        template_closed = await client.post(
            f"/api/v1/assignments/{template_assignment_id}/submission-drafts",
            headers={"origin": ORIGIN, "idempotency-key": "92757"},
        )
        assert template_closed.status_code == 409

        missing_origin = await client.post(
            f"/api/v1/assignments/{assignment_id}/submission-drafts",
            headers={"idempotency-key": "92751"},
        )
        assert missing_origin.status_code == 403
        invalid_begin = await client.post(
            "/api/v1/assignments/not-a-uuid/submission-drafts",
            headers={"origin": ORIGIN, "idempotency-key": "92758"},
        )
        nonempty_begin = await client.post(
            f"/api/v1/assignments/{assignment_id}/submission-drafts",
            headers={"origin": ORIGIN, "idempotency-key": "92759"},
            content=b"x",
        )
        missing_assignment = await client.post(
            f"/api/v1/assignments/{uuid4()}/submission-drafts",
            headers={"origin": ORIGIN, "idempotency-key": "92760"},
        )
        assert [
            invalid_begin.status_code,
            nonempty_begin.status_code,
            missing_assignment.status_code,
        ] == [
            422,
            422,
            409,
        ]
        begin = await client.post(
            f"/api/v1/assignments/{assignment_id}/submission-drafts",
            headers={"origin": ORIGIN, "idempotency-key": "92751"},
        )
        assert begin.status_code == 200, begin.text
        draft = begin.json()
        headers = {"origin": ORIGIN, "idempotency-key": "92752", "content-type": "application/json"}
        invalid_save = await client.put(
            "/api/v1/submission-drafts/not-a-uuid",
            headers=headers,
            json={"expected_revision": 0, "payload": {"result": "x"}},
        )
        invalid_revision = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers=headers | {"idempotency-key": "92761"},
            json={"expected_revision": True, "payload": {"result": "x"}},
        )
        oversized = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers=headers | {"idempotency-key": "92762"},
            content=b"{" + b"x" * 4096,
        )
        assert [invalid_save.status_code, invalid_revision.status_code, oversized.status_code] == [
            422,
            422,
            422,
        ]
        saved = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers=headers,
            json={
                "expected_revision": draft["revision"],
                "payload": {"result": "Useful escaped <script>result</script>."},
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["result"] == "Useful escaped <script>result</script>."
        replay = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers=headers,
            json={
                "expected_revision": draft["revision"],
                "payload": {"result": "Useful escaped <script>result</script>."},
            },
        )
        assert replay.json() == saved.json()
        conflict = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers=headers,
            json={
                "expected_revision": draft["revision"],
                "payload": {"result": "Changed command."},
            },
        )
        assert conflict.status_code == 409
        malformed = await client.put(
            f"/api/v1/submission-drafts/{draft['id']}",
            headers={"origin": ORIGIN, "idempotency-key": "92753", "content-type": "text/plain"},
            content=b"x",
        )
        assert malformed.status_code == 422
        confirm_headers = {
            "origin": ORIGIN,
            "idempotency-key": "92754",
            "content-type": "application/json",
        }
        invalid_confirm = await client.post(
            "/api/v1/submission-drafts/not-a-uuid/confirm",
            headers=confirm_headers,
            json={"expected_revision": saved.json()["revision"]},
        )
        invalid_confirm_revision = await client.post(
            f"/api/v1/submission-drafts/{draft['id']}/confirm",
            headers=confirm_headers | {"idempotency-key": "92763"},
            json={"expected_revision": True},
        )
        assert [invalid_confirm.status_code, invalid_confirm_revision.status_code] == [422, 422]
        first, second = await asyncio.gather(
            client.post(
                f"/api/v1/submission-drafts/{draft['id']}/confirm",
                headers=confirm_headers,
                json={"expected_revision": saved.json()["revision"]},
            ),
            client.post(
                f"/api/v1/submission-drafts/{draft['id']}/confirm",
                headers=confirm_headers,
                json={"expected_revision": saved.json()["revision"]},
            ),
        )
        assert {first.status_code, second.status_code} == {204}
        confirm_conflict = await client.post(
            f"/api/v1/submission-drafts/{draft['id']}/confirm",
            headers=confirm_headers,
            json={"expected_revision": saved.json()["revision"] + 1},
        )
        assert confirm_conflict.status_code == 409
        stale_confirm = await client.post(
            f"/api/v1/submission-drafts/{draft['id']}/confirm",
            headers=confirm_headers | {"idempotency-key": "92764"},
            json={"expected_revision": saved.json()["revision"]},
        )
        assert stale_confirm.status_code == 409
        refreshed = await client.get(f"/api/v1/assignments/{assignment_id}")
        assert refreshed.json()["assignment_status"] == "submitted"

    begin_update_id = _submission_update_id(performer.id, UUID(assignment_id), "begin", "92751")
    confirm_update_id = _submission_update_id(performer.id, UUID(draft["id"]), "confirm", "92754")
    async with sessions() as session:
        assert await session.get(ProcessedTelegramUpdateModel, begin_update_id) is not None
        assert await session.get(ProcessedTelegramUpdateModel, confirm_update_id) is not None
        assert (
            await session.scalar(
                select(func.count(AssignmentResultVersionModel.id)).where(
                    AssignmentResultVersionModel.assignment_id == UUID(assignment_id)
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count(AssignmentSubmissionDraftModel.id)).where(
                    AssignmentSubmissionDraftModel.assignment_id == UUID(template_assignment_id)
                )
            )
            == 0
        )
    await database.dispose()


async def test_active_assignment_api_paginates_privately_without_effects(
    database_url: str,
) -> None:
    database = Database(database_url)
    _author, source_task = await _published_task(database, update_base=53_500)
    performer = await prepare_member(database, telegram_user_id=53_600)
    foreign = await prepare_member(database, telegram_user_id=53_601)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    accepted_at = datetime.datetime(2026, 8, 17, 20, 0, tzinfo=datetime.UTC)
    active_ids: list[UUID] = []

    async with sessions.begin() as session:
        source = await session.get(TaskModel, source_task.id)
        assert source is not None

        def task_row(title: str, *, test_run_id: UUID | None = None) -> TaskModel:
            return TaskModel(
                origin=source.origin,
                test_run_id=test_run_id,
                template_id=source.template_id,
                template_version=source.template_version,
                creator_id=source.creator_id,
                author_display_name=source.author_display_name,
                category_id=source.category_id,
                time_size=source.time_size,
                title=title,
                description="Visible description",
                completion_criteria="Visible completion criteria",
                materials_json={"text": "Visible material", "private": "PRIVATE_MATERIAL"},
                input_payload_json={"private": "PRIVATE_INPUT"},
                credit_reward_per_performer=source.credit_reward_per_performer,
                performer_slots=1,
                reserved_credit_total=source.reserved_credit_total,
                estimated_minutes=source.estimated_minutes,
                minimum_level=source.minimum_level,
                format=source.format,
                city=source.city,
                deadline_at=source.deadline_at,
                status="published",
                safety_snapshot_json=source.safety_snapshot_json,
                publish_command_id=uuid4(),
                published_at=source.published_at,
            )

        first_assignment: AssignmentModel | None = None
        for index in range(52):
            task = task_row(f"Active assignment {index:02d}")
            session.add(task)
            await session.flush()
            assignment = AssignmentModel(
                task_id=task.id,
                performer_id=performer.id,
                slot_number=1,
                status="disputed" if index == 0 else "accepted",
                accepted_at=accepted_at,
                submitted_at=accepted_at if index == 0 else None,
                review_deadline_at=(
                    accepted_at + datetime.timedelta(days=3) if index == 0 else None
                ),
            )
            session.add(assignment)
            await session.flush()
            active_ids.append(assignment.id)
            if index == 0:
                first_assignment = assignment

        assert first_assignment is not None
        result = AssignmentResultVersionModel(
            assignment_id=first_assignment.id,
            version=1,
            payload_json={"summary": "Visible result", "private": "PRIVATE_RESULT"},
            submit_command_id=uuid4(),
        )
        dispute = AssignmentDisputeModel(
            assignment_id=first_assignment.id,
            performer_id=performer.id,
            comment="PRIVATE_DISPUTE",
            open_command_id=uuid4(),
        )
        session.add_all((result, dispute))
        await session.flush()
        case = ModerationCaseModel(
            assignment_id=first_assignment.id,
            dispute_id=dispute.id,
            case_type="dispute",
            status="open",
            opened_by_member_id=performer.id,
            open_command_id=uuid4(),
            open_payload_hash="private-hash",
            reason="PRIVATE_CASE_REASON",
        )
        session.add(case)
        await session.flush()
        session.add(
            DisputeEvidenceModel(
                case_id=case.id,
                author_member_id=performer.id,
                evidence_type="link",
                reference="PRIVATE_EVIDENCE",
            )
        )

        terminal_task = task_row("Terminal assignment")
        foreign_task = task_row("Foreign assignment")
        test_run = DbTestRunModel(marker="TEST-CB54-HIDDEN", started_by_member_id=performer.id)
        session.add_all((terminal_task, foreign_task, test_run))
        await session.flush()
        invisible_task = task_row("Invisible assignment", test_run_id=test_run.id)
        session.add(invisible_task)
        await session.flush()
        terminal = AssignmentModel(
            task_id=terminal_task.id,
            performer_id=performer.id,
            slot_number=1,
            status="approved",
            accepted_at=accepted_at,
            reviewed_at=accepted_at,
            slot_ever_paid=True,
        )
        foreign_assignment = AssignmentModel(
            task_id=foreign_task.id,
            performer_id=foreign.id,
            slot_number=1,
            status="accepted",
            accepted_at=accepted_at,
        )
        invisible = AssignmentModel(
            task_id=invisible_task.id,
            performer_id=performer.id,
            slot_number=1,
            status="accepted",
            accepted_at=accepted_at,
        )
        session.add_all((terminal, foreign_assignment, invisible))
        await session.flush()
        hidden_ids = (terminal.id, foreign_assignment.id, invisible.id, uuid4())

    settings = Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url)
    app = create_web_app(settings=settings, database=database)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(performer.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        before_schema = await schema_snapshot(database.engine)
        async with sessions() as session:
            before_state = tuple(
                (row.id, row.status, row.reviewed_at)
                for row in (
                    await session.scalars(select(AssignmentModel).order_by(AssignmentModel.id))
                ).all()
            )

        first = await client.get("/api/v1/assignments", params={"status": "active", "limit": 50})
        assert first.status_code == 200, first.text
        assert first.json()["next_cursor"] is not None
        second = await client.get(
            "/api/v1/assignments",
            params={
                "status": "active",
                "limit": 50,
                "cursor": first.json()["next_cursor"],
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["next_cursor"] is None
        ids = [UUID(item["id"]) for page in (first, second) for item in page.json()["items"]]
        assert ids == sorted(active_ids, reverse=True)
        assert len(ids) == len(set(ids)) == 52

        list_keys = {
            "id",
            "task_id",
            "task_title",
            "task_origin",
            "created_at",
            "category_name",
            "task_kind",
            "time_size",
            "format",
            "city",
            "credit_reward_per_performer",
            "performer_slots",
            "minimum_level",
            "deadline_at",
            "assignment_status",
            "accepted_at",
            "submitted_at",
            "review_deadline_at",
            "reject_dispute_deadline_at",
            "reviewed_at",
            "task_deadline_at",
            "result_summary",
            "case_status",
            "rejection_reason",
            "rejection_comment",
        }
        assert all(set(item) == list_keys for item in first.json()["items"])
        detail = await client.get(f"/api/v1/assignments/{first_assignment.id}")
        assert detail.status_code == 200, detail.text
        assert set(detail.json()) == list_keys | {
            "task_creator_id",
            "task_author_display_name",
            "category_name",
            "category_icon",
            "task_kind",
            "time_size",
            "description",
            "performer_instructions",
            "completion_criteria",
            "reward_per_performer",
            "format",
            "city",
            "minimum_level",
            "performer_slots",
            "submission_contract",
            "can_submit",
            "can_cancel",
            "can_dispute",
        }
        assert detail.json()["result_summary"] == "Visible result"
        assert detail.json()["case_status"] == "open"
        assert not any(
            marker in first.text + second.text + detail.text
            for marker in (
                "PRIVATE_MATERIAL",
                "PRIVATE_INPUT",
                "PRIVATE_RESULT",
                "PRIVATE_DISPUTE",
                "PRIVATE_CASE_REASON",
                "PRIVATE_EVIDENCE",
            )
        )
        hidden = [await client.get(f"/api/v1/assignments/{item}") for item in hidden_ids]
        assert {(response.status_code, response.text) for response in hidden} == {
            (404, '{"code":"not_found"}')
        }
        invalid_status = await client.get("/api/v1/assignments", params={"status": "all"})
        invalid_cursor = await client.get("/api/v1/assignments", params={"cursor": "invalid"})
        assert invalid_status.status_code == 422
        assert invalid_cursor.status_code == 422

        after_schema = await schema_snapshot(database.engine)
        async with sessions() as session:
            after_state = tuple(
                (row.id, row.status, row.reviewed_at)
                for row in (
                    await session.scalars(select(AssignmentModel).order_by(AssignmentModel.id))
                ).all()
            )
        assert after_schema == before_schema
        assert after_state == before_state

        async with sessions.begin() as session:
            stored = await session.get(MemberModel, performer.id)
            assert stored is not None
            stored.status = MemberStatus.BANNED.value
        denied_before = await schema_snapshot(database.engine)
        denied_list = await client.get("/api/v1/assignments")
        denied_detail = await client.get(f"/api/v1/assignments/{first_assignment.id}")
        assert [(item.status_code, item.json()) for item in (denied_list, denied_detail)] == [
            (403, {"code": "assignment_unavailable"}),
            (403, {"code": "assignment_unavailable"}),
        ]
        assert await schema_snapshot(database.engine) == denied_before

    await database.dispose()


async def test_performer_dispute_api_is_exact_private_and_scope_owned(
    database_url: str,
) -> None:
    database = Database(database_url)
    performer = await prepare_member(database, telegram_user_id=54_700)
    foreign = await prepare_member(database, telegram_user_id=54_701)
    fixtures = [
        await _freeform_task(database, update_base=value) for value in (54_800, 55_000, 55_200)
    ]
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    now = datetime.datetime.now(datetime.UTC)
    rows = [
        AssignmentModel(
            task_id=task.id,
            performer_id=performer.id,
            slot_number=1,
            status="rejected_pending_dispute",
            rejected_at=now,
            reject_dispute_deadline_at=now + datetime.timedelta(hours=24),
        )
        for _author, task in fixtures
    ]
    async with sessions.begin() as session:
        session.add_all(rows)
        await session.flush()
    first, second, hidden = rows
    hidden_author, _hidden_task = fixtures[-1]
    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(performer.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        path = f"/api/v1/assignments/{first.id}/disputes"
        headers = {"origin": ORIGIN, "idempotency-key": "55701"}
        detail = await client.get(f"/api/v1/assignments/{first.id}")
        assert detail.status_code == 200
        assert detail.json()["can_dispute"] is True
        assert detail.json()["reject_dispute_deadline_at"] is not None
        _schema, baseline = await schema_snapshot(database.engine)
        for body in (
            {},
            {"comment": ""},
            {"comment": "   "},
            {"comment": "short"},
            {"comment": "x" * 1001},
        ):
            invalid = await client.post(path, headers=headers, json=body)
            assert (invalid.status_code, invalid.json()) == (422, {"code": "invalid_request"})
        assert (await schema_snapshot(database.engine))[1] == baseline

        async def post(target: UUID, key: str, comment: str) -> Response:
            return await client.post(
                f"/api/v1/assignments/{target}/disputes",
                headers={"origin": ORIGIN, "idempotency-key": key},
                json={"comment": comment},
            )

        exact = await asyncio.gather(
            post(first.id, "55702", "Private exact reason"),
            post(first.id, "55702", " Private exact reason "),
        )
        assert [response.status_code for response in exact] == [204, 204]
        disputed_detail = await client.get(f"/api/v1/assignments/{first.id}")
        assert disputed_detail.json()["can_dispute"] is False
        assert disputed_detail.json()["case_status"] == "open"
        assert "Private exact reason" not in disputed_detail.text
        conflict = await asyncio.gather(
            post(second.id, "55703", "First private reason"),
            post(second.id, "55703", "Conflicting private reason"),
        )
        assert sorted(response.status_code for response in conflict) == [204, 409]
        assert (await post(first.id, "55704", "Already open")).status_code == 409

        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as outsider:
            await outsider.post(
                "/api/v1/auth/telegram",
                content=proof(foreign.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            denied = await outsider.post(
                path,
                headers=headers,
                json={"comment": "Foreign reason"},
            )
            assert (denied.status_code, denied.json()) == (
                409,
                {"code": "assignment_unavailable"},
            )

        async with sessions.begin() as session:
            run = DbTestRunModel(marker="TEST-CB74-HIDDEN", started_by_member_id=hidden_author.id)
            session.add(run)
            await session.flush()
            session.add(DbTestRunParticipantModel(run_id=run.id, member_id=performer.id))
        hidden_response = await post(hidden.id, "55705", "Hidden reason")
        assert (hidden_response.status_code, hidden_response.json()) == (
            409,
            {"code": "assignment_unavailable"},
        )
        replay_after_scope_change = await post(first.id, "55702", "Private exact reason")
        assert replay_after_scope_change.status_code == 409
        async with sessions.begin() as session:
            participant = await session.get(DbTestRunParticipantModel, (run.id, performer.id))
            stored_hidden = await session.get(AssignmentModel, hidden.id)
            assert participant is not None and stored_hidden is not None  # noqa: PT018
            participant.is_active = False
            participant.left_at = datetime.datetime.now(datetime.UTC)
            stored_hidden.reject_dispute_deadline_at = datetime.datetime.now(datetime.UTC)
        assert (await post(hidden.id, "55706", "Expired reason")).status_code == 409

    _schema, final = await schema_snapshot(database.engine)
    effect_tables = (
        "assignment_disputes",
        "moderation_cases",
        "outbox_events",
        "processed_telegram_updates",
        "account_transactions",
        "reliability_events",
        "audit_events",
    )
    assert tuple(final[name] - baseline[name] for name in effect_tables) == (2, 2, 2, 2, 0, 0, 0)
    async with sessions() as session:
        payloads = (await session.scalars(select(OutboxEventModel.payload_json))).all()
    assert "Private" not in json.dumps(payloads)
    await database.dispose()


async def test_creator_review_api_is_private_exact_and_domain_owned(database_url: str) -> None:
    database = Database(database_url)
    author, task = await _freeform_task(database, update_base=54_000)
    performer = await prepare_member(database, telegram_user_id=54_100)
    service = assignment_app.AssignmentService(database.unit_of_work)
    assignment = await service.accept(
        assignment_app.AcceptAssignmentCommand(54_200, performer.telegram_user_id, task.id)
    )
    await service.submit(
        assignment_app.SubmitResultCommand(
            54_201,
            performer.telegram_user_id,
            assignment.id,
            uuid4(),
            {"result": "Literal creator review result."},
        )
    )
    reviewer, community_id = await _community_task(database, update_base=54_300)
    _other, hidden_task = await _freeform_task(database, update_base=54_400)
    _low_owner, low_task = await _freeform_task(database, update_base=54_500)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        author.role = "administrator"
        session.add(author)
        community_source = await session.get(TaskModel, community_id)
        hidden_source = await session.get(TaskModel, hidden_task.id)
        low_source = await session.get(TaskModel, low_task.id)
        assert community_source and hidden_source and low_source  # noqa: PT018

        def clone(source: TaskModel, **changes: object) -> TaskModel:
            values = {
                column.key: getattr(source, column.key)
                for column in inspect(TaskModel).columns
                if column.key not in {"id", "created_at", "updated_at"}
            }
            return TaskModel(**(values | changes | {"publish_command_id": uuid4()}))

        run = DbTestRunModel(marker="TEST-CB73-HIDDEN", started_by_member_id=author.id)
        session.add(run)
        await session.flush()
        community = clone(community_source, created_by_admin_id=author.id)
        community.reviewer_admin_id = reviewer.id
        community.community_approved_by_admin_id = reviewer.id
        community_tasks = [community]
        community_tasks.extend(clone(community) for _index in range(51))
        hidden = clone(hidden_source, creator_id=author.id, test_run_id=run.id)
        low = clone(low_source, creator_id=author.id, credit_reward_per_performer=1)
        low.reserved_credit_total = 1
        session.add_all((*community_tasks, hidden, low))
        await session.flush()
        now = datetime.datetime.now(datetime.UTC)
        rows = [
            AssignmentModel(
                task_id=current.id,
                performer_id=performer.id,
                slot_number=1,
                status="submitted",
                accepted_at=now,
                submitted_at=now,
                review_deadline_at=now + datetime.timedelta(hours=72),
            )
            for current in (*community_tasks, hidden, low)
        ]
        session.add_all(rows)
        await session.flush()
        session.add_all(
            [
                AssignmentResultVersionModel(
                    assignment_id=row.id,
                    version=1,
                    payload_json={"result": f"hidden-{current.id}"},
                    submit_command_id=uuid4(),
                )
                for current, row in zip((*community_tasks, hidden, low), rows, strict=True)
            ]
        )

    app = create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, database_url=database_url),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post(
                "/api/v1/auth/telegram",
                content=proof(author.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
        ).status_code == 204
        page = await client.get("/api/v1/assignment-reviews")
        assert page.status_code == 200
        items = {UUID(item["id"]): item for item in page.json()["items"]}
        assert set(items) == {assignment.id, rows[-1].id}
        assert items[assignment.id]["available_decisions"] == ["full", "partial", "reject"]
        assert items[rows[-1].id]["available_decisions"] == ["full", "reject"]
        assert items[assignment.id]["result"] == "Literal creator review result."
        detail = await client.get(f"/api/v1/assignment-reviews/{assignment.id}")
        assert detail.status_code == 200
        for row in (rows[0], rows[-2]):
            hidden = await client.get(f"/api/v1/assignment-reviews/{row.id}")
            assert hidden.status_code == 404
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as foreign:
            await foreign.post(
                "/api/v1/auth/telegram",
                content=proof(performer.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert (await foreign.get("/api/v1/assignment-reviews")).json() == {"items": []}
            assert (
                await foreign.get(f"/api/v1/assignment-reviews/{assignment.id}")
            ).status_code == 404
        headers = {"origin": ORIGIN, "idempotency-key": "5473"}
        missing_reason = await client.post(
            f"/api/v1/assignment-reviews/{assignment.id}/decision",
            headers={"origin": ORIGIN, "idempotency-key": "5472"},
            json={"decision": "reject"},
        )
        assert missing_reason.status_code == 422
        assert (
            await client.post(
                f"/api/v1/assignment-reviews/{assignment.id}/decision",
                headers={"origin": ORIGIN, "idempotency-key": "5471"},
                json={"decision": "reject", "rejection_reason": "other"},
            )
        ).status_code == 422
        rejection_payload = {
            "decision": "reject",
            "rejection_reason": "insufficient_evidence",
            "rejection_comment": "Нужна ссылка на готовый результат.",
        }
        reject = await client.post(
            f"/api/v1/assignment-reviews/{assignment.id}/decision",
            headers=headers,
            json=rejection_payload,
        )
        assert reject.status_code == 204

        async def replay_reject() -> int:
            response = await client.post(
                reject.request.url.path, headers=headers, json=rejection_payload
            )
            return response.status_code

        assert await replay_reject() == 204
        assert (
            await client.post(
                reject.request.url.path,
                headers=headers,
                json={**rejection_payload, "rejection_comment": "Другая причина."},
            )
        ).status_code == 409
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as rejected_user:
            rejected_auth = await rejected_user.post(
                "/api/v1/auth/telegram",
                content=proof(
                    performer.telegram_user_id,
                    now=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1),
                ),
                headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
            )
            assert rejected_auth.status_code == 204
            rejected_detail = await rejected_user.get(
                f"/api/v1/assignments/{assignment.id}"
            )
            assert rejected_detail.status_code == 200
            assert rejected_detail.json()["rejection_reason"] == "insufficient_evidence"
            assert rejected_detail.json()["rejection_comment"] == (
                "Нужна ссылка на готовый результат."
            )
        assert (
            await client.post(
                reject.request.url.path, headers=headers, json={"decision": "partial"}
            )
        ).status_code == 409
        async with sessions() as session:
            stored = await session.get(AssignmentModel, assignment.id)
            assert stored is not None
            assert stored.status == "rejected_pending_dispute"
            assert stored.reject_dispute_deadline_at is not None
            assert stored.rejected_at is not None
            assert stored.rejection_reason == "insufficient_evidence"
            assert stored.rejection_comment == "Нужна ссылка на готовый результат."
            assert stored.reject_dispute_deadline_at - stored.rejected_at == datetime.timedelta(
                hours=24
            )
            ledger_count = await session.scalar(
                select(func.count())
                .select_from(AccountTransactionModel)
                .where(AccountTransactionModel.assignment_id == assignment.id)
            )
            reliability_count = await session.scalar(
                select(func.count())
                .select_from(ReliabilityEventModel)
                .where(ReliabilityEventModel.assignment_id == assignment.id)
            )
            outbox_count = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.aggregate_id == assignment.id)
            )
            assert (ledger_count, reliability_count, outbox_count) == (0, 1, 3)
            review_outbox = await session.scalar(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id == assignment.id,
                    OutboxEventModel.event_type == "assignment_rejection_pending_dispute",
                )
            )
            assert review_outbox is not None
            assert review_outbox.payload_json["rejection_reason"] == "insufficient_evidence"
            assert review_outbox.payload_json["rejection_comment"] == (
                "Нужна ссылка на готовый результат."
            )
        await service.finalize_rejection(
            assignment_id=assignment.id,
            command_id=uuid4(),
            now=stored.reject_dispute_deadline_at,
        )
        assert await replay_reject() == 204
        async with sessions.begin() as session:
            await session.execute(
                update(MemberModel).where(MemberModel.id == author.id).values(status="paused")
            )
        assert await replay_reject() == 409
        inactive_list = await client.get("/api/v1/assignment-reviews")
        inactive_detail = await client.get(f"/api/v1/assignment-reviews/{assignment.id}")
        assert (inactive_list.status_code, inactive_detail.status_code) == (403, 404)
    await database.dispose()


async def test_web_sessions_migration_preserves_existing_schema_and_data(
    database_url: str,
) -> None:
    await migrate(database_url, "downgrade 0020")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO members "
                "(id, telegram_user_id, display_name, timezone, role, status, "
                "level_number, credit_balance_cached, experience_total_cached) "
                "VALUES (:id, 52002, 'Migration member', 'UTC', 'member', 'active', 1, 0, 0)"
            ),
            {"id": uuid4()},
        )
    before_tables, before_counts = await schema_snapshot(engine)
    assert "web_sessions" not in before_tables
    await engine.dispose()

    await migrate(database_url, "upgrade 0021")
    engine = create_async_engine(database_url)
    after_tables, after_counts = await schema_snapshot(engine)
    assert after_tables == before_tables | {"web_sessions"}
    assert {table: after_counts[table] for table in before_counts} == before_counts
    assert after_counts["web_sessions"] == 0
    async with engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable, column_default "
                    "FROM information_schema.columns WHERE table_name='web_sessions' "
                    "ORDER BY ordinal_position"
                )
            )
        ).all()
        constraints = (
            await connection.execute(
                text(
                    "SELECT conname, contype::text, pg_get_constraintdef(oid) "
                    "FROM pg_constraint WHERE conrelid='web_sessions'::regclass "
                    "AND contype <> 'n' ORDER BY conname"
                )
            )
        ).all()
        indexes = (
            await connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='web_sessions'")
            )
        ).all()
    assert columns == [
        ("token_digest", "bytea", "NO", None),
        ("member_id", "uuid", "NO", None),
        ("created_at", "timestamptz", "NO", "now()"),
        ("authenticated_at", "timestamptz", "NO", None),
        ("expires_at", "timestamptz", "NO", None),
        ("revoked_at", "timestamptz", "YES", None),
    ]
    assert [(name, kind) for name, kind, _definition in constraints] == [
        ("ck_web_sessions_authenticated_at", "c"),
        ("ck_web_sessions_digest", "c"),
        ("ck_web_sessions_expiry", "c"),
        ("ck_web_sessions_revoked_at", "c"),
        ("web_sessions_member_id_fkey", "f"),
        ("web_sessions_pkey", "p"),
    ]
    definitions = (
        " ".join(definition for _name, _kind, definition in constraints)
        .replace(" ", "")
        .replace("(", "")
        .replace(")", "")
    )
    for fragment in (
        "authenticated_at<=expires_at",
        "octet_lengthtoken_digest=32",
        "expires_at>created_at",
        "revoked_atISNULLORrevoked_at>=created_at",
        "FOREIGNKEYmember_idREFERENCESmembersidONDELETERESTRICT",
        "PRIMARYKEYtoken_digest",
    ):
        assert fragment in definitions
    assert len(indexes) == 1
    assert "UNIQUE INDEX web_sessions_pkey" in indexes[0].indexdef
    await engine.dispose()
    await migrate(database_url, "downgrade 0020")
    engine = create_async_engine(database_url)
    downgraded_tables, downgraded_counts = await schema_snapshot(engine)
    assert downgraded_tables == before_tables
    assert downgraded_counts == before_counts
    await engine.dispose()


async def test_profile_links_migration_round_trip_and_constraints(database_url: str) -> None:
    await migrate(database_url, "downgrade 0021")
    engine = create_async_engine(database_url)
    member_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO members (id, telegram_user_id, display_name, timezone, role, status, "
                "level_number, credit_balance_cached, experience_total_cached) "
                "VALUES (:id, 52999, 'Legacy links member', 'UTC', 'member', 'active', 1, 0, 0)"
            ),
            {"id": member_id},
        )
    await engine.dispose()
    await migrate(database_url, "upgrade 0022")
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        column = (
            await connection.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name='members' AND column_name='profile_links_json'"
                )
            )
        ).one()
        constraints = set(
            await connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid='members'::regclass "
                    "AND conname LIKE 'ck_members_profile_links_%'"
                )
            )
        )
        stored = await connection.scalar(
            text("SELECT profile_links_json FROM members WHERE id=:id"), {"id": member_id}
        )
        assert stored == []
    assert column == ("NO", "'[]'::jsonb")
    assert constraints == {"ck_members_profile_links_array", "ck_members_profile_links_limit"}
    valid = [
        {"id": str(uuid4()), "label": str(index), "url": f"https://example.com/{index}"}
        for index in range(5)
    ]
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE members SET profile_links_json=CAST(:links AS jsonb) WHERE id=:id"),
            {"links": json.dumps(valid), "id": member_id},
        )
    for invalid in ({"bad": True}, [*valid, valid[0]]):
        with pytest.raises(SQLAlchemyError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE members SET profile_links_json=CAST(:links AS jsonb) WHERE id=:id"
                    ),
                    {"links": json.dumps(invalid), "id": member_id},
                )
    await engine.dispose()
    await migrate(database_url, "downgrade 0021")
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_name='members' "
                "AND column_name='profile_links_json'"
            )
        )
        assert count == 0
    await engine.dispose()
    await migrate(database_url, "upgrade 0022")


async def test_administrator_management_api_enforces_provenance_and_delegation(
    database_url: str,
) -> None:
    database = Database(database_url)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    owner_id, manager_id, target_id = uuid4(), uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add_all(
            (
                MemberModel(
                    id=owner_id,
                    telegram_user_id=91_001,
                    telegram_username="community_owner",
                    display_name="Alex Owner",
                    timezone="UTC",
                    role=MemberRole.ADMINISTRATOR.value,
                    status=MemberStatus.ACTIVE.value,
                    permissions_json=[SUPERADMINISTRATOR_PERMISSION],
                ),
                MemberModel(
                    id=manager_id,
                    telegram_user_id=91_002,
                    telegram_username="future_manager",
                    display_name="Schoonia",
                    timezone="UTC",
                    role=MemberRole.MEMBER.value,
                    status=MemberStatus.ACTIVE.value,
                ),
                MemberModel(
                    id=target_id,
                    telegram_user_id=91_003,
                    telegram_username="future_admin",
                    display_name="Kristina",
                    timezone="UTC",
                    role=MemberRole.MEMBER.value,
                    status=MemberStatus.ACTIVE.value,
                ),
            )
        )

    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            database_url=database_url,
        ),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as owner_client:
        authenticated = await owner_client.post(
            "/api/v1/auth/telegram",
            content=proof(91_001, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        overview = await owner_client.get("/api/v1/administration")
        assert overview.status_code == 200
        owner = next(item for item in overview.json()["items"] if item["is_owner"])
        assert owner["can_edit"] is False
        assert set(owner["permissions"]) == {
            "interaction_review",
            "member_invitation",
            "member_blocking",
            "administrator_management",
            "community_task_create",
            "community_task_review",
        }

        appointed = await owner_client.post(
            f"/api/v1/administration/{manager_id}",
            json={
                "permissions": [
                    ADMINISTRATOR_MANAGEMENT_PERMISSION,
                    MEMBER_INVITATION_PERMISSION,
                ]
            },
            headers={"origin": ORIGIN, "idempotency-key": "91001"},
        )
        assert appointed.status_code == 201, appointed.text
        assert appointed.json()["appointed_by"]["member_id"] == str(owner_id)
        owner_cookies = owner_client.cookies

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as manager_client:
        authenticated = await manager_client.post(
            "/api/v1/auth/telegram",
            content=proof(91_002, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        forbidden = await manager_client.post(
            f"/api/v1/administration/{target_id}",
            json={"permissions": [ADMINISTRATOR_MANAGEMENT_PERMISSION]},
            headers={"origin": ORIGIN, "idempotency-key": "91002"},
        )
        assert forbidden.status_code == 403
        delegated = await manager_client.post(
            f"/api/v1/administration/{target_id}",
            json={"permissions": [MEMBER_INVITATION_PERMISSION]},
            headers={"origin": ORIGIN, "idempotency-key": "91003"},
        )
        assert delegated.status_code == 201, delegated.text
        assert delegated.json()["appointed_by"]["member_id"] == str(manager_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, cookies=owner_cookies
    ) as owner_client:
        short_reason = await owner_client.post(
            f"/api/v1/administration/{manager_id}/demote",
            json={"reason": "x"},
            headers={"origin": ORIGIN, "idempotency-key": "91004"},
        )
        assert short_reason.status_code == 422
        demoted = await owner_client.post(
            f"/api/v1/administration/{manager_id}/demote",
            json={"reason": "Изменение зоны ответственности"},
            headers={"origin": ORIGIN, "idempotency-key": "91005"},
        )
        assert demoted.status_code == 200, demoted.text

    async with sessions() as session:
        manager = await session.get(MemberModel, manager_id)
        target = await session.get(MemberModel, target_id)
        audits = (
            await session.scalars(
                select(AuditEventModel)
                .where(
                    AuditEventModel.entity_id.in_((str(manager_id), str(target_id))),
                    AuditEventModel.action == "member_access_changed",
                )
                .order_by(AuditEventModel.created_at)
            )
        ).all()
        assert manager is not None
        assert manager.role == MemberRole.MEMBER.value
        assert manager.permissions_json == []
        assert target is not None
        assert target.administrator_appointed_by_member_id == manager_id
        assert [event.action for event in audits] == [
            "member_access_changed",
            "member_access_changed",
            "member_access_changed",
        ]
        assert audits[0].after_json is not None
        assert audits[1].after_json is not None
        assert audits[0].after_json["administrator_appointed_by_member_id"] == str(owner_id)
        assert audits[1].after_json["administrator_appointed_by_member_id"] == str(manager_id)
        assert audits[2].reason == "Изменение зоны ответственности"
    await database.dispose()


async def test_superadministrator_credit_grants_are_credit_only_idempotent_and_audited(
    database_url: str,
) -> None:
    database = Database(database_url)
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    owner = await add_member(
        database,
        92_001,
        telegram_username="credit_owner",
        display_name="Alex Owner",
        role=MemberRole.ADMINISTRATOR,
        permissions=[SUPERADMINISTRATOR_PERMISSION],
    )
    ordinary_admin = await add_member(
        database,
        92_002,
        telegram_username="ordinary_admin",
        role=MemberRole.ADMINISTRATOR,
        permissions=[MEMBER_INVITATION_PERMISSION],
    )
    recipient = await add_member(
        database,
        92_003,
        telegram_username="credit_recipient",
        display_name="Credit Recipient",
        status=MemberStatus.PAUSED,
    )
    async with sessions.begin() as session:
        stored = await session.get(MemberModel, recipient.id)
        assert stored is not None
        stored.experience_total_cached = 41
        stored.level_number = 4

    app = create_web_app(
        settings=Settings(
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            database_url=database_url,
        ),
        database=database,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(owner.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        overview = await client.get("/api/v1/administration")
        assert overview.json()["can_grant_credits"] is True
        own_card = await client.get("/api/v1/administration/credits/self")
        assert own_card.status_code == 200
        assert own_card.json()["member_id"] == str(owner.id)
        search = await client.get(
            "/api/v1/administration/credits/recipients",
            params={"query": "@credit_recip", "limit": 30},
        )
        assert search.status_code == 200
        assert [item["member_id"] for item in search.json()["items"]] == [str(recipient.id)]

        headers = {"origin": ORIGIN, "idempotency-key": "92001"}
        payload = {
            "target_member_id": str(recipient.id),
            "amount": 25,
            "reason": "Компенсация за техническую ошибку",
        }
        created = await client.post(
            "/api/v1/administration/credits/grants", json=payload, headers=headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["recipient"]["credit_balance"] == 25
        assert created.json()["replayed"] is False
        replayed = await client.post(
            "/api/v1/administration/credits/grants", json=payload, headers=headers
        )
        assert replayed.status_code == 201
        assert replayed.json()["transaction_id"] == created.json()["transaction_id"]
        assert replayed.json()["replayed"] is True

        self_grant = await client.post(
            "/api/v1/administration/credits/grants",
            json={
                "target_member_id": str(owner.id),
                "amount": 3,
                "reason": "Проверка начисления себе",  # noqa: RUF001
            },
            headers={"origin": ORIGIN, "idempotency-key": "92002"},
        )
        assert self_grant.status_code == 201, self_grant.text
        history = await client.get("/api/v1/administration/credits/history?limit=30")
        assert history.status_code == 200
        assert len(history.json()["items"]) == 2
        assert {item["amount"] for item in history.json()["items"]} == {3, 25}

    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        authenticated = await client.post(
            "/api/v1/auth/telegram",
            content=proof(ordinary_admin.telegram_user_id, now=datetime.datetime.now(datetime.UTC)),
            headers={"content-type": "text/plain; charset=utf-8", "origin": ORIGIN},
        )
        assert authenticated.status_code == 204
        forbidden = await client.get("/api/v1/administration/credits/self")
        assert forbidden.status_code == 403

    async with sessions() as session:
        stored = await session.get(MemberModel, recipient.id)
        assert stored is not None
        assert stored.credit_balance_cached == 25
        assert stored.experience_total_cached == 41
        assert stored.level_number == 4
        transactions = (
            await session.scalars(
                select(AccountTransactionModel).where(
                    AccountTransactionModel.transaction_type == "manual_credit_grant"
                )
            )
        ).all()
        assert len(transactions) == 2
        assert all(item.experience_delta == 0 for item in transactions)
        audits = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.action == "economy_administrative_mutation",
                    AuditEventModel.entity_id.in_([str(item.id) for item in transactions]),
                )
            )
        ).all()
        assert len(audits) == 2

    await database.dispose()
