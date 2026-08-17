from __future__ import annotations

import io
from types import SimpleNamespace
from uuid import uuid4

import pytest

from community_bot.application.initial_admin import (
    InitialAdministratorCommand,
    InitialAdministratorConflictError,
    InitialAdministratorProfileRepairResult,
    InitialAdministratorReason,
    InitialAdministratorResult,
)
from community_bot.bootstrap import initial_admin
from community_bot.bootstrap.initial_admin import main


@pytest.mark.parametrize("telegram_user_id", [0, -1, 9_223_372_036_854_775_808])
def test_bootstrap_command_rejects_invalid_postgresql_identity(telegram_user_id: int) -> None:
    with pytest.raises(ValueError, match="positive PostgreSQL BIGINT"):
        InitialAdministratorCommand(
            telegram_user_id=telegram_user_id,
            reason=InitialAdministratorReason.INITIAL_INSTALL,
        )


def test_bootstrap_cli_help_is_available() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0


def test_bootstrap_cli_rejects_reason_outside_allowlist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_input = "BOT_TOKEN=private-value"
    with pytest.raises(SystemExit) as error:
        main(["--telegram-user-id", "100", "--reason", private_input])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert private_input not in captured.err
    assert "invalid arguments" in captured.err


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("created", 0), ("replay", 0), ("rejected", 2), ("failed", 1)],
)
def test_bootstrap_cli_maps_safe_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected: int,
) -> None:
    async def bootstrap(_url: str, _command: InitialAdministratorCommand) -> object:
        if outcome == "rejected":
            raise InitialAdministratorConflictError
        if outcome == "failed":
            raise RuntimeError
        return InitialAdministratorResult(uuid4(), created=outcome == "created")

    monkeypatch.setattr(initial_admin, "get_settings", _settings)
    monkeypatch.setattr(initial_admin, "configure_logging", lambda _level: None)
    monkeypatch.setattr(initial_admin, "configure_sentry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(initial_admin, "_bootstrap", bootstrap)

    assert main(["--telegram-user-id", "100", "--reason", "initial_install"]) == expected


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("changed", 0), ("replay", 0), ("rejected", 2), ("failed", 1)],
)
def test_repair_cli_maps_safe_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected: int,
) -> None:
    async def repair(_url: str, _command: object) -> object:
        if outcome == "rejected":
            raise InitialAdministratorConflictError
        if outcome == "failed":
            raise RuntimeError
        return InitialAdministratorProfileRepairResult(uuid4(), changed=outcome == "changed")

    monkeypatch.setattr(initial_admin, "get_settings", _settings)
    monkeypatch.setattr(initial_admin, "configure_logging", lambda _level: None)
    monkeypatch.setattr(initial_admin, "configure_sentry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(initial_admin, "_repair", repair)

    assert initial_admin.repair_main([], io.StringIO("100\nAdministrator\n")) == expected


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql://db",
        log_level="INFO",
        sentry_dsn=None,
        environment="test",
        release="test",
    )


@pytest.mark.asyncio
async def test_bootstrap_helpers_dispose_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Database:
        initial_administrator_unit_of_work = object()

        def __init__(self, _url: str) -> None:
            pass

        async def dispose(self) -> None:
            events.append("disposed")

    class Service:
        def __init__(self, _factory: object) -> None:
            pass

        async def bootstrap(self, _command: object) -> InitialAdministratorResult:
            events.append("bootstrap")
            return InitialAdministratorResult(uuid4(), created=True)

        async def repair_profile(self, _command: object) -> InitialAdministratorProfileRepairResult:
            events.append("repair")
            return InitialAdministratorProfileRepairResult(uuid4(), changed=True)

    monkeypatch.setattr(initial_admin, "Database", Database)
    monkeypatch.setattr(initial_admin, "InitialAdministratorService", Service)
    command = InitialAdministratorCommand(100, InitialAdministratorReason.INITIAL_INSTALL)

    await initial_admin._bootstrap("postgresql://db", command)  # noqa: SLF001
    await initial_admin._repair(  # noqa: SLF001
        "postgresql://db",
        initial_admin.InitialAdministratorProfileRepairCommand(100, "Administrator"),
    )

    assert events == ["bootstrap", "disposed", "repair", "disposed"]
