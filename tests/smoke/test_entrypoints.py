from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.mark.parametrize("command", ["community-bot", "community-worker"])
def test_check_mode_is_safe_and_successful(command: str) -> None:
    executable = shutil.which(command)
    assert executable is not None

    result = subprocess.run(
        [executable, "--check"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "bootstrap_check_passed" in result.stderr


@pytest.mark.parametrize(
    ("command", "error_code"),
    [
        ("community-bot", "required_secret_missing"),
        ("community-worker", "bot_token_missing"),
    ],
)
def test_runtime_mode_fails_without_required_secrets(command: str, error_code: str) -> None:
    executable = shutil.which(command)
    assert executable is not None

    result = subprocess.run(
        [executable],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert error_code in result.stderr
