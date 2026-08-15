from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest
from aiogram.types import ReplyKeyboardMarkup

from community_bot.bootstrap.bot import main as bot_main
from community_bot.bootstrap.runner import run_process
from community_bot.bootstrap.settings import get_settings
from community_bot.worker.entrypoint import _notification_reply_markup
from community_bot.worker.entrypoint import main as worker_main

EntryPoint = Callable[[Sequence[str] | None], int]


def test_worker_composes_registration_approval_with_the_main_menu() -> None:
    markup = _notification_reply_markup("registration.approved")

    assert isinstance(markup, ReplyKeyboardMarkup)
    assert len(markup.keyboard) == 6
    assert sum(len(row) for row in markup.keyboard) == 11
    assert _notification_reply_markup("task.published") is None


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
