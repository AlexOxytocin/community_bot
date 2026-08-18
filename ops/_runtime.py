"""Shared host-side helpers for Community Bot operations scripts."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

IMAGE_REFERENCE_RE = re.compile(r"^ghcr\.io/.+@sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


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


def require_non_empty_file(path: Path, message: str) -> None:
    """Require an existing non-empty regular file."""
    if not path.is_file() or path.stat().st_size == 0:
        raise OpsError(message)


def validate_image_reference(image_reference: str) -> None:
    """Require the immutable GHCR reference published by the release contract."""
    if IMAGE_REFERENCE_RE.fullmatch(image_reference) is None:
        raise OpsError("Production deployment requires an immutable image digest.")


@contextmanager
def selected_release(root_dir: Path | None = None) -> Iterator[tuple[Path, Path, str, str]]:
    """Yield one ready tuple while retaining the shared Linux operations lock."""
    root = root_dir or default_root_dir()
    state_dir = root / "shared" / "releases"
    with _shared_lock(state_dir / "operations.lock"):
        active_file = state_dir / "active.json"
        validate_environment_file(active_file)
        state = _json(_read_bytes(active_file))
        current = state.get("current")
        previous = state.get("previous")
        previous_sha = previous.get("manifest_sha256") if isinstance(previous, dict) else None
        if (
            set(state) != {"status", "operation", "current", "previous"}
            or state["status"] != "ready"
            or state["operation"] is not None
            or not isinstance(current, dict)
            or set(current) != {"manifest_sha256"}
            or (
                previous is not None
                and (not isinstance(previous, dict) or set(previous) != {"manifest_sha256"})
            )
        ):
            raise OpsError("Release operations are blocked while the active state is pending.")
        if previous is not None and (
            not isinstance(previous_sha, str) or SHA256_RE.fullmatch(previous_sha) is None
        ):
            raise OpsError("Active release state has an invalid previous manifest identity.")
        manifest_sha256 = current["manifest_sha256"]
        if not isinstance(manifest_sha256, str) or SHA256_RE.fullmatch(manifest_sha256) is None:
            raise OpsError("Active release state has an invalid manifest identity.")
        project_dir = state_dir / manifest_sha256
        manifest_file = project_dir / "manifest.json"
        validate_environment_file(manifest_file)
        manifest_bytes = _read_bytes(manifest_file)
        manifest = _json(manifest_bytes)
        image, release = manifest.get("image"), manifest.get("commit_sha")
        if (
            hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256
            or manifest.get("contract_version") != "community-mini-app-release/v1"
            or manifest.get("repository") != "AlexOxytocin/community_bot"
            or not isinstance(image, str)
            or not isinstance(release, str)
            or SHA1_RE.fullmatch(release) is None
        ):
            raise OpsError("Selected release manifest has an invalid identity.")
        validate_image_reference(image)
        validate_environment_file(project_dir / "compose.production.yaml")
        env_file = root / "shared" / ".env"
        validate_environment_file(env_file)
        yield project_dir, env_file, image, release


@contextmanager
def _shared_lock(path: Path) -> Iterator[None]:
    """Lock the same file as activation for the entire caller operation."""
    validate_environment_file(path)
    with path.open("rb") as lock:
        if os.name != "posix":  # pragma: no cover - production hosts are Linux.
            raise OpsError("Operations lock requires Linux flock support.")
        fcntl = importlib.import_module("fcntl")
        flock = fcntl.flock
        flock(lock, fcntl.LOCK_SH)
        try:
            yield
        finally:
            flock(lock, fcntl.LOCK_UN)


def _json(raw: bytes) -> dict[str, object]:
    """Read one object and reject duplicate object keys."""
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OpsError("Release JSON is invalid.") from exc
    if not isinstance(value, dict):
        raise OpsError("Release JSON is invalid.")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise OpsError("Release file is missing or unsafe.") from exc


def compose_command(project_dir: Path, env_file: Path) -> list[str]:
    """Build the Docker Compose command prefix used by all host operations."""
    return [
        "docker",
        "compose",
        "--project-directory",
        str(project_dir),
        "--env-file",
        str(env_file),
        "-f",
        str(project_dir / "compose.production.yaml"),
    ]


def operations_environment(env_file: Path, image_reference: str, release: str) -> dict[str, str]:
    """Return process variables bound to one selected release tuple."""
    environment = os.environ.copy()
    environment["COMMUNITY_BOT_IMAGE"] = image_reference
    environment["COMMUNITY_BOT_RELEASE"] = release
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
