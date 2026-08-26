from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

PROJECT_ROOT = Path(__file__).parents[2]

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session")
def postgresql_server_url() -> Iterator[str]:
    """Provide Compose PostgreSQL or start PostgreSQL 18 automatically."""
    configured_url = os.getenv("DATABASE_URL")
    if configured_url is not None:
        yield configured_url
        return

    with PostgresContainer("postgres:18", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def migrated_template_database(postgresql_server_url: str) -> Iterator[tuple[URL, str]]:
    """Migrate one template database used to clone isolated test databases."""
    server_url = make_url(postgresql_server_url)
    database_name = f"template_{uuid4().hex}"
    asyncio.run(_database_command(server_url, f'CREATE DATABASE "{database_name}"'))
    template_url = server_url.set(database=database_name)
    migration_environment = os.environ.copy()
    migration_environment["DATABASE_URL"] = template_url.render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=migration_environment,
        check=True,
    )
    try:
        yield server_url, database_name
    finally:
        asyncio.run(
            _database_command(
                server_url,
                f'DROP DATABASE "{database_name}" WITH (FORCE)',
            )
        )


@pytest.fixture
def database_url(migrated_template_database: tuple[URL, str]) -> Iterator[str]:
    """Clone a migrated template and force-drop the isolated database after the test."""
    server_url, template_name = migrated_template_database
    database_name = f"test_{uuid4().hex}"
    asyncio.run(
        _database_command(
            server_url,
            f'CREATE DATABASE "{database_name}" TEMPLATE "{template_name}"',
        )
    )
    test_url = server_url.set(database=database_name)
    try:
        yield test_url.render_as_string(hide_password=False)
    finally:
        asyncio.run(
            _database_command(
                server_url,
                f'DROP DATABASE "{database_name}" WITH (FORCE)',
            )
        )


async def _database_command(server_url: URL, command: str) -> None:
    maintenance_url = server_url.set(database="postgres")
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(command))
    finally:
        await engine.dispose()
