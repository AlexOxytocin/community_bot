"""Asynchronous PostgreSQL connectivity check."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass

from sqlalchemy import text

from community_bot.bootstrap.migration_head import single_migration_head
from community_bot.infrastructure.db.database import Database

_EXPECTED_LEVEL_COUNT = 10
_HEARTBEAT_FUTURE_TOLERANCE = datetime.timedelta(seconds=5)


async def database_healthcheck(database_url: str) -> bool:
    """Execute a minimal database query and release the engine."""
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            result = await connection.scalar(text("SELECT 1"))
        return result == 1
    finally:
        await database.dispose()


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Safe machine-readable readiness result."""

    healthy: bool
    database: bool
    migration: bool
    product_config: bool
    heartbeat: bool
    failed_outbox_events: int
    code: str

    def as_dict(self) -> dict[str, bool | int | str]:
        """Return a JSON-ready projection without connection details."""
        return asdict(self)


async def readiness_report(  # noqa: C901, PLR0913 - independent deployment gates.
    database_url: str,
    *,
    process_name: str,
    heartbeat_max_age: datetime.timedelta,
    expected_release: str | None = None,
    heartbeat_not_before: datetime.datetime | None = None,
    now: datetime.datetime | None = None,
) -> ReadinessReport:
    """Check PostgreSQL, Alembic head, heartbeat freshness, and poison events."""
    observed_now = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            if await connection.scalar(text("SELECT 1")) != 1:
                return _unhealthy("database_unavailable")
            revisions = tuple(
                (
                    await connection.scalars(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).all()
            )
            heartbeat_result = await connection.execute(
                text(
                    "SELECT observed_at, release, migration_revision FROM process_heartbeats "
                    "WHERE process_name = :process_name"
                ),
                {"process_name": process_name},
            )
            heartbeat_row = heartbeat_result.one_or_none()
            failed_count = int(
                await connection.scalar(
                    text("SELECT count(*) FROM outbox_events WHERE status = 'failed'")
                )
                or 0
            )
            active_config_id = await connection.scalar(
                text(
                    "SELECT product_config_version_id FROM active_product_config "
                    "WHERE singleton_key"
                )
            )
            level_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM levels WHERE product_config_version_id = :config_id"
                    ),
                    {"config_id": active_config_id},
                )
                or 0
            )
            stale_member_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM members WHERE status = 'active' AND "
                        "level_config_version_id IS DISTINCT FROM :config_id"
                    ),
                    {"config_id": active_config_id},
                )
                or 0
            )
    except Exception:  # noqa: BLE001 - health boundary always returns a safe result.
        return _unhealthy("database_unavailable")
    finally:
        await database.dispose()

    expected_revision = single_migration_head()
    migration_ok = revisions == (expected_revision,)
    product_config_ok = (
        active_config_id is not None
        and level_count == _EXPECTED_LEVEL_COUNT
        and stale_member_count == 0
    )
    heartbeat_at = heartbeat_row.observed_at if heartbeat_row is not None else None
    heartbeat_release = heartbeat_row.release if heartbeat_row is not None else None
    heartbeat_revision = heartbeat_row.migration_revision if heartbeat_row is not None else None
    heartbeat_in_future = isinstance(heartbeat_at, datetime.datetime) and (
        heartbeat_at.astimezone(datetime.UTC) - observed_now > _HEARTBEAT_FUTURE_TOLERANCE
    )
    heartbeat_fresh = (
        isinstance(heartbeat_at, datetime.datetime)
        and not heartbeat_in_future
        and observed_now - heartbeat_at.astimezone(datetime.UTC) <= heartbeat_max_age
    )
    release_ok = expected_release is None or heartbeat_release == expected_release
    revision_ok = heartbeat_revision == expected_revision
    not_before = (
        heartbeat_not_before.astimezone(datetime.UTC) if heartbeat_not_before is not None else None
    )
    heartbeat_started_after_deploy = not_before is None or (
        isinstance(heartbeat_at, datetime.datetime)
        and heartbeat_at.astimezone(datetime.UTC) >= not_before
    )
    heartbeat_ok = heartbeat_fresh and release_ok and revision_ok and heartbeat_started_after_deploy
    if not migration_ok:
        code = "migration_mismatch"
    elif not product_config_ok:
        code = "product_config_incomplete"
    elif heartbeat_in_future:
        code = "heartbeat_in_future"
    elif not heartbeat_fresh:
        code = "heartbeat_stale"
    elif not release_ok:
        code = "heartbeat_release_mismatch"
    elif not revision_ok:
        code = "heartbeat_revision_mismatch"
    elif not heartbeat_started_after_deploy:
        code = "heartbeat_before_deploy"
    elif failed_count:
        code = "outbox_failed"
    else:
        code = "ready"
    return ReadinessReport(
        healthy=migration_ok and product_config_ok and heartbeat_ok and failed_count == 0,
        database=True,
        migration=migration_ok,
        product_config=product_config_ok,
        heartbeat=heartbeat_ok,
        failed_outbox_events=failed_count,
        code=code,
    )


def _unhealthy(code: str) -> ReadinessReport:
    return ReadinessReport(
        healthy=False,
        database=False,
        migration=False,
        product_config=False,
        heartbeat=False,
        failed_outbox_events=0,
        code=code,
    )
