from __future__ import annotations

import os

import pytest

from community_bot.infrastructure.db import database_healthcheck

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_database_healthcheck_executes_select_one() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test.")

    assert await database_healthcheck(database_url)
