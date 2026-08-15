"""Tests for the isolated test-run operator CLI."""

# ruff: noqa: SLF001

from __future__ import annotations

import argparse
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from community_bot.application.test_runs import (
    TestRunBlockers as RunBlockers,
)
from community_bot.application.test_runs import (
    TestRunScope as RunScope,
)
from community_bot.application.test_runs import (
    TestRunSnapshot as RunSnapshot,
)
from community_bot.bootstrap import test_run


def _snapshot(status: str = "active") -> RunSnapshot:
    return RunSnapshot(
        scope=RunScope(uuid4(), "TEST-RELEASE-CLI01"),
        status=status,
        participant_count=2,
        blockers=RunBlockers(0, 0, 0),
    )


def test_main_prints_privacy_safe_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_run(_args: argparse.Namespace) -> RunSnapshot:
        return _snapshot()

    monkeypatch.setattr(test_run, "_run", fake_run)

    assert test_run.main(["status", "TEST-RELEASE-CLI01"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "blockers": {"assignments": 0, "drafts": 0, "tasks": 0},
        "marker": "TEST-RELEASE-CLI01",
        "participant_count": 2,
        "status": "active",
    }


@pytest.mark.asyncio
async def test_run_dispatches_every_lifecycle_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeDatabase:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql+asyncpg://test"
            self.unit_of_work = object()

        async def dispose(self) -> None:
            calls.append(("dispose", None))

    class FakeService:
        def __init__(self, _factory: object) -> None:
            pass

        async def begin(self, **kwargs: object) -> RunSnapshot:
            calls.append(("begin", kwargs))
            return _snapshot()

        async def status(self, marker: str) -> RunSnapshot:
            calls.append(("status", marker))
            return _snapshot()

        async def cleanup(self, marker: str) -> RunSnapshot:
            calls.append(("cleanup", marker))
            return _snapshot()

        async def finish(self, **kwargs: object) -> RunSnapshot:
            calls.append(("finish", kwargs))
            return _snapshot("failed")

    monkeypatch.setattr(test_run, "Database", FakeDatabase)
    monkeypatch.setattr(test_run, "TestRunService", FakeService)
    monkeypatch.setattr(
        test_run,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://test"),
    )
    monkeypatch.setattr(
        test_run.sys,
        "stdin",
        io.StringIO('{"participant_telegram_user_ids": [1, 2]}'),
    )

    await test_run._run(argparse.Namespace(command="begin", marker="TEST-RELEASE-CLI01"))
    await test_run._run(argparse.Namespace(command="status", marker="TEST-RELEASE-CLI01"))
    await test_run._run(argparse.Namespace(command="cleanup", marker="TEST-RELEASE-CLI01"))
    await test_run._run(
        argparse.Namespace(command="finish", marker="TEST-RELEASE-CLI01", failed=True)
    )

    assert [name for name, _value in calls] == [
        "begin",
        "dispose",
        "status",
        "dispose",
        "cleanup",
        "dispose",
        "finish",
        "dispose",
    ]
