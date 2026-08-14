"""Deploy one immutable Community Bot image on the self-hosted pilot server."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops._runtime import (
    OpsError,
    compose_command,
    default_root_dir,
    operations_environment,
    require_file,
    run_checked,
    validate_environment_file,
    validate_image_reference,
    wait_for_health,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the production deployment sequence."""
    parser = argparse.ArgumentParser(
        prog="deploy_self_hosted.py",
        description="Deploy a GHCR digest or local immutable Docker image ID.",
    )
    parser.add_argument("image_reference")
    parser.add_argument("bootstrap_telegram_id", nargs="?")
    args = parser.parse_args(argv)

    try:
        deploy(args.image_reference, args.bootstrap_telegram_id)
    except OpsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def deploy(image_reference: str, bootstrap_telegram_id: str | None) -> None:
    """Apply migrations, bootstrap config, and restart worker then bot."""
    root_dir = default_root_dir()
    compose_file = root_dir / "current" / "compose.production.yaml"
    env_file = root_dir / "shared" / ".env"
    state_dir = root_dir / "shared" / "releases"

    require_file(compose_file, "Deployment files are missing.")
    validate_environment_file(env_file)
    validate_image_reference(image_reference)

    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    current_file = state_dir / "current-image"
    previous_file = state_dir / "previous-image"
    if current_file.is_file():
        shutil.copyfile(current_file, previous_file)
        previous_file.chmod(0o600)

    environment = operations_environment(env_file, image_reference)
    compose = compose_command(root_dir, env_file)

    if image_reference.startswith("ghcr.io/"):
        run_checked(["docker", "pull", image_reference], env=environment)
    else:
        result = subprocess.run(
            ["docker", "image", "inspect", image_reference],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise OpsError("The requested immutable image is not loaded.")

    run_checked([*compose, "up", "-d", "postgres"], env=environment)
    run_checked([*compose, "run", "--rm", "migrate"], env=environment)
    if bootstrap_telegram_id is not None:
        run_checked(
            [
                *compose,
                "run",
                "--rm",
                "migrate",
                "community-bootstrap-admin",
                "--telegram-user-id",
                bootstrap_telegram_id,
                "--reason",
                os.environ.get("COMMUNITY_BOT_BOOTSTRAP_REASON", "initial_install"),
            ],
            env=environment,
        )
    run_checked(
        [*compose, "run", "--rm", "migrate", "community-bootstrap-product-config"],
        env=environment,
    )
    run_checked([*compose, "up", "-d", "--no-deps", "worker"], env=environment)
    wait_for_health(compose, environment, service="worker", process="community-worker")
    run_checked([*compose, "up", "-d", "--no-deps", "bot"], env=environment)
    wait_for_health(compose, environment, service="bot", process="community-bot")
    current_file.write_text(f"{image_reference}\n", encoding="utf-8")
    current_file.chmod(0o600)
    run_checked([*compose, "ps"], env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
