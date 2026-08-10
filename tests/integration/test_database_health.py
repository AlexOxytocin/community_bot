from __future__ import annotations

import pytest

from community_bot.infrastructure.db import database_healthcheck

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_database_healthcheck_executes_select_one(database_url: str) -> None:
    assert await database_healthcheck(database_url)
