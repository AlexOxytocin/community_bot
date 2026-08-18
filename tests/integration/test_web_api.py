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

from community_bot.application.economy import ProductConfigBootstrapCoordinator
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import Settings
from community_bot.domain.members import MemberRole, MemberStatus
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    AssignmentModel,
    AuditEventModel,
    MemberModel,
    OutboxEventModel,
    ProcessedTelegramUpdateModel,
    ReliabilityEventModel,
    TaskModel,
    WebSessionModel,
)
from community_bot.transport.web import _accept_update_id, create_web_app
from tests.integration.test_assignments import _published_task
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


async def test_catalog_detail_projection_and_accept_path(database_url: str) -> None:
    database = Database(database_url)
    _author, task = await _published_task(database, update_base=52_500)
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

    first_update_id = _accept_update_id(performer.id, task.id, "9001")
    second_update_id = _accept_update_id(performer.id, task.id, "9002")
    async with sessions() as session:
        assignment_id = UUID(assignment["id"])
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
                    ReliabilityEventModel.event_type == "accepted",
                )
            )
            == 1
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
