from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from community_bot.compact_import import inventory_database

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_inventory_uses_a_role_that_defaults_to_read_only(database_url: str) -> None:
    role = f"cb51_readonly_{uuid4().hex}"
    password = uuid4().hex
    source_url = make_url(database_url)
    database = source_url.database
    assert database is not None
    admin = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
            await connection.exec_driver_sql(
                f'ALTER ROLE "{role}" SET default_transaction_read_only = on'
            )
            await connection.exec_driver_sql(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"')
            await connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            await connection.exec_driver_sql(
                f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
        readonly_url = source_url.set(username=role, password=password).render_as_string(
            hide_password=False
        )

        result = await inventory_database(readonly_url)

        assert result["schema"] == "community_bot.compact_inventory.v1"
        source = cast("dict[str, object]", result["source"])
        tables = cast("dict[str, object]", source["tables"])
        assert len(tables) == 43
        with pytest.raises(ValueError, match="default every transaction to read-only"):
            await inventory_database(database_url)
    finally:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            await connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        await admin.dispose()
