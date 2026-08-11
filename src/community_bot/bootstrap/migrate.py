"""Single-owner Alembic migration gate for the worker pre-deploy step."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from community_bot.bootstrap.settings import get_settings
from community_bot.infrastructure.db import Database
from community_bot.infrastructure.observability import configure_logging, configure_sentry

_LOCK_KEY_SQL = "hashtextextended('community_migrations', 0)"


def main() -> int:
    """Run `alembic upgrade head` while holding the shared migration lock."""
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_sentry(
        settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
    )
    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001 - CLI must fail closed with a safe log.
        structlog.get_logger(process="community-migrate").exception("migration_gate_failed")
        return 1


async def _run() -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    expected = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text(f"SELECT pg_advisory_lock({_LOCK_KEY_SQL})"))
            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    check=False,
                )
                if completed.returncode != 0:
                    return completed.returncode
                actual = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                if actual != expected:
                    return 1
            finally:
                await connection.execute(text(f"SELECT pg_advisory_unlock({_LOCK_KEY_SQL})"))
    finally:
        await database.dispose()
    structlog.get_logger(process="community-migrate").info(
        "migration_gate_passed", revision=expected
    )
    return 0
