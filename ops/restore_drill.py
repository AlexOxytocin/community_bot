"""Restore a PostgreSQL dump into an isolated drill database and verify it."""

from __future__ import annotations

import argparse
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
    fail,
    operations_environment,
    read_current_image,
    read_dotenv,
    require_env_values,
    require_non_empty_file,
    run_checked,
    validate_environment_file,
)

DRILL_DATABASE = "community_bot_restore_drill"
RESTORE_CHECK_SQL = """
DO $$
BEGIN
  IF (SELECT version_num FROM alembic_version) <> '0018' THEN
    RAISE EXCEPTION 'Unexpected Alembic revision in restored database.';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM members AS member
    LEFT JOIN (
      SELECT
        member_id,
        COALESCE(SUM(credit_delta), 0) AS credit_total,
        COALESCE(SUM(experience_delta), 0) AS experience_total
      FROM account_transactions
      GROUP BY member_id
    ) AS ledger ON ledger.member_id = member.id
    WHERE member.credit_balance_cached <> COALESCE(ledger.credit_total, 0)
       OR member.experience_total_cached <> COALESCE(ledger.experience_total, 0)
  ) THEN
    RAISE EXCEPTION 'Ledger reconciliation failed in restored database.';
  END IF;
END
$$;
SELECT version_num AS alembic_revision FROM alembic_version;
SELECT count(*) AS members_count FROM members;
SELECT count(*) AS account_transactions_count FROM account_transactions;
SELECT 0 AS ledger_mismatch_count;
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Run one restore drill for a provided backup file."""
    parser = argparse.ArgumentParser(prog="restore_drill.py")
    parser.add_argument("backup_file", type=Path)
    args = parser.parse_args(argv)
    try:
        return restore_drill(args.backup_file)
    except OpsError as exc:
        fail(str(exc))
    return 1


def restore_drill(backup_file: Path) -> int:
    """Restore a dump, validate revision and ledger caches, then remove the drill DB."""
    root_dir = default_root_dir()
    env_file = root_dir / "shared" / ".env"

    require_non_empty_file(backup_file, "Backup or environment file is missing.")
    validate_environment_file(env_file)
    image_reference = read_current_image(root_dir)
    env_values = require_env_values(read_dotenv(env_file), "POSTGRES_USER")
    environment = operations_environment(env_file, image_reference)
    compose = compose_command(root_dir, env_file)

    cleanup_drill_database(compose, environment, env_values["POSTGRES_USER"], check=True)
    restore_return_code = 0
    cleanup_return_code = 0
    try:
        run_checked(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "createdb",
                "--username",
                env_values["POSTGRES_USER"],
                DRILL_DATABASE,
            ],
            env=environment,
        )
        with backup_file.open("rb") as backup:
            run_checked(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--username",
                    env_values["POSTGRES_USER"],
                    "--dbname",
                    DRILL_DATABASE,
                    "--no-owner",
                    "--no-privileges",
                ],
                env=environment,
                stdin=backup,
            )
        run_checked(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "--username",
                env_values["POSTGRES_USER"],
                "--dbname",
                DRILL_DATABASE,
                "--set",
                "ON_ERROR_STOP=1",
                "--command",
                RESTORE_CHECK_SQL,
            ],
            env=environment,
        )
    except subprocess.CalledProcessError as exc:
        restore_return_code = exc.returncode or 1
    finally:
        cleanup = cleanup_drill_database(
            compose, environment, env_values["POSTGRES_USER"], check=False
        )
        cleanup_return_code = cleanup.returncode

    return restore_return_code or cleanup_return_code


def cleanup_drill_database(
    compose: list[str],
    environment: dict[str, str],
    postgres_user: str,
    *,
    check: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Drop the isolated drill database."""
    return subprocess.run(
        [
            *compose,
            "exec",
            "-T",
            "postgres",
            "dropdb",
            "--username",
            postgres_user,
            "--if-exists",
            "--force",
            DRILL_DATABASE,
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        check=check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
