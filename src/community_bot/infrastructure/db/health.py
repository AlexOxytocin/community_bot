"""Asynchronous PostgreSQL connectivity check."""

from __future__ import annotations

from sqlalchemy import text

from community_bot.infrastructure.db.database import Database


async def database_healthcheck(database_url: str) -> bool:
    """Execute a minimal database query and release the engine."""
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            result = await connection.scalar(text("SELECT 1"))
        return result == 1
    finally:
        await database.dispose()
