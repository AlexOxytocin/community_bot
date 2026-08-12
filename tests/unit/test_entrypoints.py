from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from community_bot.bootstrap.bot import main as bot_main
from community_bot.bootstrap.runner import run_process
from community_bot.bootstrap.settings import get_settings
from community_bot.worker.entrypoint import main as worker_main

EntryPoint = Callable[[Sequence[str] | None], int]


@pytest.mark.parametrize("entrypoint", [bot_main, worker_main])
def test_entrypoint_check_mode_returns_success(
    entrypoint: EntryPoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_settings.cache_clear()

    assert entrypoint(["--check"]) == 0
    assert "bootstrap_check_passed" in capsys.readouterr().err


@pytest.mark.parametrize("entrypoint", [bot_main, worker_main])
def test_entrypoint_runtime_mode_rejects_missing_secrets(
    entrypoint: EntryPoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_settings.cache_clear()

    assert entrypoint([]) == 2
    assert "configuration_invalid" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected_code", "expected_log"),
    [
        (["--check"], 0, "bootstrap_check_passed"),
        ([], 2, "runtime_not_implemented"),
    ],
)
def test_shared_runner_is_safe_in_check_and_runtime_modes(
    argv: list[str],
    expected_code: int,
    expected_log: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_settings.cache_clear()

    assert run_process("community-legacy", argv) == expected_code
    assert expected_log in capsys.readouterr().err
