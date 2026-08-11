"""Integration checks for pilot reporting and supported-schema readiness."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from community_bot.application.pilot import PilotMetricsService
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import AccountTransactionModel, MemberModel
from community_bot.infrastructure.db.pilot import PostgresPilotMetrics

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).parents[2]


def test_supported_schema_upgrade_preserves_outbox_semantics(
    postgresql_server_url: str,
) -> None:
    """Migration 0010 backfills old outbox rows and installs its DB guards."""
    server_url = make_url(postgresql_server_url)
    database_name = f"test_pilot_migration_{uuid4().hex}"
    asyncio.run(_database_command(server_url, f'CREATE DATABASE "{database_name}"'))
    database_url = server_url.set(database=database_name)
    try:
        _alembic(database_url, "0009")
        expected = asyncio.run(_seed_legacy_outbox(database_url))
        _alembic(database_url, "head")
        asyncio.run(_assert_upgraded_outbox(database_url, expected))
        _alembic(database_url, "head")
        asyncio.run(_assert_upgraded_outbox(database_url, expected))
    finally:
        asyncio.run(_database_command(server_url, f'DROP DATABASE "{database_name}" WITH (FORCE)'))


def test_empty_database_cycles_and_restores_catalog_seed(database_url: str) -> None:
    """An empty database returns to head with the canonical eight-by-eight seed."""
    url = make_url(database_url)
    _alembic(url, "base", downgrade=True)
    _alembic(url, "head")
    counts = asyncio.run(_catalog_counts(url))
    assert counts == (8, 8, "0010")


@pytest.mark.asyncio
async def test_pilot_report_is_ledger_authoritative_and_contains_no_member_data(
    database_url: str,
) -> None:
    """The real adapter ignores caches and emits only privacy-safe aggregates."""
    database = Database(database_url)
    now = datetime.datetime.now(datetime.UTC)
    members = [
        MemberModel(
            telegram_user_id=9_910_000 + index,
            display_name=f"Private Pilot Member {index}",
            timezone="UTC",
            role="member",
            status="active",
            approved_at=now - datetime.timedelta(hours=2),
            credit_balance_cached=999,
            experience_total_cached=999,
        )
        for index in range(3)
    ]
    async with database.session_factory.begin() as session:
        session.add_all(members)
        await session.flush()
        session.add_all(
            AccountTransactionModel(
                member_id=member.id,
                credit_delta=5,
                experience_delta=0,
                transaction_type="starting_grant",
                idempotency_key=f"pilot-ledger:{member.id}",
                payload_hash="0" * 64,
            )
            for member in members
        )
    report = await PilotMetricsService(PostgresPilotMetrics(database.session_factory)).report(
        from_at=now - datetime.timedelta(days=1),
        to_at=now + datetime.timedelta(days=1),
        generated_at=now,
    )
    payload = report.model_dump_json()
    assert report.current_active_members == 3
    assert [cell.model_dump() for cell in report.credit_distribution.cells] == [
        {"label": "5-9", "count": 3}
    ]
    assert [cell.model_dump() for cell in report.experience_distribution.cells] == [
        {"label": "0", "count": 3}
    ]
    assert "Private Pilot Member" not in payload
    assert "991000" not in payload
    assert all(str(member.id) not in payload for member in members)
    await database.dispose()


async def _seed_legacy_outbox(url: URL) -> dict[str, tuple[object, ...]]:
    engine = create_async_engine(url)
    unpublished_id, published_id, aggregate_id = uuid4(), uuid4(), uuid4()
    created_at = datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.UTC)
    published_at = created_at + datetime.timedelta(minutes=5)
    rows = {
        "pilot:pending": (unpublished_id, {"kind": "pending"}, created_at, None),
        "pilot:published": (published_id, {"kind": "published"}, created_at, published_at),
    }
    try:
        async with engine.begin() as connection:
            for business_key, (
                event_id,
                payload,
                event_created_at,
                event_published_at,
            ) in rows.items():
                await connection.execute(
                    text(
                        "INSERT INTO outbox_events "
                        "(id,event_type,aggregate_type,aggregate_id,payload_json,business_key,"
                        "created_at,published_at) VALUES "
                        "(:id,'pilot.event','pilot',:aggregate_id,CAST(:payload AS jsonb),"
                        ":business_key,:created_at,:published_at)"
                    ),
                    {
                        "id": event_id,
                        "aggregate_id": aggregate_id,
                        "payload": json.dumps(payload),
                        "business_key": business_key,
                        "created_at": event_created_at,
                        "published_at": event_published_at,
                    },
                )
    finally:
        await engine.dispose()
    return rows


async def _assert_upgraded_outbox(
    url: URL,
    expected: dict[str, tuple[object, ...]],
) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT id,payload_json,created_at,published_at,status,attempt_count,"
                        "next_attempt_at FROM outbox_events ORDER BY business_key"
                    )
                )
            ).all()
            assert len(rows) == 2
            pending, published = rows
            for row, business_key in zip(rows, sorted(expected), strict=True):
                event_id, payload, created_at, published_at = expected[business_key]
                assert tuple(row[:4]) == (event_id, payload, created_at, published_at)
                assert row.attempt_count == 0
                assert row.next_attempt_at is not None
            assert pending.status == "pending"
            assert published.status == "materialized"
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conrelid IN "
                        "('outbox_events'::regclass,'notifications'::regclass)"
                    )
                )
            )
            indexes = set(
                await connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE tablename IN "
                        "('outbox_events','notifications')"
                    )
                )
            )
            assert {
                "ck_outbox_status",
                "ck_outbox_lease_state",
                "ck_outbox_materialized_at",
                "ck_outbox_failed_error",
                "ck_notifications_status",
                "ck_notifications_lease_state",
            } <= constraints
            assert {"ix_outbox_due", "ix_notifications_due"} <= indexes
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
            )
            invalid_states = (
                "UPDATE outbox_events SET status='processing' WHERE business_key='pilot:pending'",
                (
                    "UPDATE outbox_events SET status='failed',last_error_code=NULL "
                    "WHERE business_key='pilot:pending'"
                ),
                (
                    "UPDATE outbox_events SET status='materialized',published_at=NULL "
                    "WHERE business_key='pilot:pending'"
                ),
            )
            for statement in invalid_states:
                savepoint = await connection.begin_nested()
                with pytest.raises(DBAPIError):
                    await connection.execute(text(statement))
                await savepoint.rollback()
    finally:
        await engine.dispose()


async def _catalog_counts(url: URL) -> tuple[int, int, str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            categories = await connection.scalar(text("SELECT count(*) FROM task_categories"))
            templates = await connection.scalar(text("SELECT count(*) FROM task_templates"))
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            return int(categories or 0), int(templates or 0), str(revision)
    finally:
        await engine.dispose()


def _alembic(url: URL, revision: str, *, downgrade: bool = False) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    subprocess.run(  # noqa: S603 - fixed interpreter and Alembic arguments.
        [sys.executable, "-m", "alembic", "downgrade" if downgrade else "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


async def _database_command(server_url: URL, command: str) -> None:
    maintenance_url = server_url.set(database="postgres")
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(command))
    finally:
        await engine.dispose()
