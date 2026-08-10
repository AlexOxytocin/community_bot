"""Asynchronous PostgreSQL connectivity check."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def database_healthcheck(database_url: str) -> bool:
    """Execute a minimal database query and release the engine."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            result = await connection.scalar(text("SELECT 1"))
        return result == 1
    finally:
        await engine.dispose()
