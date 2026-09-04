"""Apply one reviewed no-migration Compose change on the canonical dev host."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path("/opt/community-bot")
REPOSITORY = "https://github.com/AlexOxytocin/community_bot.git"
PROJECT = "community-mini-app-core"
WEB = f"{PROJECT}-web-1"
WORKER = f"{PROJECT}-worker-1"
POSTGRES = f"{PROJECT}-postgres-1"
EGRESS = f"{PROJECT}_egress"
PREVIOUS_IMAGE = "community-bot-dev:previous"
SHA = re.compile(r"^[0-9a-f]{40}$")


class DeployError(RuntimeError):
    """Reject an unsafe or incomplete Compose deployment."""


def run(*command: str, env: dict[str, str] | None = None) -> str:
    """Run one checked command without a shell."""
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def inspect(container: str) -> dict[str, Any]:
    """Return one Docker object without Go-template quoting."""
    rows = json.loads(run("docker", "inspect", container))
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise DeployError(f"Could not inspect {container}.")
    return rows[0]


def dotenv(path: Path) -> dict[str, str]:
    """Read simple production dotenv values without expansion or logging."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("\"'")
    return values


def compose(
    config: Path, image: str, release: str, env_file: Path
) -> tuple[list[str], dict[str, str]]:
    """Build the exact Compose argv and environment."""
    environment = os.environ | {
        "COMMUNITY_BOT_ENV_FILE": str(env_file),
        "COMMUNITY_BOT_IMAGE": image,
        "COMMUNITY_BOT_RELEASE": release,
    }
    return [
        "docker",
        "compose",
        "--project-directory",
        str(config.parent),
        "--env-file",
        str(env_file),
        "-f",
        str(config),
    ], environment


def active_config(web: dict[str, Any]) -> Path:
    """Resolve the exact active Compose file inside the managed release set."""
    labels = web.get("Config", {}).get("Labels", {})
    raw = labels.get("com.docker.compose.project.config_files")
    if not isinstance(raw, str) or "," in raw:
        raise DeployError("Running web container has no single Compose config identity.")
    path = Path(raw).resolve(strict=True)
    releases = (ROOT / "shared" / "releases").resolve(strict=True)
    if not path.is_relative_to(releases) or path.name != "compose.production.yaml":
        raise DeployError("Running Compose config is outside the managed release set.")
    return path


def release_of(container: dict[str, Any]) -> str:
    """Read one immutable OCI release identity."""
    value = container.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise DeployError("Running container has no exact release identity.")
    return value


def live_head(values: dict[str, str]) -> str:
    """Read the live Alembic head without exposing database credentials."""
    database = values.get("POSTGRES_DB")
    user = values.get("POSTGRES_USER")
    if not database or not user:
        raise DeployError("Production database identity is incomplete.")
    return run(
        "docker",
        "exec",
        POSTGRES,
        "psql",
        "--username",
        user,
        "--dbname",
        database,
        "--tuples-only",
        "--no-align",
        "--command",
        "SELECT version_num FROM alembic_version ORDER BY version_num",
    )


def validate_compose(config: Path, image: str, release: str, env_file: Path) -> None:
    """Require the bounded service and network topology before mutation."""
    command, environment = compose(config, image, release, env_file)
    payload = json.loads(run(*command, "config", "--format", "json", env=environment))
    services = payload.get("services", {})
    if set(services) != {"postgres", "migrate", "worker", "web"}:
        raise DeployError("Compose services do not match the production package.")
    if set(services["web"].get("networks", {})) != {"internal", "egress"}:
        raise DeployError("Web must have only internal and egress networks.")
    if set(services["postgres"].get("networks", {})) != {"internal"}:
        raise DeployError("PostgreSQL must remain internal-only.")
    if services["web"].get("ports"):
        raise DeployError("Web must not publish a host port.")


def durable_replace(path: Path, content: bytes) -> None:
    """Atomically replace one exact regular file and fsync its directory."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def exclusive_backup(path: Path, content: bytes) -> Path:
    """Create the one rollback copy without overwriting an earlier backup."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def prove(release: str, deadline: float) -> None:
    """Require healthy exact runtime and real HTTPS egress from web."""
    while time.time() < deadline:
        web = inspect(WEB)
        worker = inspect(WORKER)
        if all(
            item.get("State", {}).get("Health", {}).get("Status") == "healthy"
            and release_of(item) == release
            for item in (web, worker)
        ):
            networks = set(web.get("NetworkSettings", {}).get("Networks", {}))
            if networks == {f"{PROJECT}_internal", EGRESS}:
                run(
                    "docker",
                    "exec",
                    WEB,
                    "python",
                    "-c",
                    "import urllib.request; "
                    "urllib.request.urlopen('https://api.telegram.org', timeout=5).read(1)",
                )
                payload = json.loads(
                    run(
                        "docker",
                        "exec",
                        WEB,
                        "python",
                        "-c",
                        "import urllib.request; print(urllib.request.urlopen("
                        "'http://127.0.0.1:8000/readyz', timeout=5).read().decode())",
                    )
                )
                if payload.get("healthy") is True and payload.get("release") == release:
                    return
        time.sleep(2)
    raise DeployError("Exact runtime did not become ready before the deadline.")


def prepare(target: str, source: Path) -> tuple[str, Path, Path, bytes, dict[str, str]]:
    """Perform the complete read-only preflight and return measured state."""
    if SHA.fullmatch(target) is None:
        raise DeployError("Target must be a full lowercase Git SHA.")
    remote = run("git", "ls-remote", REPOSITORY, "refs/heads/main").split()
    if len(remote) != 2 or remote[0] != target:
        raise DeployError("Target is no longer current main.")
    run("git", "clone", "--quiet", "--no-checkout", REPOSITORY, str(source))
    run("git", "-C", str(source), "fetch", "--quiet", "origin", target)
    run("git", "-C", str(source), "checkout", "--quiet", "--detach", target)
    if run("git", "-C", str(source), "rev-parse", "HEAD") != target:
        raise DeployError("Fetched source identity does not match target.")

    web = inspect(WEB)
    before = release_of(web)
    run("git", "-C", str(source), "fetch", "--quiet", "origin", before)
    migration_diff = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "diff",
            "--quiet",
            before,
            target,
            "--",
            "migrations",
            "alembic.ini",
        ],
        check=False,
    ).returncode
    if migration_diff != 0:
        raise DeployError("Compose deployment cannot include a migration change.")

    config = active_config(web)
    if config.stat().st_mode & 0o777 != 0o600:
        raise DeployError("Active Compose config must be root-private.")
    env_file = ROOT / "shared" / ".env"
    values = dotenv(env_file)
    target_config = source / "compose.production.yaml"
    validate_compose(target_config, f"community-bot:{target}", target, env_file)
    backup = config.with_name(f"{config.name}.pre-cb128-{target[:7]}")
    if backup.exists():
        raise DeployError("The exact Compose backup target already exists.")
    return before, config, backup, target_config.read_bytes(), values


def deploy(target: str, *, apply: bool) -> None:
    """Run dry preflight or one rollback-protected Compose deployment."""
    lock = ROOT / "shared" / "releases" / "dev-deploy.lock"
    with lock.open("w", encoding="utf-8") as stream:
        getattr(fcntl, "flock")(stream, getattr(fcntl, "LOCK_EX"))  # noqa: B009
        with tempfile.TemporaryDirectory(prefix="community-compose-") as temporary:
            source = Path(temporary) / "source"
            before, config, backup, target_config, values = prepare(target, source)
            evidence = {
                "before": before,
                "target": target,
                "migration_head": live_head(values),
                "config": str(config),
                "backup": str(backup),
                "services": ["postgres", "migrate", "worker", "web"],
            }
            if not apply:
                print(json.dumps(evidence, sort_keys=True))
                return

            image = f"community-bot:{target}"
            run(
                "docker",
                "build",
                "--platform",
                "linux/arm64",
                "--build-arg",
                f"RELEASE={target}",
                "-t",
                image,
                str(source),
            )
            if (
                run("docker", "run", "--rm", image, "community-migration-head")
                != evidence["migration_head"]
            ):
                raise DeployError("Target image and live migration heads differ.")
            image_release = (
                inspect(image)
                .get("Config", {})
                .get("Labels", {})
                .get("org.opencontainers.image.revision")
            )
            if image_release != target:
                raise DeployError("Built image has the wrong release identity.")

            old_content = config.read_bytes()
            old_image = inspect(WEB).get("Config", {}).get("Image")
            if old_image != f"community-bot:{before}":
                raise DeployError("Running image tag does not match its release identity.")
            run("docker", "tag", old_image, PREVIOUS_IMAGE)
            exclusive_backup(backup, old_content)
            durable_replace(config, target_config)
            command, environment = compose(config, image, target, ROOT / "shared" / ".env")
            try:
                run(
                    *command,
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "worker",
                    env=environment,
                )
                run(
                    *command,
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "web",
                    env=environment,
                )
                prove(target, time.time() + 90)
            except Exception:
                durable_replace(config, old_content)
                rollback, rollback_environment = compose(
                    config, PREVIOUS_IMAGE, before, ROOT / "shared" / ".env"
                )
                run(
                    *rollback,
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "worker",
                    "web",
                    env=rollback_environment,
                )
                run("docker", "network", "connect", EGRESS, WEB)
                prove(before, time.time() + 60)
                raise
            print(json.dumps({**evidence, "status": "ready"}, sort_keys=True))


def main() -> int:
    """Parse one exact target and default to a non-mutating preflight."""
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        deploy(arguments.target, apply=arguments.apply)
    except (DeployError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"compose deployment rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
