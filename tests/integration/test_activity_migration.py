from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from ops.wallet_cutover import (
    ACTIVITY_FINGERPRINT_SQL,
    ACTIVITY_INVARIANT_SQL,
    ONBOARDING_FINGERPRINT_SQL,
    ONBOARDING_INVARIANT_SQL,
)
from sqlalchemy import text

from community_bot.infrastructure.db.database import Database

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _migration(name: str, filename: str):  # noqa: ANN202
    path = Path(__file__).parents[2] / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def test_onboarding_cutover_preserves_schema_0036_data(database_url: str) -> None:
    crypto = _migration("crypto_cutover_migration", "0037_crypto_subscription.py")
    onboarding = _migration("onboarding_cutover_migration", "0038_bot_onboarding.py")
    db = Database(database_url)

    def verify(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            onboarding.downgrade()
            crypto.downgrade()
            before = connection.scalar(text(ONBOARDING_FINGERPRINT_SQL))
            crypto.upgrade()
            onboarding.upgrade()
            assert connection.scalar(text(ONBOARDING_FINGERPRINT_SQL)) == before
            assert connection.scalar(text(ONBOARDING_INVARIANT_SQL)) == "true"
            onboarding.downgrade()
            crypto.downgrade()
            assert connection.scalar(text(ONBOARDING_FINGERPRINT_SQL)) == before
            crypto.upgrade()
            onboarding.upgrade()

    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(verify)
    finally:
        await db.dispose()


async def test_crypto_migration_preserves_existing_choices_and_defaults_off(
    database_url: str,
) -> None:
    path = Path(__file__).parents[2] / "migrations/versions/0037_crypto_subscription.py"
    spec = importlib.util.spec_from_file_location("crypto_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db = Database(database_url)

    def verify(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            member_id = uuid4()
            connection.execute(
                text("""INSERT INTO members
                (id, telegram_user_id, display_name, timezone, status, role, level_number)
                VALUES (:id, 8803, 'Migration test', 'UTC', 'active', 'member', 1)"""),
                {"id": member_id},
            )
            connection.execute(
                text("""INSERT INTO member_notification_preferences
                (member_id, tasks, disputes, disputes_since, revision)
                VALUES (:id, false, true, now(), 4)"""),
                {"id": member_id},
            )
            snapshot = text("""SELECT to_jsonb(p) - 'crypto' - 'crypto_since'
                FROM member_notification_preferences p WHERE member_id=:id""")
            before = connection.scalar(snapshot, {"id": member_id})
            migration.upgrade()
            assert connection.scalar(snapshot, {"id": member_id}) == before
            assert connection.execute(
                text("""SELECT crypto, crypto_since
                FROM member_notification_preferences WHERE member_id=:id"""),
                {"id": member_id},
            ).one() == (False, None)
            migration.downgrade()
            assert connection.scalar(snapshot, {"id": member_id}) == before
            migration.upgrade()

    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(verify)
    finally:
        await db.dispose()


async def test_activity_migration_preserves_consent_and_retires_legacy_queue(
    database_url: str,
) -> None:
    # This is a migration-property test on the standard isolated database clone.
    path = Path(__file__).parents[2] / "migrations/versions/0035_activity_subscriptions.py"
    spec = importlib.util.spec_from_file_location("activity_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db = Database(database_url)

    def verify(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            for opted_in in (False, True):
                member_id = uuid4()
                connection.execute(
                    text("""INSERT INTO members
                    (id, telegram_user_id, display_name, timezone, status, role, level_number)
                    VALUES (:id, :telegram_id, 'Migration test', 'UTC', 'active', 'member', 1)"""),
                    {"id": member_id, "telegram_id": 8800 + int(opted_in)},
                )
                connection.execute(
                    text("""INSERT INTO member_notification_preferences
                    (member_id, tasks, tasks_since, nomad, nomad_since, revision)
                    VALUES (:id, :enabled, '2026-01-01T00:00:00Z', :enabled,
                    '2026-01-01T00:00:00Z', 7)"""),
                    {"id": member_id, "enabled": opted_in},
                )
                connection.execute(
                    text("""INSERT INTO notifications
                    (id, member_id, notification_type, payload_json, status, scheduled_at,
                    next_attempt_at, deduplication_key, attempt_count)
                    VALUES (:id, :member, 'nomad.published', '{}', 'pending',
                    now(), now(), :key, 0)"""),
                    {"id": uuid4(), "member": member_id, "key": str(uuid4())},
                )
            before = connection.scalar(text(ACTIVITY_FINGERPRINT_SQL))
            migration.upgrade()
            assert connection.scalar(text(ACTIVITY_FINGERPRINT_SQL)) == before
            assert connection.scalar(text(ACTIVITY_INVARIANT_SQL)) == "true"
            rows = (
                connection.execute(
                    text("""SELECT tasks, nomad, online, offline,
                task_updates, task_reminders, disputes, revision,
                task_updates_since=tasks_since AS same_since
                FROM member_notification_preferences ORDER BY tasks""")
                )
                .mappings()
                .all()
            )
            assert len(rows) == 2
            for row in rows:
                assert row["nomad"] == row["tasks"]
                assert not row["online"]
                assert not row["offline"]
                assert row["task_updates"] == row["tasks"]
                assert row["task_reminders"] == row["tasks"]
                assert row["disputes"] == row["tasks"]
                assert row["revision"] == 8
                assert row["same_since"]
            assert (
                connection.scalar(
                    text("""SELECT count(*) FROM notifications
                WHERE status='failed' AND last_error_code='legacy_topic_retired'""")
                )
                == 2
            )

    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(verify)
    finally:
        await db.dispose()
