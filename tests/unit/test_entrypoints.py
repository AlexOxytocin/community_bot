from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from community_bot.application.notifications import WorkerTickResult
from community_bot.bootstrap.settings import get_settings
from community_bot.domain.notifications import DeliveryWindow
from community_bot.worker import entrypoint
from community_bot.worker.entrypoint import main as worker_main


def test_worker_check_mode_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    get_settings.cache_clear()

    assert worker_main(["--check"]) == 0
    assert "bootstrap_check_passed" in capsys.readouterr().err


def test_worker_runtime_mode_rejects_missing_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_settings.cache_clear()

    assert worker_main([]) == 2
    assert "configuration_invalid" in capsys.readouterr().err


def test_worker_rejects_invalid_delivery_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _worker_settings()
    settings.notification_window_end_local = settings.notification_window_start_local
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)

    assert worker_main(["--check"]) == 2


def test_worker_handles_operator_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def interrupted(**_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(entrypoint, "get_settings", _worker_settings)
    monkeypatch.setattr(entrypoint, "_run", interrupted)

    assert worker_main([]) == 0


@pytest.mark.asyncio
async def test_worker_once_composes_ticks_heartbeats_and_closes(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    settings = _worker_settings()

    class Database:
        session_factory = object()
        unit_of_work = object()

        def __init__(self, _url: str) -> None:
            pass

        async def dispose(self) -> None:
            events.append("database_closed")

    class Queue:
        def __init__(self, _factory: object) -> None:
            pass

        async def heartbeat(self, **kwargs: object) -> None:
            assert kwargs["migration_revision"] == "packaged-head"
            events.append("heartbeat")

    class Bot:
        def __init__(self, *, token: str) -> None:
            assert token.startswith("123456:")
            self.session = SimpleNamespace(close=self.close)

        async def close(self) -> None:
            events.append("bot_closed")

    class NotificationWorker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def tick(self, **_kwargs: object) -> WorkerTickResult:
            events.append("notifications")
            return WorkerTickResult(0, 0, 0, 0, 0, 0)

    class DeadlineWorker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def tick(self, **_kwargs: object) -> int:
            events.append("deadlines")
            return 0

    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)
    monkeypatch.setattr(entrypoint, "Database", Database)
    monkeypatch.setattr(entrypoint, "PostgresNotificationQueue", Queue)
    monkeypatch.setattr(entrypoint, "Bot", Bot)
    monkeypatch.setattr(entrypoint, "NotificationWorker", NotificationWorker)
    monkeypatch.setattr(entrypoint, "AssignmentDeadlineWorker", DeadlineWorker)
    monkeypatch.setattr(entrypoint, "single_migration_head", lambda: "packaged-head")

    await entrypoint._run(once=True, window=DeliveryWindow())  # noqa: SLF001

    assert events == [
        "deadlines",
        "notifications",
        "heartbeat",
        "bot_closed",
        "database_closed",
    ]


@pytest.mark.asyncio
async def test_worker_composition_rechecks_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _worker_settings()
    settings.bot_token = None
    monkeypatch.setattr(entrypoint, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="validated before worker composition"):
        await entrypoint._run(once=True, window=DeliveryWindow())  # noqa: SLF001


def _worker_settings() -> SimpleNamespace:
    token = SimpleNamespace(get_secret_value=lambda: f"{123456}:{'T' * 35}")
    return SimpleNamespace(
        database_url="postgresql://db",
        log_level="INFO",
        sentry_dsn=None,
        environment="test",
        release="test",
        bot_token=token,
        notification_window_start_local=datetime.time(9),
        notification_window_end_local=datetime.time(21),
        worker_batch_size=10,
        worker_lease_seconds=30,
        worker_poll_interval_seconds=1,
    )
