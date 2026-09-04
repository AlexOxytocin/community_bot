"""Real dump/restore, migration rehearsal and transactional database-name recovery."""

from __future__ import annotations

# ruff: noqa: S608 - interpolated SQL identifiers are generated UUID objects only.
import os
import subprocess
import sys
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from ops import wallet_cutover as cutover
from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def test_postgres_wallet_restore_and_failed_migration_recovery(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = make_url(database_url)
    assert url.database is not None
    assert url.database.startswith("test_")
    assert url.username is not None
    # Reuse the shared fixture's existing PostgreSQL; never start another server.
    candidates = cutover.run(
        "docker", "ps", "--filter", f"publish={url.port}", "--format", "{{.ID}}"
    ).splitlines()
    assert len(candidates) == 1
    host = object.__new__(cutover.Host)
    host.database, host.user = url.database, url.username
    suffix = uuid4().hex
    host.receipt = {
        "postgres": candidates[0],
        "backup": str(tmp_path / "frozen.dump"),
        "restore_db": f"wallet_restore_{suffix}",
        "failed_db": f"wallet_failed_{suffix}",
    }
    events: list[str] = []
    monkeypatch.setattr(host, "stopped", lambda: None)
    monkeypatch.setattr(host, "stop", lambda: events.append("stopped"))
    monkeypatch.setattr(host, "start", lambda **_: events.append("old_started"))
    monkeypatch.setattr(host, "verify", lambda **_: events.append("old_verified"))

    def migrate(*, database: str | None = None, downgrade: bool = False) -> None:
        destination = url.set(database=database or host.database)
        env = os.environ | {"DATABASE_URL": destination.render_as_string(hide_password=False)}
        result = subprocess.run(  # noqa: S603 - fixed Alembic executable against an isolated test DB.
            [
                sys.executable,
                "-m",
                "alembic",
                "downgrade" if downgrade else "upgrade",
                "0031" if downgrade else "head",
            ],
            env=env,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, "Migration rehearsal failed (private output withheld)."

    monkeypatch.setattr(host, "migrate", migrate)
    migrate(downgrade=True)
    member = uuid4()
    host.sql(
        f"INSERT INTO members (id,telegram_user_id,display_name,timezone,role,status,"
        f"level_number,credit_balance_cached) VALUES ('{member}',8181,'Fixture','UTC',"
        "'member','active',1,10)"
    )
    host.sql(
        f"INSERT INTO account_transactions (id,member_id,credit_delta,experience_delta,"
        f"transaction_type,idempotency_key,payload_hash) VALUES ('{uuid4()}','{member}',"
        f"10,0,'starting_grant','starting_grant:{member}',repeat('a',64))"
    )
    try:
        host.backup_restore()
        assert host.receipt["restore_verified"]
        assert host.head() == "0031"
        assert host.head(host.receipt["restore_db"]) == "0031"
        migrate()
        assert host.head() == "0032"
        host.rollback()
        assert host.head() == "0031"
        assert host.head(host.receipt["failed_db"]) == "0032"
        assert host.fingerprint() == host.receipt["fingerprint"]
        assert events == ["stopped", "old_started", "old_verified"]
        # Crash/retry after the atomic rename is safe: restored DB remains live.
        host.rollback()
        assert host.head() == "0031"
    finally:
        for name in (host.receipt["restore_db"], host.receipt["failed_db"]):
            cutover.run(
                "docker",
                "exec",
                candidates[0],
                "dropdb",
                "-U",
                host.user,
                "--if-exists",
                "--force",
                name,
            )
