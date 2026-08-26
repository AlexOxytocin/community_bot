from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def test_worker_check_mode_is_safe_and_successful(tmp_path: Path) -> None:
    command = "community-worker"
    executable = shutil.which(command)
    assert executable is not None

    result = subprocess.run(
        [executable, "--check"],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        text=True,
    )

    assert result.returncode == 0
    assert "bootstrap_check_passed" in result.stderr


def test_worker_runtime_mode_fails_without_required_secrets(tmp_path: Path) -> None:
    command = "community-worker"
    executable = shutil.which(command)
    assert executable is not None

    result = subprocess.run(
        [executable],
        capture_output=True,
        check=False,
        cwd=tmp_path,
        text=True,
    )

    assert result.returncode == 2
    assert "bot_token_missing" in result.stderr
