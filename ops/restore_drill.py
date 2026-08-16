"""Restore a PostgreSQL dump into an isolated drill database and verify it."""

from __future__ import annotations

import argparse
import re
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
REVISION_QUERY_SQL = "SELECT version_num FROM alembic_version ORDER BY version_num;"
DRILL_DATABASE_COUNT_SQL = (
    "SELECT count(*) FROM pg_database WHERE datname = 'community_bot_restore_drill';"
)
_REVISION_BYTES_RE = re.compile(rb"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RESTORE_CHECK_SQL = """
DO $$
BEGIN
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
    env_values = require_env_values(read_dotenv(env_file), "POSTGRES_USER", "POSTGRES_DB")
    postgres_user = env_values["POSTGRES_USER"]
    production_database = env_values["POSTGRES_DB"]
    require_distinct_database_names(production_database)
    environment = operations_environment(env_file, image_reference)
    compose = compose_command(root_dir, env_file)

    cleanup_drill_database(
        compose,
        environment,
        postgres_user,
        verification_database=production_database,
    )
    expected_head = read_image_migration_head(image_reference)
    production_revisions = read_database_revisions(
        compose,
        environment,
        postgres_user,
        production_database,
    )
    require_exact_revision(
        production_revisions,
        expected_head,
        database_label="production",
    )
    print(f"expected_alembic_head={expected_head}")
    print(f"production_alembic_revision={expected_head}")

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
                postgres_user,
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
                    postgres_user,
                    "--dbname",
                    DRILL_DATABASE,
                    "--no-owner",
                    "--no-privileges",
                ],
                env=environment,
                stdin=backup,
            )
        restored_revisions = read_database_revisions(
            compose,
            environment,
            postgres_user,
            DRILL_DATABASE,
        )
        require_exact_revision(
            restored_revisions,
            expected_head,
            database_label="restored",
        )
        print(f"restored_alembic_revision={expected_head}")
        run_checked(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "--username",
                postgres_user,
                "--dbname",
                DRILL_DATABASE,
                "--set",
                "ON_ERROR_STOP=1",
                "--command",
                RESTORE_CHECK_SQL,
            ],
            env=environment,
        )
    except (OpsError, subprocess.CalledProcessError) as exc:
        restore_return_code = failure_code(exc)
        print("restore_or_validation_failed", file=sys.stderr)
    finally:
        try:
            cleanup_drill_database(
                compose,
                environment,
                postgres_user,
                verification_database=production_database,
            )
        except OpsError:
            cleanup_return_code = 1
            print("cleanup_failed", file=sys.stderr)

    return restore_return_code or cleanup_return_code


def require_distinct_database_names(production_database: str) -> None:
    """Reject a configuration that would make cleanup target production."""
    if production_database == DRILL_DATABASE:
        raise OpsError("Production database must differ from restore drill database.")


def capture_stdout_bytes(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> bytes:
    """Capture exact stdout bytes without universal-newline conversion."""
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        env=env,
    )
    return result.stdout


def exact_protocol_rows(output: bytes) -> list[bytes]:
    """Split literal LF-delimited byte rows, ignoring only one terminal LF."""
    if output == b"":
        return []
    payload = output.removesuffix(b"\n")
    return payload.split(b"\n")


def parse_image_migration_head(output: bytes) -> str:
    """Parse one exact ASCII revision with at most one terminal LF."""
    heads = exact_protocol_rows(output)
    if len(heads) != 1 or _REVISION_BYTES_RE.fullmatch(heads[0]) is None:
        raise OpsError("Release image must report exactly one valid migration head.")
    return heads[0].decode("ascii")


def read_image_migration_head(image_reference: str) -> str:
    """Read one migration head from the exact immutable application image."""
    try:
        output = capture_stdout_bytes(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--entrypoint",
                "community-migration-head",
                image_reference,
            ]
        )
    except subprocess.CalledProcessError as exc:
        raise OpsError("Failed to read release image migration head.") from exc
    return parse_image_migration_head(output)


def read_database_revisions(
    compose: list[str],
    environment: dict[str, str],
    postgres_user: str,
    database: str,
) -> list[bytes]:
    """Return every Alembic revision row from one database."""
    try:
        output = capture_stdout_bytes(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "--username",
                postgres_user,
                "--dbname",
                database,
                "--set",
                "ON_ERROR_STOP=1",
                "--tuples-only",
                "--no-align",
                "--command",
                REVISION_QUERY_SQL,
            ],
            env=environment,
        )
    except subprocess.CalledProcessError as exc:
        raise OpsError("Failed to read Alembic revisions from database.") from exc
    return exact_protocol_rows(output)


def require_exact_revision(
    revisions: list[bytes],
    expected_head: str,
    *,
    database_label: str,
) -> None:
    """Require cardinality one and exact equality with the image head."""
    if len(revisions) != 1 or revisions[0] != expected_head.encode("ascii"):
        raise OpsError(
            f"The {database_label} database must contain exactly the release image Alembic head."
        )


def parse_drill_database_count(output: bytes) -> bool:
    """Parse one exact cleanup count row without text normalization."""
    rows = exact_protocol_rows(output)
    if len(rows) != 1 or rows[0] not in {b"0", b"1"}:
        raise OpsError("Failed to verify drill database absence.")
    return rows[0] == b"1"


def drill_database_exists(
    compose: list[str],
    environment: dict[str, str],
    postgres_user: str,
    verification_database: str,
) -> bool:
    """Return whether the fixed drill database is still present."""
    try:
        output = capture_stdout_bytes(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "--username",
                postgres_user,
                "--dbname",
                verification_database,
                "--set",
                "ON_ERROR_STOP=1",
                "--tuples-only",
                "--no-align",
                "--command",
                DRILL_DATABASE_COUNT_SQL,
            ],
            env=environment,
        )
    except subprocess.CalledProcessError as exc:
        raise OpsError("Failed to verify drill database absence.") from exc
    return parse_drill_database_count(output)


def cleanup_drill_database(
    compose: list[str],
    environment: dict[str, str],
    postgres_user: str,
    *,
    verification_database: str,
) -> None:
    """Drop the isolated drill database and prove its absence."""
    cleanup = subprocess.run(
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
        check=False,
    )
    if cleanup.returncode != 0:
        raise OpsError("Restore drill cleanup failed.")
    if drill_database_exists(
        compose,
        environment,
        postgres_user,
        verification_database,
    ):
        raise OpsError("Restore drill cleanup postcondition failed.")


def failure_code(exc: OpsError | subprocess.CalledProcessError) -> int:
    """Return a stable nonzero code without exposing exception details."""
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.returncode or 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
