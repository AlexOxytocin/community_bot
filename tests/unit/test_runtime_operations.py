"""Unit coverage for health and migration runtime orchestration."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from community_bot.bootstrap import health as health_module
from community_bot.bootstrap import migrate as migrate_module


@pytest.mark.parametrize(("healthy", "expected_code"), [(True, 0), (False, 1)])
def test_health_entrypoint_reports_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    healthy: bool,
    expected_code: int,
) -> None:
    """Health CLI forwards settings and returns the readiness outcome."""
    captured: dict[str, object] = {}

    async def fake_readiness_report(
        database_url: object,
        *,
        process_name: str,
        heartbeat_max_age: object,
    ) -> object:
        captured.update(
            database_url=database_url,
            process_name=process_name,
            heartbeat_max_age=heartbeat_max_age,
        )
        return SimpleNamespace(
            healthy=healthy,
            as_dict=lambda: {"healthy": healthy, "code": "ready" if healthy else "stale"},
        )

    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://db", heartbeat_max_age_seconds=45),
    )
    monkeypatch.setattr(health_module, "readiness_report", fake_readiness_report)

    assert health_module.main(["--process", "community-worker"]) == expected_code
    assert captured["process_name"] == "community-worker"
    assert "45" in str(captured["heartbeat_max_age"])
    assert f'"healthy": {str(healthy).lower()}' in capsys.readouterr().out


@pytest.mark.parametrize("raises", [False, True])
def test_migration_entrypoint_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raises: bool,
) -> None:
    """Migration CLI configures observability and converts failures to exit 1."""
    calls: list[str] = []

    async def fake_run() -> int:
        if raises:
            message = "private database failure"
            raise RuntimeError(message)
        return 0

    monkeypatch.setattr(
        migrate_module,
        "get_settings",
        lambda: SimpleNamespace(
            log_level="INFO", sentry_dsn=None, environment="test", release="sha"
        ),
    )
    monkeypatch.setattr(migrate_module, "configure_logging", lambda _level: calls.append("log"))
    monkeypatch.setattr(
        migrate_module,
        "configure_sentry",
        lambda *_args, **_kwargs: calls.append("sentry"),
    )
    monkeypatch.setattr(migrate_module, "_run", fake_run)
    monkeypatch.setattr(
        migrate_module.structlog,
        "get_logger",
        lambda **_kwargs: SimpleNamespace(exception=lambda _event: calls.append("error")),
    )

    assert migrate_module.main() == (1 if raises else 0)
    assert calls[:2] == ["log", "sentry"]
    assert ("error" in calls) is raises


class _FakeConnection:
    def __init__(self, actual_revision: str) -> None:
        self.actual_revision = actual_revision
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))

    async def scalar(self, _statement: object) -> str:
        return self.actual_revision


class _ConnectionContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self.engine = SimpleNamespace(connect=lambda: _ConnectionContext(connection))
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.mark.parametrize(
    ("migration_returncode", "actual_revision", "expected_code"),
    [(0, "0010", 0), (0, "0009", 1), (7, "0010", 7)],
)
def test_migration_gate_unlocks_and_disposes_for_all_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    migration_returncode: int,
    actual_revision: str,
    expected_code: int,
) -> None:
    """Migration gate preserves lock cleanup and exact revision verification."""
    connection = _FakeConnection(actual_revision)
    database = _FakeDatabase(connection)
    logged: list[tuple[str, str]] = []

    monkeypatch.setattr(
        migrate_module,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://db"),
    )
    monkeypatch.setattr(migrate_module, "Database", lambda _url: database)
    monkeypatch.setattr(
        migrate_module.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0010"),
    )

    def fake_subprocess_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], migration_returncode)

    monkeypatch.setattr(migrate_module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(
        migrate_module.structlog,
        "get_logger",
        lambda **kwargs: SimpleNamespace(
            info=lambda event, **_fields: logged.append((str(kwargs.get("process")), event))
        ),
    )

    assert asyncio.run(migrate_module._run()) == expected_code  # noqa: SLF001
    assert "pg_advisory_lock" in connection.statements[0]
    assert "pg_advisory_unlock" in connection.statements[-1]
    assert database.disposed
    assert bool(logged) is (expected_code == 0)
