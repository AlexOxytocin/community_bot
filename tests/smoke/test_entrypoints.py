from __future__ import annotations

import shutil
import subprocess


def test_worker_check_mode_is_safe_and_successful() -> None:
    command = "community-worker"
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


def test_worker_runtime_mode_fails_without_required_secrets() -> None:
    command = "community-worker"
    executable = shutil.which(command)
    assert executable is not None

    result = subprocess.run(
        [executable],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert "bot_token_missing" in result.stderr
