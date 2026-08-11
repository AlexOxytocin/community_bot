"""Asynchronous PostgreSQL connectivity check."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from community_bot.infrastructure.db.database import Database

_EXPECTED_LEVEL_COUNT = 10


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


async def readiness_report(
    database_url: str,
    *,
    process_name: str,
    heartbeat_max_age: datetime.timedelta,
    now: datetime.datetime | None = None,
) -> ReadinessReport:
    """Check PostgreSQL, Alembic head, heartbeat freshness, and poison events."""
    observed_now = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            if await connection.scalar(text("SELECT 1")) != 1:
                return _unhealthy("database_unavailable")
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            heartbeat_at = await connection.scalar(
                text(
                    "SELECT observed_at FROM process_heartbeats WHERE process_name = :process_name"
                ),
                {"process_name": process_name},
            )
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

    expected_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    migration_ok = revision == expected_revision
    product_config_ok = (
        active_config_id is not None
        and level_count == _EXPECTED_LEVEL_COUNT
        and stale_member_count == 0
    )
    heartbeat_ok = (
        isinstance(heartbeat_at, datetime.datetime)
        and observed_now - heartbeat_at.astimezone(datetime.UTC) <= heartbeat_max_age
    )
    if not migration_ok:
        code = "migration_mismatch"
    elif not product_config_ok:
        code = "product_config_incomplete"
    elif not heartbeat_ok:
        code = "heartbeat_stale"
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
