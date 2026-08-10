from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from community_bot.bootstrap.bot import main as bot_main
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
def test_entrypoint_runtime_mode_returns_safe_failure(
    entrypoint: EntryPoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_settings.cache_clear()

    assert entrypoint([]) == 2
    assert "runtime_not_implemented" in capsys.readouterr().err
