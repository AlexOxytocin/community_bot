from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from community_bot.application import assignments as assignment_app
from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import Settings
from community_bot.domain.members import MemberRole, MemberStatus
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
    KarmaVoteHistoryModel,
    KarmaVoteModel,
    MemberModel,
    MemberSanctionModel,
    ModerationCaseModel,
    NotificationModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
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


def proof(user_id: int, *, now: datetime.datetime) -> bytes:
    fields = {
        "auth_date": str(int(now.timestamp())),
        "query_id": "integration-query",
        "user": json.dumps({"id": user_id, "first_name": "Web"}, separators=(",", ":")),
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
            "/api/v1/me/profile", json={"field": "city", "value": " Rosario "}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["city"] == "Rosario"
        assert saved.json()["display_name"] == "Web Member"

        replay = await client.put(
            "/api/v1/me/profile", json={"field": "city", "value": " Rosario "}, headers=headers
        )
        assert replay.status_code == 200
        conflict = await client.put(
            "/api/v1/me/profile",
            json={"field": "current_goal", "value": "Другой command"},
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

        city, goal = await asyncio.gather(
            client.put(
                "/api/v1/me/profile",
                json={"field": "city", "value": "Córdoba"},
                headers={"origin": ORIGIN, "idempotency-key": "8105"},
            ),
            client.put(
                "/api/v1/me/profile",
                json={"field": "current_goal", "value": "Запустить пилот"},
                headers={"origin": ORIGIN, "idempotency-key": "8106"},
            ),
        )
        assert city.status_code == goal.status_code == 200
        authoritative = (await client.get("/api/v1/me")).json()
        assert authoritative["city"] == "Córdoba"
        assert authoritative["current_goal"] == "Запустить пилот"

        async with sessions.begin() as session:
            stored_member = await session.get(MemberModel, member.id)
            assert stored_member is not None
            stored_member.status = MemberStatus.PAUSED.value
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
        assert profile_audits == web_receipts == 3
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
            "city": "  Buenos Aires  ",
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
                "city": form["city"].strip(),
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
        assert preview["draft"]["values"]["city"] == "Buenos Aires"

        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions.begin() as session:
            stored = await session.get(TaskCreationDraftModel, UUID(draft_id))
            assert stored is not None
            stored.deadline_at = now - datetime.timedelta(minutes=1)
        expired = (await client.get("/api/v1/task-creation")).json()
        assert expired["needs_edit"] is True
        assert expired["preview"] is None
        repaired = save | {"expected_revision": 1, "form": form}
        assert (
            await client.post(
                "/api/v1/task-creation",
                json=repaired,
                headers={"origin": ORIGIN, "idempotency-key": "7003"},
            )
        ).status_code == 204
        publish = {"action": "publish", "draft_id": draft_id, "expected_revision": 2}
        publish_headers = {"origin": ORIGIN, "idempotency-key": "7004"}
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
                DbTestRunParticipantModel(run_id=run.id, member_id=creator.id, is_active=False),
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
        assert first.status_code == replay.status_code == 204
        assert conflict.status_code == stale.status_code == 409

    async with sessions() as session:
        stored_case = await session.get(ModerationCaseModel, case.id)
        assignment = await session.get(AssignmentModel, case.assignment_id)
        assert stored_case is not None
        assert stored_case.status == "resolved"
        assert stored_case.revision == 1
        assert assignment is not None
        assert assignment.status == "partially_approved"
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
        assert (await client.get("/api/v1/members", params={"query": "@"})).status_code == 422

    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions() as session:
        stored = (await session.scalars(select(WebSessionModel))).one()
        assert (
            stored.token_digest
            == hashlib.sha256(__import__("base64").b64decode(f"{token}=", altchars=b"-_")).digest()
        )
        assert token.encode() not in stored.token_digest
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
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        author_model = await session.get(MemberModel, author.id)
        foreign_author_model = await session.get(MemberModel, foreign_author.id)
        source = await session.get(TaskModel, foreign.id)
        assert author_model is not None
        assert foreign_author_model is not None
        assert source is not None
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
        assert response.json()["items"] == [
            {
                "id": str(owned.id),
                "title": owned.title,
                "status": "published",
                "performer_slots": 1,
                "deadline_at": owned.deadline_at.isoformat().replace("+00:00", "Z"),
                "assignees": [{"display_name": performer.display_name, "status": "accepted"}],
                "cancellation_status": None,
            }
        ]

    await database.dispose()


async def test_web_submission_draft_is_bounded_exact_and_template_closed(database_url: str) -> None:
    database = Database(database_url)
    _author, freeform_task = await _freeform_task(database, update_base=52_750)
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
        assert detail.json()["submission_contract"] == "freeform_result_v1"

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
            "assignment_status",
            "accepted_at",
            "submitted_at",
            "review_deadline_at",
            "reject_dispute_deadline_at",
            "reviewed_at",
            "task_deadline_at",
            "result_summary",
            "case_status",
        }
        assert all(set(item) == list_keys for item in first.json()["items"])
        detail = await client.get(f"/api/v1/assignments/{first_assignment.id}")
        assert detail.status_code == 200, detail.text
        assert set(detail.json()) == list_keys | {
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
        for body in ({}, {"comment": ""}, {"comment": "   "}):
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
            denied = await outsider.post(path, headers=headers, json={"comment": "Foreign"})
            assert (denied.status_code, denied.json()) == (
                409,
                {"code": "assignment_unavailable"},
            )

        async with sessions.begin() as session:
            run = DbTestRunModel(marker="TEST-CB74-HIDDEN", started_by_member_id=hidden_author.id)
            session.add(run)
            await session.flush()
            session.add(DbTestRunParticipantModel(run_id=run.id, member_id=performer.id))
        hidden_response = await post(hidden.id, "55705", "Hidden")
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
        assert (await post(hidden.id, "55706", "Expired")).status_code == 409

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
        reject = await client.post(
            f"/api/v1/assignment-reviews/{assignment.id}/decision",
            headers=headers,
            json={"decision": "reject"},
        )
        assert reject.status_code == 204

        async def replay_reject() -> int:
            response = await client.post(
                reject.request.url.path, headers=headers, json={"decision": "reject"}
            )
            return response.status_code

        assert await replay_reject() == 204
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
