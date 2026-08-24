"""Deploy one exact no-migration main SHA on the canonical dev server."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path("/opt/community-bot")
REPOSITORY = "https://github.com/AlexOxytocin/community_bot.git"
PUBLIC_READY_URL = "https://allo.godmodetools.com/readyz"
PREVIOUS_IMAGE = "community-bot-dev:previous"
SHA = re.compile(r"^[0-9a-f]{40}$")


def run(*command: str, env: dict[str, str] | None = None) -> str:
    """Run one checked local command."""
    return subprocess.run(
        command, check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def command() -> tuple[str, float]:
    """Parse the sole allowed forced-command payload."""
    parts = os.environ.get("SSH_ORIGINAL_COMMAND", "").split()
    if len(parts) != 3 or parts[0] != "deploy" or SHA.fullmatch(parts[1]) is None:
        raise SystemExit("Rejected deployment command.")
    try:
        started = float(parts[2])
    except ValueError as exc:
        raise SystemExit("Rejected deployment command.") from exc
    return parts[1], started


def compose(active: Path, image: str, release: str) -> tuple[list[str], dict[str, str]]:
    """Return the fixed Compose call and its image identity."""
    environment = os.environ | {
        "COMMUNITY_BOT_ENV_FILE": str(ROOT / "shared" / ".env"),
        "COMMUNITY_BOT_IMAGE": image,
        "COMMUNITY_BOT_RELEASE": release,
    }
    return ["docker", "compose", "-f", str(active / "compose.production.yaml")], environment


def prove(sha: str, deadline: float) -> None:
    """Poll container and public readiness until both expose the exact release."""
    while time.time() < deadline:
        state = run(
            "docker",
            "inspect",
            "community-mini-app-core-web-1",
            "--format",
            '{{.State.Health.Status}} {{index .Config.Labels "org.opencontainers.image.revision"}}',
        )
        if state == f"healthy {sha}":
            try:
                with urllib.request.urlopen(PUBLIC_READY_URL, timeout=5) as response:
                    if response.status == 200 and json.load(response)["release"] == sha:
                        return
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        time.sleep(2)
    raise RuntimeError("Deployment exceeded 120 seconds.")


def main() -> int:
    """Execute the serialized fast deploy or restore the prior running image."""
    sha, started = command()
    deadline = started + 120
    releases = ROOT / "shared" / "releases"
    active_state = json.loads((releases / "active.json").read_text(encoding="utf-8"))
    active = releases / active_state["current"]["manifest_sha256"]
    manifest = json.loads((active / "manifest.json").read_text(encoding="utf-8"))
    lock = releases / "dev-deploy.lock"
    with lock.open("w", encoding="utf-8") as stream:
        getattr(fcntl, "flock")(stream, getattr(fcntl, "LOCK_EX"))  # noqa: B009
        if run("git", "ls-remote", REPOSITORY, "refs/heads/main").split()[0] != sha:
            raise RuntimeError("Requested SHA is no longer main.")
        with tempfile.TemporaryDirectory(prefix="community-dev-") as temporary:
            source = Path(temporary) / "source"
            run("git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(source))
            run("git", "-C", str(source), "fetch", "--quiet", "--depth", "1", "origin", sha)
            run("git", "-C", str(source), "checkout", "--quiet", "--detach", "FETCH_HEAD")
            if run("git", "-C", str(source), "rev-parse", "HEAD") != sha:
                raise RuntimeError("Fetched SHA mismatch.")
            if subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "diff",
                    "--quiet",
                    manifest["commit_sha"],
                    sha,
                    "--",
                    "migrations",
                    "alembic.ini",
                    "compose.production.yaml",
                ],
                check=False,
            ).returncode:
                raise RuntimeError("Migration or compose change requires the slow path.")
            image = f"community-bot:{sha}"
            run(
                "docker",
                "build",
                "--platform",
                "linux/arm64",
                "--build-arg",
                f"RELEASE={sha}",
                "-t",
                image,
                str(source),
            )
        target_head = run("docker", "run", "--rm", image, "community-migration-head")
        probe, probe_environment = compose(active, image, sha)
        migration_query = (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc '
            '"SELECT version_num FROM alembic_version ORDER BY version_num"'
        )
        live_head = run(
            *probe,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            migration_query,
            env=probe_environment,
        )
        if target_head != manifest["migration_head"] or live_head != manifest["migration_head"]:
            raise RuntimeError("Migration head requires the slow path.")
        before = run("docker", "inspect", "community-mini-app-core-web-1", "--format", "{{.Image}}")
        before_release = run(
            "docker",
            "inspect",
            "community-mini-app-core-web-1",
            "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
        )
        if SHA.fullmatch(before_release) is None:
            raise RuntimeError("Running image has no exact release identity.")
        run("docker", "tag", before, PREVIOUS_IMAGE)
        deploy, environment = compose(active, image, sha)
        try:
            run(*deploy, "up", "-d", "--no-deps", "--force-recreate", "worker", env=environment)
            run(*deploy, "up", "-d", "--no-deps", "--force-recreate", "web", env=environment)
            prove(sha, deadline)
        except Exception:
            rollback_release = run(
                "docker",
                "image",
                "inspect",
                PREVIOUS_IMAGE,
                "--format",
                '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
            )
            if SHA.fullmatch(rollback_release) is None:
                raise RuntimeError("Previous image has no exact release identity.") from None
            rollback, old_environment = compose(active, PREVIOUS_IMAGE, rollback_release)
            run(
                *rollback,
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "worker",
                "web",
                env=old_environment,
            )
            prove(rollback_release, time.time() + 60)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
