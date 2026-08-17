"""Create a root-only PostgreSQL logical backup for the Mini App backend."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops._runtime import (
    OpsError,
    compose_command,
    default_root_dir,
    fail,
    operations_environment,
    read_current_image,
    read_dotenv,
    require_env_values,
    run_checked,
    validate_environment_file,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one backup and print the created dump path."""
    parser = argparse.ArgumentParser(prog="backup_postgres.py")
    parser.parse_args(argv)
    try:
        backup_path = create_backup()
    except OpsError as exc:
        fail(str(exc))
    print(backup_path)
    return 0


def create_backup() -> Path:
    """Create one custom-format dump and prune local dumps older than seven days."""
    root_dir = default_root_dir()
    env_file = root_dir / "shared" / ".env"
    backup_dir = Path(os.environ.get("COMMUNITY_BOT_BACKUP_DIR", "/var/backups/community-bot"))

    validate_environment_file(env_file)
    image_reference = read_current_image(root_dir)
    env_values = require_env_values(read_dotenv(env_file), "POSTGRES_DB", "POSTGRES_USER")
    environment = operations_environment(env_file, image_reference)
    compose = compose_command(root_dir, env_file)

    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    temporary = backup_dir / f".{env_values['POSTGRES_DB']}-{timestamp}.dump.part"
    target = backup_dir / f"{env_values['POSTGRES_DB']}-{timestamp}.dump"

    previous_umask = os.umask(0o077)
    try:
        with temporary.open("wb") as output:
            run_checked(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "--username",
                    env_values["POSTGRES_USER"],
                    "--dbname",
                    env_values["POSTGRES_DB"],
                    "--format",
                    "custom",
                    "--no-owner",
                    "--no-privileges",
                ],
                env=environment,
                stdout=output,
            )
        if temporary.stat().st_size == 0:
            raise OpsError("PostgreSQL backup is empty.")
        temporary.replace(target)
    finally:
        os.umask(previous_umask)
        if temporary.exists():
            temporary.unlink()

    prune_old_backups(backup_dir, now=dt.datetime.now(dt.UTC), retention_days=7)
    return target


def prune_old_backups(backup_dir: Path, *, now: dt.datetime, retention_days: int) -> None:
    """Remove old dump files from the configured backup directory."""
    cutoff = now.timestamp() - retention_days * 24 * 60 * 60
    for dump_file in backup_dir.glob("*.dump"):
        if dump_file.is_file() and dump_file.stat().st_mtime < cutoff:
            dump_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
