"""Deploy one exact no-migration main SHA on the canonical dev server."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("/opt/community-bot")
REPOSITORY = "https://github.com/AlexOxytocin/community_bot.git"
PREVIOUS_IMAGE = "community-bot-dev:previous"
SHA = re.compile(r"^[0-9a-f]{40}$")
RESTORE_DATABASE = "community_bot_restore_drill"


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
    """Poll private container health until it exposes the exact release."""
    while time.time() < deadline:
        state = run(
            "docker",
            "inspect",
            "community-mini-app-core-web-1",
            "--format",
            '{{.State.Health.Status}} {{index .Config.Labels "org.opencontainers.image.revision"}}',
        )
        if state == f"healthy {sha}":
            return
        time.sleep(2)
    raise RuntimeError("Deployment exceeded its private readiness deadline.")


def database_head(probe: list[str], environment: dict[str, str]) -> str:
    """Read the exact live Alembic head without exposing database credentials."""
    values = environment_values(ROOT / "shared" / ".env")
    return database_head_for(
        probe,
        environment,
        values["POSTGRES_USER"],
        values["POSTGRES_DB"],
    )


def database_head_for(
    probe: list[str], environment: dict[str, str], postgres_user: str, database: str
) -> str:
    """Read one exact database head through the existing PostgreSQL container."""
    return run(
        *probe,
        "exec",
        "-T",
        "postgres",
        "psql",
        "--username",
        postgres_user,
        "--dbname",
        database,
        "--tuples-only",
        "--no-align",
        "--command",
        "SELECT version_num FROM alembic_version ORDER BY version_num",
        env=environment,
    )


def environment_values(path: Path) -> dict[str, str]:
    """Read required simple dotenv values without expansion or logging."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        values[key.strip()] = value.strip().strip('"\'')
    missing = [name for name in ("POSTGRES_USER", "POSTGRES_DB") if not values.get(name)]
    if missing:
        raise RuntimeError("Production database identity is incomplete.")
    return values


def backup_restore_drill(
    probe: list[str], environment: dict[str, str], expected_head: str
) -> tuple[Path, str]:
    """Back up the live database and prove an isolated exact-head restore."""
    values = environment_values(ROOT / "shared" / ".env")
    postgres_user = values["POSTGRES_USER"]
    database = values["POSTGRES_DB"]
    backup_dir = Path("/var/backups/community-bot")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{database}-{timestamp}.dump"
    temporary = backup_dir / f".{database}-{timestamp}.dump.part"
    previous_umask = os.umask(0o077)
    try:
        with temporary.open("wb") as output:
            subprocess.run(
                [
                    *probe,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "--username",
                    postgres_user,
                    "--dbname",
                    database,
                    "--format",
                    "custom",
                    "--no-owner",
                    "--no-privileges",
                ],
                check=True,
                env=environment,
                stdout=output,
            )
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size == 0:
            raise RuntimeError("Production backup is empty.")
        temporary.replace(target)
    finally:
        os.umask(previous_umask)
        temporary.unlink(missing_ok=True)

    run(
        *probe,
        "exec",
        "-T",
        "postgres",
        "dropdb",
        "--username",
        postgres_user,
        "--if-exists",
        RESTORE_DATABASE,
        env=environment,
    )
    try:
        run(
            *probe,
            "exec",
            "-T",
            "postgres",
            "createdb",
            "--username",
            postgres_user,
            RESTORE_DATABASE,
            env=environment,
        )
        with target.open("rb") as backup:
            subprocess.run(
                [
                    *probe,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--username",
                    postgres_user,
                    "--dbname",
                    RESTORE_DATABASE,
                    "--no-owner",
                    "--no-privileges",
                ],
                check=True,
                env=environment,
                stdin=backup,
            )
        if database_head_for(
            probe, environment, postgres_user, RESTORE_DATABASE
        ) != expected_head:
            raise RuntimeError("Restored database has the wrong migration head.")
    finally:
        run(
            *probe,
            "exec",
            "-T",
            "postgres",
            "dropdb",
            "--username",
            postgres_user,
            "--if-exists",
            RESTORE_DATABASE,
            env=environment,
        )
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def require_database_head(
    probe: list[str], environment: dict[str, str], expected_head: str
) -> None:
    """Require one exact post-migration head."""
    if database_head(probe, environment) != expected_head:
        raise RuntimeError("Migration did not reach the exact target head.")


def main() -> int:  # noqa: PLR0915 - one serialized release transaction.
    """Execute the serialized fast deploy or restore the prior running image."""
    sha, started = command()
    deadline = started + 600
    releases = ROOT / "shared" / "releases"
    active_state = json.loads((releases / "active.json").read_text(encoding="utf-8"))
    active = releases / active_state["current"]["manifest_sha256"]
    lock = releases / "dev-deploy.lock"
    with lock.open("w", encoding="utf-8") as stream:
        getattr(fcntl, "flock")(stream, getattr(fcntl, "LOCK_EX"))  # noqa: B009
        if run("git", "ls-remote", REPOSITORY, "refs/heads/main").split()[0] != sha:
            raise RuntimeError("Requested SHA is no longer main.")
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
        with tempfile.TemporaryDirectory(prefix="community-dev-") as temporary:
            source = Path(temporary) / "source"
            run("git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(source))
            run("git", "-C", str(source), "fetch", "--quiet", "--depth", "1", "origin", sha)
            run("git", "-C", str(source), "checkout", "--quiet", "--detach", "FETCH_HEAD")
            if run("git", "-C", str(source), "rev-parse", "HEAD") != sha:
                raise RuntimeError("Fetched SHA mismatch.")
            compose_changed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "diff",
                    "--quiet",
                    before_release,
                    sha,
                    "--",
                    "compose.production.yaml",
                ],
                check=False,
            ).returncode != 0
            migration_changed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "diff",
                    "--quiet",
                    before_release,
                    sha,
                    "--",
                    "migrations",
                    "alembic.ini",
                ],
                check=False,
            ).returncode != 0
            if compose_changed:
                raise RuntimeError("Compose changes require a separately reviewed host package.")
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
        live_head = database_head(probe, probe_environment)
        if target_head != live_head and not migration_changed:
            raise RuntimeError("Unexpected database head mismatch.")
        run("docker", "tag", before, PREVIOUS_IMAGE)
        deploy, environment = compose(active, image, sha)
        try:
            if target_head != live_head:
                backup_restore_drill(probe, probe_environment, live_head)
                run(*deploy, "stop", "web", "worker", env=environment)
                run(
                    *deploy,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "migrate",
                    env=environment,
                )
                require_database_head(probe, probe_environment, target_head)
            run(*deploy, "up", "-d", "--no-deps", "--force-recreate", "worker", env=environment)
            run(*deploy, "up", "-d", "--no-deps", "--force-recreate", "web", env=environment)
            prove(sha, deadline)
        except Exception:
            if database_head(probe, probe_environment) != live_head:
                raise RuntimeError(
                    "Forward migration completed; automatic image rollback is unsafe."
                ) from None
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
