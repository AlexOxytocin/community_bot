"""Allowlisted schema releases with a frozen-runtime gate and database recovery.

Run from an exact clean Git checkout. Prepare builds but never stops production.
Apply uses the measured receipt, rechecks drift, and keeps writers in maintenance
until migration, restore rehearsal, runtime, and ledger checks have all passed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from ops._runtime import read_dotenv, validate_environment_file

ROOT = Path("/opt/community-bot")
PROJECT = "community-mini-app-core"
SERVICES = {"postgres", "migrate", "worker", "web"}
SHA = re.compile(r"[0-9a-f]{40}")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")
FROM_HEAD, TO_HEAD = "0033", "0034"
TRANSITIONS = {"0033-0034": ("0033", "0034"), "0034-0036": ("0034", "0036")}

# Only economic data: maintenance heartbeats must not invalidate this invariant.
FINGERPRINT_SQL = """SELECT json_build_object(
 'preferences_hash', (SELECT md5(COALESCE(string_agg(
   row_to_json(p)::text, ',' ORDER BY member_id),'')) FROM member_notification_preferences p),
 'members', (SELECT count(*) FROM members),
 'ledger', (SELECT count(*) FROM account_transactions),
 'member_hash', (SELECT md5(COALESCE(string_agg(
   id::text||':'||credit_balance_cached||':'||experience_total_cached,
   ',' ORDER BY id),'')) FROM members),
 'ledger_hash', (SELECT md5(COALESCE(string_agg(
   id::text||':'||member_id||':'||credit_delta||':'||experience_delta||':'||payload_hash,
   ',' ORDER BY id),'')) FROM account_transactions))::text"""

# Schema 0035 intentionally expands preferences and increments their revision.
# Compare the original consent fields, then separately assert the new defaults/splits.
ACTIVITY_FINGERPRINT_SQL = FINGERPRINT_SQL.replace(
    "FROM member_notification_preferences p",
    "FROM (SELECT member_id,tasks,tasks_since,nomad,nomad_since "
    "FROM member_notification_preferences) p",
)
ACTIVITY_INVARIANT_SQL = """SELECT (
 NOT EXISTS (SELECT 1 FROM member_notification_preferences WHERE
   online OR offline OR important OR online_since IS NOT NULL OR offline_since IS NOT NULL
   OR important_since IS NOT NULL OR task_updates IS DISTINCT FROM tasks
   OR task_reminders IS DISTINCT FROM tasks OR disputes IS DISTINCT FROM tasks
   OR task_updates_since IS DISTINCT FROM tasks_since
   OR task_reminders_since IS DISTINCT FROM tasks_since
   OR disputes_since IS DISTINCT FROM tasks_since)
 AND NOT EXISTS (SELECT 1 FROM activity_publications)
 AND NOT EXISTS (SELECT 1 FROM notifications WHERE notification_type='nomad.published'
   AND status IN ('pending','processing'))
 AND NOT EXISTS (SELECT 1 FROM outbox_events WHERE event_type='nomad.published'
   AND status IN ('pending','processing'))
)::text"""


class CutoverError(RuntimeError):
    """A bounded safe failure; command output never includes secrets."""


def run(*command: str, env: dict[str, str] | None = None, **kwargs: Any) -> str:
    """Capture private diagnostics instead of printing credential-bearing argv."""
    result = subprocess.run(command, env=env, check=False, capture_output=True, **kwargs)
    if result.returncode:
        raise CutoverError(f"{command[0]} failed (exit {result.returncode}).")
    return result.stdout.decode().strip()


def digest(path: Path) -> str:
    """Hash an exact file without logging its contents."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save(path: Path, receipt: dict[str, Any]) -> None:
    """Durably journal recovery state before each irreversible boundary."""
    temporary = path.with_suffix(".part")
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def inspect(name: str) -> dict[str, Any]:
    """Read Docker JSON without shell templates or environment disclosure."""
    return json.loads(run("docker", "inspect", name))[0]


class Host:
    """The measured production package; no active.json or guessed current path."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        """Bind validated database names to one measured release receipt."""
        self.receipt = receipt
        if (self.from_head, self.to_head) not in TRANSITIONS.values():
            raise CutoverError("Unsupported schema transition.")
        self.config = Path(receipt["config"])
        self.env_file = ROOT / "shared" / ".env"
        validate_environment_file(self.env_file)
        self.values = read_dotenv(self.env_file)
        self.database = self.values["POSTGRES_DB"]
        self.user = self.values["POSTGRES_USER"]
        for name in (self.database, self.user, receipt["restore_db"], receipt["failed_db"]):
            if not IDENTIFIER.fullmatch(name):
                raise CutoverError("Invalid database identifier.")
        if len({self.database, receipt["restore_db"], receipt["failed_db"]}) != 3:
            raise CutoverError("Recovery databases must be distinct.")
        if "drill_db" in receipt and (
            not IDENTIFIER.fullmatch(receipt["drill_db"])
            or receipt["drill_db"] in {self.database, receipt["restore_db"], receipt["failed_db"]}
        ):
            raise CutoverError("Migration drill database must be distinct.")
        if urlsplit(self.values["DATABASE_URL"]).path != f"/{self.database}":
            raise CutoverError("Runtime and PostgreSQL database identities differ.")
        if self.values.get("RELEASE_MAINTENANCE", "false").lower() not in {"false", "0"}:
            raise CutoverError("Base environment must not enable maintenance.")

    @property
    def from_head(self) -> str:
        """Keep older prepared receipts readable for recovery."""
        return self.receipt.get("from_head", FROM_HEAD)

    @property
    def to_head(self) -> str:
        """Read the exact allowlisted target schema."""
        return self.receipt.get("to_head", TO_HEAD)

    def compose(
        self,
        *args: str,
        old: bool = False,
        maintenance: bool = False,
        config: Path | None = None,
    ) -> str:
        """Run only the exact measured Compose package and explicit override."""
        prefix = [
            "docker",
            "compose",
            "--env-file",
            str(self.env_file),
            "-f",
            str(config or self.config),
        ]
        if maintenance:
            prefix += ["-f", self.receipt["override"]]
        release = self.receipt["before"] if old else self.receipt["target"]
        environment = os.environ | {
            "COMMUNITY_BOT_ENV_FILE": str(self.env_file),
            "COMMUNITY_BOT_IMAGE": self.receipt["old_image"] if old else self.receipt["image"],
            "COMMUNITY_BOT_RELEASE": release,
        }
        return run(*prefix, *args, env=environment)

    def sql(self, sql: str, database: str | None = None) -> str:
        """Run fixed/validated SQL through the measured PostgreSQL container."""
        return run(
            "docker",
            "exec",
            self.receipt["postgres"],
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            self.user,
            "-d",
            database or self.database,
            "-Atc",
            sql,
        )

    def head(self, database: str | None = None) -> str:
        """Read the actual database revision."""
        return self.sql("SELECT version_num FROM alembic_version", database)

    def fingerprint(self, database: str | None = None) -> dict[str, Any]:
        """Read hashes and aggregate counts, never private ledger rows."""
        sql = ACTIVITY_FINGERPRINT_SQL if self.to_head == "0036" else FINGERPRINT_SQL
        return json.loads(self.sql(sql, database))

    def stopped(self) -> None:
        """Reject any running app process or remaining database client."""
        for service in ("web", "worker"):
            if inspect(f"{PROJECT}-{service}-1")["State"]["Running"]:
                raise CutoverError("A writer is still running.")
        if (
            self.sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND backend_type='client backend'"
            )
            != "0"
        ):
            raise CutoverError("Unexpected database clients remain.")

    def stop(self) -> None:
        """Stop both writer surfaces before creating the backup."""
        self.compose("stop", "web", "worker", old=True)
        self.stopped()

    def migrate(self, *, database: str | None = None, downgrade: bool = False) -> None:
        """Run a non-TTY one-shot; credentials stay out of diagnostics."""
        args = ["run", "--rm", "--no-deps", "-T"]
        if database:
            parsed = urlsplit(self.values["DATABASE_URL"])
            args += ["--env", f"DATABASE_URL={urlunsplit(parsed._replace(path=f'/{database}'))}"]
        args += ["migrate"]
        if downgrade:
            args += ["python", "-m", "alembic", "downgrade", self.from_head]
        self.compose(*args)

    def backup_restore(self) -> None:
        """Fresh frozen backup, real restore, forward/backward migration rehearsal."""
        self.stopped()
        receipt = self.receipt
        receipt["fingerprint"] = self.fingerprint()
        backup = Path(receipt["backup"])
        with backup.open("xb") as output:
            backup.chmod(0o600)
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    receipt["postgres"],
                    "pg_dump",
                    "-U",
                    self.user,
                    "-d",
                    self.database,
                    "-Fc",
                    "--no-owner",
                    "--no-privileges",
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
            output.flush()
            os.fsync(output.fileno())
        if result.returncode or not backup.stat().st_size:
            raise CutoverError("Frozen backup failed.")
        receipt["backup_sha256"] = digest(backup)
        restore = receipt["restore_db"]
        run("docker", "exec", receipt["postgres"], "createdb", "-U", self.user, restore)
        with backup.open("rb") as source:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    receipt["postgres"],
                    "pg_restore",
                    "-U",
                    self.user,
                    "-d",
                    restore,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                ],
                stdin=source,
                capture_output=True,
                check=False,
            )
        if result.returncode:
            raise CutoverError("Isolated restore failed.")
        self.rehearse(restore)
        receipt["restore_verified"] = True

    def rehearse(self, restore: str) -> None:
        """Exercise migrations on a clone, never on the rollback database."""
        self.check_snapshot(restore, self.from_head)
        # Keep the restored backup pristine: migrations retire legacy queued events,
        # and a downgrade cannot recreate those events for a faithful rollback.
        drill = self.receipt["drill_db"]
        run(
            "docker",
            "exec",
            self.receipt["postgres"],
            "createdb",
            "-U",
            self.user,
            "--template",
            restore,
            drill,
        )
        self.migrate(database=drill)
        self.check_snapshot(drill, self.to_head)
        self.migrate(database=drill, downgrade=True)
        self.check_snapshot(drill, self.from_head)
        self.check_snapshot(restore, self.from_head)

    def check_snapshot(self, database: str | None, head: str) -> None:
        """Check exact schema and conserved economic data."""
        if self.head(database) != head or self.fingerprint(database) != self.receipt["fingerprint"]:
            raise CutoverError("Snapshot/schema invariant failed.")
        if head == "0036" and self.sql(ACTIVITY_INVARIANT_SQL, database) != "true":
            raise CutoverError("Activity subscriptions or retired queue invariant failed.")

    def start(self, *, old: bool = False, maintenance: bool = False) -> None:
        """Recreate exact services; maintenance writes only liveness heartbeats."""
        self.compose(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "worker",
            "web",
            old=old,
            maintenance=maintenance,
        )

    def verify(self, *, old: bool = False, maintenance: bool = False) -> None:
        """Require fresh worker heartbeat, schema, config, and exact web revision."""
        release = self.receipt["before"] if old else self.receipt["target"]
        probe = (
            "import urllib.request,urllib.error; "
            "\ntry: r=urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=4)"
            "\nexcept urllib.error.HTTPError as e: r=e"
            "\nprint(r.read().decode())"
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                payload = json.loads(
                    run("docker", "exec", f"{PROJECT}-web-1", "python", "-c", probe)
                )
                identities = all(
                    inspect(f"{PROJECT}-{service}-1")["Config"]["Labels"].get(
                        "org.opencontainers.image.revision"
                    )
                    == release
                    for service in ("web", "worker")
                )
                if (
                    identities
                    and payload.get("release") == release
                    and all(
                        payload.get(key) is True
                        for key in (
                            "database",
                            "migration",
                            "product_config",
                            "heartbeat",
                            "invitation_config",
                        )
                    )
                    and bool(payload.get("maintenance", False)) == maintenance
                    and payload.get("healthy") is (not maintenance)
                ):
                    return
            except (CutoverError, json.JSONDecodeError):
                pass
            time.sleep(2)
        raise CutoverError("Exact runtime readiness timed out.")

    def rollback(self) -> None:
        """Retain the failed database; promote the verified pre-cutover restore."""
        receipt = self.receipt
        self.stop()
        if self.head() != self.from_head:
            if not receipt.get("restore_verified"):
                raise CutoverError("No verified recovery database; manual recovery required.")
            if digest(Path(receipt["backup"])) != receipt["backup_sha256"]:
                raise CutoverError("Backup digest changed; refusing recovery.")
            self.check_snapshot(receipt["restore_db"], self.from_head)
            self.sql(
                f'BEGIN; ALTER DATABASE "{self.database}" RENAME TO "{receipt["failed_db"]}"; '
                f'ALTER DATABASE "{receipt["restore_db"]}" RENAME TO "{self.database}"; COMMIT;',
                "postgres",
            )
        self.start(old=True)
        self.verify(old=True)


def execute(host: Host, path: Path) -> None:
    """One frozen transaction; never restore old data after enabling writers."""
    receipt = host.receipt
    receipt["phase"] = "stopping"
    save(path, receipt)
    try:
        host.stop()
        receipt["phase"] = "backup"
        save(path, receipt)
        host.backup_restore()
        receipt["phase"] = "migrating"
        save(path, receipt)
        host.migrate()
        host.check_snapshot(None, host.to_head)
        host.start(maintenance=True)
        host.verify(maintenance=True)
        host.check_snapshot(None, host.to_head)
    except Exception:
        receipt["phase"] = "rolling_back"
        save(path, receipt)
        host.rollback()
        receipt["phase"] = "rolled_back"
        save(path, receipt)
        raise
    # After this durable boundary background work may resume. DB restore would
    # discard new business operations, so recovery can only move forward.
    receipt["phase"] = "writers_enabled"
    save(path, receipt)
    activate(host)
    receipt["phase"] = "ready"
    save(path, receipt)


def activate(host: Host) -> None:
    """Bounded same-image forward recovery if service recreation was interrupted."""
    try:
        host.start()
        host.verify()
    except CutoverError:
        host.start()
        host.verify()


def prepare(source: Path, target: str, transition: str = "0033-0034") -> tuple[Host, Path]:
    """Measure the current package and build the exact clean main checkout."""
    if not SHA.fullmatch(target) or run("git", "-C", str(source), "rev-parse", "HEAD") != target:
        raise CutoverError("Source must be an exact full-SHA checkout.")
    if run("git", "-C", str(source), "status", "--porcelain"):
        raise CutoverError("Release checkout must be clean.")
    if (
        run(
            "git",
            "ls-remote",
            "https://github.com/AlexOxytocin/community_bot.git",
            "refs/heads/main",
        ).split()[0]
        != target
    ):
        raise CutoverError("Target is not current main.")
    web = inspect(f"{PROJECT}-web-1")
    labels = web["Config"]["Labels"]
    config = Path(labels["com.docker.compose.project.config_files"]).resolve(strict=True)
    if config.name != "compose.production.yaml" or not config.is_relative_to(
        (ROOT / "shared" / "releases").resolve(strict=True)
    ):
        raise CutoverError("Unrecognized active Compose package.")
    if config.read_bytes() != (source / "compose.production.yaml").read_bytes():
        raise CutoverError("Compose changes require a separate cutover.")
    validate_environment_file(config)
    postgres = inspect(f"{PROJECT}-postgres-1")
    postgres_config = Path(
        postgres["Config"]["Labels"]["com.docker.compose.project.config_files"]
    ).resolve(strict=True)
    if not postgres_config.is_relative_to((ROOT / "shared").resolve(strict=True)):
        raise CutoverError("Unrecognized PostgreSQL Compose package.")
    validate_environment_file(postgres_config)
    before = labels["org.opencontainers.image.revision"]
    if not SHA.fullmatch(before):
        raise CutoverError("Missing source release identity.")
    operation = uuid4().hex
    directory = ROOT / "shared" / "releases" / f"wallet-{operation}"
    directory.mkdir(mode=0o700)
    backup_dir = Path("/var/backups/community-bot")
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    from_head, to_head = TRANSITIONS[transition]
    receipt = {
        "from_head": from_head,
        "to_head": to_head,
        "target": target,
        "before": before,
        "config": str(config),
        "config_sha256": digest(config),
        "postgres": f"{PROJECT}-postgres-1",
        "postgres_id": postgres["Id"],
        "postgres_image": postgres["Image"],
        "postgres_config": str(postgres_config),
        "postgres_config_sha256": digest(postgres_config),
        "old_image": web["Image"],
        "image": f"community-bot:{target}",
        "restore_db": f"wallet_restore_{operation}",
        "drill_db": f"schema_drill_{operation}",
        "failed_db": f"wallet_failed_{operation}",
        "backup": str(backup_dir / f"wallet-{operation}.dump"),
        "override": str(directory / "maintenance.json"),
        "phase": "preparing",
    }
    host = Host(receipt)
    validate_source(host)
    host.verify(old=True)
    print(
        json.dumps({**receipt, "live_head": host.head(), "services": sorted(SERVICES)}), flush=True
    )
    run("docker", "build", "--build-arg", f"RELEASE={target}", "-t", receipt["image"], str(source))
    receipt["image"] = inspect(receipt["image"])["Id"]
    if (
        inspect(receipt["image"])["Config"]["Labels"].get("org.opencontainers.image.revision")
        != target
        or run("docker", "run", "--rm", receipt["image"], "community-migration-head")
        != host.to_head
    ):
        raise CutoverError("Target image identity/head mismatch.")
    save(
        Path(receipt["override"]),
        {
            "services": {
                name: {"environment": {"RELEASE_MAINTENANCE": "true"}} for name in ("web", "worker")
            }
        },
    )
    if set(host.compose("config", "--services", maintenance=True).splitlines()) != SERVICES:
        raise CutoverError("Maintenance package service mismatch.")
    receipt["phase"] = "prepared"
    path = directory / "receipt.json"
    save(path, receipt)
    return host, path


def validate_source(host: Host) -> None:
    """Fail before stopping anything if measured source or package has drifted."""
    receipt = host.receipt
    if digest(host.config) != receipt["config_sha256"] or host.head() != host.from_head:
        raise CutoverError("Source schema/package drifted.")
    if set(host.compose("config", "--services", old=True).splitlines()) != SERVICES:
        raise CutoverError("Unexpected production services.")
    for service in ("web", "worker"):
        item = inspect(f"{PROJECT}-{service}-1")
        if (
            item["Config"]["Labels"].get("com.docker.compose.project.config_files")
            != receipt["config"]
        ):
            raise CutoverError("Services do not share the measured Compose package.")
        if item["Image"] != receipt["old_image"]:
            raise CutoverError("Source runtime drifted.")
    validate_postgres(host)


def validate_postgres(host: Host) -> None:
    """Allow an unrecreated DB container only when its exact service is unchanged."""
    receipt = host.receipt
    postgres = inspect(receipt["postgres"])
    config = Path(receipt["postgres_config"])
    if (
        postgres["Id"] != receipt["postgres_id"]
        or postgres["Image"] != receipt["postgres_image"]
        or postgres["Config"]["Labels"].get("com.docker.compose.project.config_files")
        != receipt["postgres_config"]
        or postgres["Config"]["Labels"].get("com.docker.compose.project") != PROJECT
        or digest(config) != receipt["postgres_config_sha256"]
    ):
        raise CutoverError("PostgreSQL identity/package drifted.")
    current = json.loads(host.compose("config", "--format", "json", old=True))
    previous = json.loads(host.compose("config", "--format", "json", old=True, config=config))
    if current["services"]["postgres"] != previous["services"]["postgres"]:
        raise CutoverError("PostgreSQL service differs between measured packages.")


def main() -> int:
    """Prepare, apply, or resume the forward-only activation phase explicitly."""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "apply", "recover"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--transition", choices=tuple(TRANSITIONS), default="0033-0034")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        raise CutoverError("Production cutover requires Linux root.")
    lock_path = ROOT / "shared" / "releases" / "dev-deploy.lock"
    with lock_path.open("a") as lock:
        fcntl = importlib.import_module("fcntl")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode == "prepare":
            if args.source is None or args.target is None:
                raise CutoverError("Prepare requires source and target.")
            _host, path = prepare(args.source, args.target, args.transition)
            print(json.dumps({"prepared_receipt": str(path)}))
        else:
            if args.receipt is None:
                raise CutoverError("An exact prepared receipt is required.")
            validate_environment_file(args.receipt)
            receipt = json.loads(args.receipt.read_text())
            host = Host(receipt)
            if args.mode == "apply" and receipt["phase"] == "prepared":
                validate_source(host)
                execute(host, args.receipt)
            elif args.mode == "recover" and receipt["phase"] == "writers_enabled":
                activate(host)
                receipt["phase"] = "ready"
                save(args.receipt, receipt)
            elif args.mode == "recover" and receipt["phase"] in {
                "stopping",
                "backup",
                "migrating",
                "rolling_back",
            }:
                host.rollback()
                receipt["phase"] = "rolled_back"
                save(args.receipt, receipt)
            else:
                raise CutoverError("Receipt phase does not permit this operation.")
            print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CutoverError, OSError, KeyError, ValueError) as error:
        print(f"Cutover stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from None
