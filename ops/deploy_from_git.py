"""Deploy Community Bot by fetching a Git ref on the self-hosted server."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops._runtime import (
    OpsError,
    capture_text,
    default_root_dir,
    fail,
    run_checked,
    validate_environment_file,
    validate_image_reference,
)

PRODUCTION_PATHS = (
    "Dockerfile",
    ".dockerignore",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "alembic.ini",
    "compose.production.yaml",
    "ops",
    "src",
    "config",
    "migrations",
)
RELEASE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAIN_REFS = frozenset({"main", "refs/heads/main"})


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch a Git ref, build a local image, and deploy it through Compose."""
    parser = argparse.ArgumentParser(prog="deploy_from_git.py")
    parser.add_argument("repository")
    parser.add_argument("ref")
    parser.add_argument("bootstrap_telegram_id", nargs="?")
    parser.add_argument("--root-dir", type=Path, default=default_root_dir())
    parser.add_argument("--image-name", default="community-bot")
    parser.add_argument("--release")
    args = parser.parse_args(argv)

    try:
        deploy_from_git(
            repository=args.repository,
            ref=args.ref,
            root_dir=args.root_dir,
            image_name=args.image_name,
            release=args.release,
            bootstrap_telegram_id=args.bootstrap_telegram_id,
        )
    except OpsError as exc:
        fail(str(exc))
    return 0


def deploy_from_git(
    *,
    repository: str,
    ref: str,
    root_dir: Path,
    image_name: str,
    release: str | None,
    bootstrap_telegram_id: str | None,
) -> None:
    """Build and deploy a production package copied from one Git ref."""
    validate_environment_file(root_dir / "shared" / ".env")
    with tempfile.TemporaryDirectory(prefix="community-bot-git-") as temporary:
        source = Path(temporary) / "source"
        fetch_source(repository=repository, ref=ref, source=source)
        commit = capture_text(["git", "-C", str(source), "rev-parse", "HEAD"])
        release_name = release or default_release_name(commit)
        if RELEASE_RE.fullmatch(release_name) is None:
            raise OpsError(
                "Release name may contain only letters, digits, dot, underscore and dash."
            )
        staging = root_dir / f"current.{release_name}"
        backup = root_dir / f"current.before-{release_name}"
        failed = root_dir / f"current.failed-{release_name}"
        current = root_dir / "current"
        for path in (staging, backup, failed):
            if path.exists():
                raise OpsError(f"Release path already exists: {path}")
        if not current.is_dir():
            raise OpsError("Current deployment package is missing.")

        copy_production_paths(source, staging)
        ensure_no_forbidden_paths(staging)
        mark_python_scripts_executable(staging / "ops")
        image_id = build_image(staging=staging, image_name=image_name, release=release_name)
        validate_image_reference(image_id)
        print(f"deploy:git_commit={commit}")
        print(f"deploy:release={release_name}")
        print(f"deploy:image_id={image_id}")

        current.rename(backup)
        staging.rename(current)
        try:
            command = [sys.executable, str(current / "ops" / "deploy_self_hosted.py"), image_id]
            if bootstrap_telegram_id is not None:
                command.append(bootstrap_telegram_id)
            run_checked(command)
        except Exception:
            if current.exists() and backup.exists() and not failed.exists():
                current.rename(failed)
                backup.rename(current)
            raise


def fetch_source(*, repository: str, ref: str, source: Path) -> None:
    """Fetch the current main commit and reject every other deployment ref."""
    source.mkdir(parents=True)
    run_checked(["git", "-C", str(source), "init"])
    run_checked(["git", "-C", str(source), "remote", "add", "origin", repository])
    run_checked(["git", "-C", str(source), "fetch", "--depth", "1", "origin", "refs/heads/main"])
    main_commit = capture_text(["git", "-C", str(source), "rev-parse", "FETCH_HEAD"])
    if ref not in MAIN_REFS and ref != main_commit:
        raise OpsError("Deploy ref must match the current origin/main commit.")
    run_checked(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"])


def default_release_name(commit: str) -> str:
    """Build a release name from UTC time and Git commit."""
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"git-{stamp}-{commit[:12]}"


def copy_production_paths(source: Path, staging: Path) -> None:
    """Copy only runtime and deployment files from a Git checkout."""
    staging.mkdir(parents=True, mode=0o755)
    for relative in PRODUCTION_PATHS:
        source_path = source / relative
        target_path = staging / relative
        if not source_path.exists():
            raise OpsError(f"Required production path is missing in Git ref: {relative}")
        if source_path.is_file():
            if is_excluded(PurePosixPath(relative)):
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            continue
        for child in sorted(source_path.rglob("*")):
            if not child.is_file():
                continue
            child_relative = PurePosixPath(child.relative_to(source).as_posix())
            if is_excluded(child_relative):
                continue
            destination = staging / child_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)


def is_excluded(path: PurePosixPath) -> bool:
    """Return whether a checkout path is forbidden in a production package."""
    parts = path.parts
    return (
        not parts
        or parts[0]
        in {
            ".git",
            ".hypothesis",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "dist",
            "tasks",
            "tests",
        }
        or path.name == ".env"
        or path.name.endswith(".pyc")
        or "__pycache__" in parts
        or (len(parts) >= 2 and parts[0] == "config" and parts[1] == "testing")
    )


def ensure_no_forbidden_paths(staging: Path) -> None:
    """Fail closed if staging contains local-only or secret-bearing paths."""
    forbidden = [
        staging / ".env",
        staging / ".git",
        staging / "tests",
        staging / "config" / "testing",
    ]
    if any(path.exists() for path in forbidden):
        raise OpsError("Deployment package contains a forbidden path.")


def mark_python_scripts_executable(ops_dir: Path) -> None:
    """Make host-side Python operation scripts executable for manual use."""
    for script in ops_dir.glob("*.py"):
        script.chmod(0o755)


def build_image(*, staging: Path, image_name: str, release: str) -> str:
    """Build the local linux/arm64 image and return its immutable ID."""
    tag = f"{image_name}:{release}"
    run_checked(
        [
            "docker",
            "build",
            "--platform",
            "linux/arm64",
            "--build-arg",
            f"RELEASE={release}",
            "-t",
            tag,
            str(staging),
        ]
    )
    return capture_text(["docker", "image", "inspect", "--format", "{{.Id}}", tag])


if __name__ == "__main__":
    raise SystemExit(main())
