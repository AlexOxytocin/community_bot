"""Shared host-side helpers for Community Bot operations scripts."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

IMAGE_REFERENCE_RE = re.compile(r"^(ghcr\.io/.+@sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64})$")


class OpsError(RuntimeError):
    """Raised when an operations precondition fails before external execution."""


def fail(message: str, *, code: int = 1) -> None:
    """Print a stable error message and stop the current script."""
    print(message, file=sys.stderr)
    raise SystemExit(code)


def default_root_dir() -> Path:
    """Return the configured self-hosted root directory."""
    return Path(os.environ.get("COMMUNITY_BOT_ROOT", "/opt/community-bot"))


def validate_environment_file(path: Path) -> None:
    """Require a root-owned regular env file with mode 0600."""
    try:
        status = path.lstat()
    except FileNotFoundError as exc:
        raise OpsError("Production environment file is missing.") from exc
    mode = stat.S_IMODE(status.st_mode)
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise OpsError(
            "Production environment file must be a root-owned regular file with mode 0600."
        )
    if status.st_uid != 0 or mode != 0o600:
        raise OpsError(
            "Production environment file must be a root-owned regular file with mode 0600."
        )


def require_file(path: Path, message: str) -> None:
    """Require an existing regular file."""
    if not path.is_file():
        raise OpsError(message)


def require_non_empty_file(path: Path, message: str) -> None:
    """Require an existing non-empty regular file."""
    if not path.is_file() or path.stat().st_size == 0:
        raise OpsError(message)


def validate_image_reference(image_reference: str) -> None:
    """Require a GHCR digest or local immutable Docker image ID."""
    if IMAGE_REFERENCE_RE.fullmatch(image_reference) is None:
        raise OpsError("Production deployment requires an immutable image digest or image ID.")


def read_current_image(root_dir: Path) -> str:
    """Read and validate the current release image identity."""
    current_image_file = root_dir / "shared" / "releases" / "current-image"
    require_file(current_image_file, "Production environment file is missing.")
    image_reference = current_image_file.read_text(encoding="utf-8").strip()
    validate_image_reference(image_reference)
    return image_reference


def compose_command(root_dir: Path, env_file: Path) -> list[str]:
    """Build the Docker Compose command prefix used by all host operations."""
    return [
        "docker",
        "compose",
        "--project-directory",
        str(root_dir / "current"),
        "--env-file",
        str(env_file),
        "-f",
        str(root_dir / "current" / "compose.production.yaml"),
    ]


def operations_environment(env_file: Path, image_reference: str) -> dict[str, str]:
    """Return a process environment with Compose image variables injected."""
    environment = os.environ.copy()
    environment["COMMUNITY_BOT_IMAGE"] = image_reference
    environment["COMMUNITY_BOT_ENV_FILE"] = str(env_file)
    return environment


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from the production env file without expansion."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def require_env_values(values: dict[str, str], *names: str) -> dict[str, str]:
    """Return required env values or fail closed."""
    missing = [name for name in names if not values.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise OpsError(f"Production environment file is missing required keys: {joined}.")
    return {name: values[name] for name in names}


def run_checked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """Run an external command and propagate its exact failure."""
    return subprocess.run(command, check=True, **kwargs)


def capture_text(command: list[str], **kwargs: Any) -> str:
    """Run a command and return stripped stdout."""
    result = subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)
    return result.stdout.strip()


def wait_for_health(
    compose: list[str],
    environment: dict[str, str],
    *,
    service: str,
    process: str,
    attempts: int = 30,
    interval_seconds: int = 2,
) -> None:
    """Wait until one Compose service reports application readiness."""
    for _ in range(attempts):
        result = subprocess.run(
            [*compose, "exec", "-T", service, "community-health", "--process", process],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(interval_seconds)
    raise OpsError(f"Service did not become healthy: {service}")
