"""Behavioral fault matrix for the isolated PostgreSQL restore drill."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from ops import restore_drill
from ops._runtime import OpsError

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_HEAD = "0020"
IMAGE = "sha256:" + "a" * 64


def completed(returncode: int = 0) -> subprocess.CompletedProcess[bytes]:
    """Return a small subprocess result for orchestration tests."""
    return subprocess.CompletedProcess([], returncode)


def called_process_error(returncode: int = 7) -> subprocess.CalledProcessError:
    """Return a subprocess failure without private output."""
    return subprocess.CalledProcessError(returncode, ["safe-command"])


def child_command(raw_output: bytes) -> list[str]:
    """Return a real child process that writes exact bytes to stdout."""
    return [
        sys.executable,
        "-c",
        f"import sys; sys.stdout.buffer.write({raw_output!r})",
    ]


@pytest.mark.parametrize(
    "raw_output",
    [b"0020\r\n", b"0020\r", b"\xff"],
)
def test_real_child_stdout_bytes_are_preserved_and_rejected_by_all_protocol_gates(
    raw_output: bytes,
) -> None:
    """Transport must preserve forbidden bytes for every fail-closed parser."""
    captured = restore_drill.capture_stdout_bytes(child_command(raw_output))

    assert captured == raw_output
    with pytest.raises(OpsError, match="exactly one valid migration head"):
        restore_drill.parse_image_migration_head(captured)
    with pytest.raises(OpsError, match="production database"):
        restore_drill.require_exact_revision(
            restore_drill.exact_protocol_rows(captured),
            EXPECTED_HEAD,
            database_label="production",
        )
    with pytest.raises(OpsError, match="verify drill database absence"):
        restore_drill.parse_drill_database_count(captured)


@pytest.mark.parametrize("raw_output", [b"0020", b"0020\n"])
def test_real_child_stdout_accepts_exact_revision_protocol(raw_output: bytes) -> None:
    """A real child may emit one ASCII revision and one optional terminal LF."""
    captured = restore_drill.capture_stdout_bytes(child_command(raw_output))

    assert captured == raw_output
    assert restore_drill.parse_image_migration_head(captured) == EXPECTED_HEAD
    restore_drill.require_exact_revision(
        restore_drill.exact_protocol_rows(captured),
        EXPECTED_HEAD,
        database_label="production",
    )


def test_read_image_migration_head_uses_exact_isolated_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expected head comes from the immutable image without env or network."""
    calls: list[tuple[list[str], dict[str, object]]] = []

    def capture(command: list[str], **kwargs: object) -> bytes:
        calls.append((command, kwargs))
        return f"{EXPECTED_HEAD}\n".encode()

    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", capture)

    assert restore_drill.read_image_migration_head(IMAGE) == EXPECTED_HEAD
    assert calls == [
        (
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
                IMAGE,
            ],
            {},
        )
    ]


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"   ",
        b"0020\n0021",
        b"0020\n0021\n",
        b" 0020",
        b"0020 ",
        b"\n0020\n",
        b"0020\n\n",
        b"0020\n \n",
        b"0020\r\n",
        b"0020\r",
        b"bad head",
        b"@invalid",
        b"\xff",
    ],
)
def test_read_image_migration_head_rejects_invalid_stdout(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
) -> None:
    """Empty, ambiguous, or malformed stdout fails closed."""
    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", lambda *_args, **_kwargs: output)

    with pytest.raises(OpsError, match="exactly one valid migration head"):
        restore_drill.read_image_migration_head(IMAGE)


@pytest.mark.parametrize("output", [EXPECTED_HEAD.encode(), f"{EXPECTED_HEAD}\n".encode()])
def test_read_image_migration_head_accepts_only_optional_terminal_lf(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
) -> None:
    """One exact revision may omit or include one terminal Linux newline."""
    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", lambda *_args, **_kwargs: output)

    assert restore_drill.read_image_migration_head(IMAGE) == EXPECTED_HEAD


def test_read_image_migration_head_converts_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker failure becomes a safe operational precondition error."""

    def fail(*_args: object, **_kwargs: object) -> bytes:
        raise called_process_error()

    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", fail)

    with pytest.raises(OpsError, match="release image migration head"):
        restore_drill.read_image_migration_head(IMAGE)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (b"", []),
        (b"0020", [b"0020"]),
        (b"0020\n", [b"0020"]),
        (b"0020\nother\n", [b"0020", b"other"]),
        (b"0020 \n", [b"0020 "]),
        (b"\n0020\n", [b"", b"0020"]),
        (b"0020\n\n", [b"0020", b""]),
        (b"0020\n \n", [b"0020", b" "]),
        (b"0020\r\n", [b"0020\r"]),
    ],
)
def test_read_database_revisions_returns_every_row(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    expected: list[bytes],
) -> None:
    """The DB gate preserves row cardinality instead of selecting a scalar."""
    calls: list[list[str]] = []

    def capture(command: list[str], **_kwargs: object) -> bytes:
        calls.append(command)
        return output

    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", capture)

    assert (
        restore_drill.read_database_revisions(["compose"], {"SAFE": "1"}, "operator", "database")
        == expected
    )
    command = calls[0]
    assert command[:4] == ["compose", "exec", "-T", "postgres"]
    assert "--tuples-only" in command
    assert "--no-align" in command
    assert "SELECT version_num FROM alembic_version ORDER BY version_num;" in command


def test_read_database_revisions_converts_query_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A psql failure cannot be mistaken for an empty successful result."""

    def fail(*_args: object, **_kwargs: object) -> bytes:
        raise called_process_error()

    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", fail)

    with pytest.raises(OpsError, match="read Alembic revisions"):
        restore_drill.read_database_revisions(["compose"], {}, "operator", "database")


@pytest.mark.parametrize(
    "revisions",
    [
        [],
        [b"wrong"],
        [EXPECTED_HEAD.encode(), b"other"],
        [f" {EXPECTED_HEAD}".encode()],
        [f"{EXPECTED_HEAD} ".encode()],
        [b"", EXPECTED_HEAD.encode()],
        [EXPECTED_HEAD.encode(), b" "],
        [b"0020\r"],
        [b"\xff"],
    ],
)
def test_require_exact_revision_rejects_zero_wrong_or_multiple_rows(
    revisions: list[bytes],
) -> None:
    """Both databases require cardinality one and exact equality."""
    with pytest.raises(OpsError, match="production database"):
        restore_drill.require_exact_revision(revisions, EXPECTED_HEAD, database_label="production")


def test_require_exact_revision_accepts_one_expected_row() -> None:
    """The only accepted DB state is one row equal to the image head."""
    restore_drill.require_exact_revision(
        [EXPECTED_HEAD.encode()], EXPECTED_HEAD, database_label="restored"
    )


@pytest.mark.parametrize(("output", "expected_count"), [(b"0\n", 0), (b"1\n", 1)])
def test_drill_database_exists_parses_exact_count(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    expected_count: int,
) -> None:
    """Cleanup postcondition accepts only a deterministic count."""
    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", lambda *_args, **_kwargs: output)

    assert restore_drill.drill_database_exists(["compose"], {}, "operator", "production") is bool(
        expected_count
    )


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"2",
        b"false",
        b"0\n1\n",
        b" 0\n",
        b"0 \n",
        b"\n0\n",
        b"0\n\n",
        b"0\r\n",
        b"0\r",
        b"\xff",
    ],
)
def test_drill_database_exists_rejects_ambiguous_output(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
) -> None:
    """An unprovable absence is a cleanup failure."""
    monkeypatch.setattr(restore_drill, "capture_stdout_bytes", lambda *_args, **_kwargs: output)

    with pytest.raises(OpsError, match="verify drill database absence"):
        restore_drill.drill_database_exists(["compose"], {}, "operator", "production")


def test_cleanup_is_idempotent_and_verifies_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drop uses a fixed target and succeeds when the DB is already absent."""
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return completed()

    monkeypatch.setattr(restore_drill.subprocess, "run", run)
    monkeypatch.setattr(restore_drill, "drill_database_exists", lambda *_args: False)

    restore_drill.cleanup_drill_database(
        ["compose"], {}, "operator", verification_database="production"
    )
    assert "--if-exists" in calls[0]
    assert "--force" in calls[0]
    assert calls[0][-1] == restore_drill.DRILL_DATABASE


@pytest.mark.parametrize(("returncode", "exists_count"), [(3, 0), (0, 1)])
def test_cleanup_rejects_command_or_postcondition_failure(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    exists_count: int,
) -> None:
    """Neither a failed drop nor a still-visible DB can report success."""
    monkeypatch.setattr(
        restore_drill.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(returncode),
    )
    monkeypatch.setattr(
        restore_drill,
        "drill_database_exists",
        lambda *_args: bool(exists_count),
    )

    with pytest.raises(OpsError, match="cleanup"):
        restore_drill.cleanup_drill_database(
            ["compose"], {}, "operator", verification_database="production"
        )


def prepare_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[list[str], list[str]]:
    """Install safe deterministic host preconditions for one drill."""
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"synthetic backup")
    events: list[str] = []
    cleanups: list[str] = []

    monkeypatch.setattr(restore_drill, "default_root_dir", lambda: tmp_path)
    monkeypatch.setattr(restore_drill, "validate_environment_file", lambda _path: None)
    monkeypatch.setattr(restore_drill, "read_current_image", lambda _root: IMAGE)
    monkeypatch.setattr(
        restore_drill,
        "read_dotenv",
        lambda _path: {"POSTGRES_USER": "operator", "POSTGRES_DB": "production"},
    )
    monkeypatch.setattr(
        restore_drill,
        "operations_environment",
        lambda _path, _image: {"SAFE": "1"},
    )
    monkeypatch.setattr(
        restore_drill,
        "compose_command",
        lambda _root, _path: ["compose"],
    )
    monkeypatch.setattr(restore_drill, "read_image_migration_head", lambda _image: EXPECTED_HEAD)

    def revisions(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        database: str,
    ) -> list[bytes]:
        events.append(f"revision:{database}")
        return [EXPECTED_HEAD.encode()]

    def cleanup(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        *,
        verification_database: str,
    ) -> None:
        cleanups.append(verification_database)
        events.append("cleanup")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "createdb" in command:
            events.append("createdb")
        elif "pg_restore" in command:
            events.append("pg_restore")
        elif "psql" in command:
            events.append("ledger")
        return completed()

    monkeypatch.setattr(restore_drill, "read_database_revisions", revisions)
    monkeypatch.setattr(restore_drill, "cleanup_drill_database", cleanup)
    monkeypatch.setattr(restore_drill, "run_checked", run)
    return events, cleanups


def backup_path(tmp_path: Path) -> Path:
    """Return the synthetic backup path installed by prepare_restore."""
    return tmp_path / "backup.dump"


@pytest.mark.parametrize("backup_state", ["missing", "empty"])
def test_missing_or_empty_backup_stops_before_environment_and_db_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backup_state: str,
) -> None:
    """An unusable backup fails before env, image, cleanup, or DB boundaries."""
    backup = tmp_path / "unusable.dump"
    if backup_state == "empty":
        backup.write_bytes(b"")
    calls: list[str] = []
    monkeypatch.setattr(
        restore_drill,
        "validate_environment_file",
        lambda _path: calls.append("environment"),
    )

    with pytest.raises(OpsError, match="Backup or environment file is missing"):
        restore_drill.restore_drill(backup)
    assert calls == []


def test_production_database_name_collision_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The fixed drill target can never alias the configured production DB."""
    prepare_restore(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        restore_drill,
        "read_dotenv",
        lambda _path: {
            "POSTGRES_USER": "operator",
            "POSTGRES_DB": restore_drill.DRILL_DATABASE,
        },
    )

    def unexpected_call(*_args: object, **_kwargs: object) -> None:
        calls.append("side-effect-boundary")

    monkeypatch.setattr(restore_drill, "cleanup_drill_database", unexpected_call)
    monkeypatch.setattr(restore_drill, "read_image_migration_head", unexpected_call)
    monkeypatch.setattr(restore_drill, "read_database_revisions", unexpected_call)
    monkeypatch.setattr(restore_drill, "run_checked", unexpected_call)

    with pytest.raises(OpsError, match="must differ from restore drill database"):
        restore_drill.restore_drill(backup_path(tmp_path))
    assert calls == []


def test_restore_drill_success_obeys_order_and_cleans_twice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Success requires pre-cleanup, both revisions, ledger, and final cleanup."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == 0
    assert events == [
        "cleanup",
        "revision:production",
        "createdb",
        "pg_restore",
        f"revision:{restore_drill.DRILL_DATABASE}",
        "ledger",
        "cleanup",
    ]
    assert cleanups == ["production", "production"]
    output = capsys.readouterr().out
    assert "expected_alembic_head=0020" in output
    assert "production_alembic_revision=0020" in output
    assert "restored_alembic_revision=0020" in output


@pytest.mark.parametrize(
    "revisions",
    [
        [],
        [b"wrong"],
        [EXPECTED_HEAD.encode(), b"other"],
        [f" {EXPECTED_HEAD}".encode()],
        [f"{EXPECTED_HEAD} ".encode()],
        [b"", EXPECTED_HEAD.encode()],
        [EXPECTED_HEAD.encode(), b" "],
        [b"0020\r"],
        [b"\xff"],
    ],
)
def test_production_revision_failure_stops_before_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revisions: list[bytes],
) -> None:
    """Invalid production cardinality or value blocks all restore mutations."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def invalid_revisions(*_args: object, **_kwargs: object) -> list[bytes]:
        events.append("revision:production")
        return revisions

    monkeypatch.setattr(restore_drill, "read_database_revisions", invalid_revisions)

    with pytest.raises(OpsError, match="production database"):
        restore_drill.restore_drill(backup_path(tmp_path))
    assert events == ["cleanup", "revision:production"]
    assert cleanups == ["production"]


def test_production_revision_query_failure_stops_before_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A production query error propagates after pre-cleanup and before mutation."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def fail_query(*_args: object, **_kwargs: object) -> list[bytes]:
        events.append("revision:production")
        message = "Failed to read Alembic revisions from database."
        raise OpsError(message)

    monkeypatch.setattr(restore_drill, "read_database_revisions", fail_query)

    with pytest.raises(OpsError, match="read Alembic revisions"):
        restore_drill.restore_drill(backup_path(tmp_path))
    assert events == ["cleanup", "revision:production"]
    assert cleanups == ["production"]


@pytest.mark.parametrize(
    "revisions",
    [
        [],
        [b"wrong"],
        [EXPECTED_HEAD.encode(), b"other"],
        [f" {EXPECTED_HEAD}".encode()],
        [f"{EXPECTED_HEAD} ".encode()],
        [b"", EXPECTED_HEAD.encode()],
        [EXPECTED_HEAD.encode(), b" "],
        [b"0020\r"],
        [b"\xff"],
    ],
)
def test_restored_revision_failure_returns_nonzero_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revisions: list[bytes],
) -> None:
    """An invalid restored revision fails before ledger and still cleans up."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def database_revisions(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        database: str,
    ) -> list[bytes]:
        events.append(f"revision:{database}")
        return [EXPECTED_HEAD.encode()] if database == "production" else revisions

    monkeypatch.setattr(restore_drill, "read_database_revisions", database_revisions)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == 1
    assert "ledger" not in events
    assert cleanups == ["production", "production"]


def test_restored_revision_query_failure_returns_nonzero_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A restored query error cannot skip final cleanup or enter ledger checks."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def database_revisions(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        database: str,
    ) -> list[bytes]:
        events.append(f"revision:{database}")
        if database == "production":
            return [EXPECTED_HEAD.encode()]
        message = "Failed to read Alembic revisions from database."
        raise OpsError(message)

    monkeypatch.setattr(restore_drill, "read_database_revisions", database_revisions)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == 1
    assert events == [
        "cleanup",
        "revision:production",
        "createdb",
        "pg_restore",
        f"revision:{restore_drill.DRILL_DATABASE}",
        "cleanup",
    ]
    assert cleanups == ["production", "production"]


@pytest.mark.parametrize(
    ("failure_step", "returncode"),
    [("createdb", 4), ("pg_restore", 5), ("ledger", 6)],
)
def test_restore_subprocess_failures_return_code_and_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_step: str,
    returncode: int,
) -> None:
    """Create, restore, and ledger failures all enter final cleanup."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "createdb" in command:
            step = "createdb"
        elif "pg_restore" in command:
            step = "pg_restore"
        else:
            step = "ledger"
        events.append(step)
        if step == failure_step:
            raise called_process_error(returncode)
        return completed()

    monkeypatch.setattr(restore_drill, "run_checked", run)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == returncode
    assert cleanups == ["production", "production"]


def test_pre_cleanup_failure_aborts_before_head_and_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stale DB that cannot be removed blocks the run immediately."""
    events, _cleanups = prepare_restore(monkeypatch, tmp_path)

    def fail_cleanup(*_args: object, **_kwargs: object) -> None:
        message = "Restore drill cleanup failed."
        raise OpsError(message)

    monkeypatch.setattr(restore_drill, "cleanup_drill_database", fail_cleanup)

    with pytest.raises(OpsError, match="cleanup"):
        restore_drill.restore_drill(backup_path(tmp_path))
    assert events == []


def test_final_cleanup_failure_turns_success_into_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful restore cannot pass without a proven cleanup."""
    _events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def cleanup(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        *,
        verification_database: str,
    ) -> None:
        cleanups.append(verification_database)
        if len(cleanups) == 2:
            message = "Restore drill cleanup failed."
            raise OpsError(message)

    monkeypatch.setattr(restore_drill, "cleanup_drill_database", cleanup)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == 1
    assert len(cleanups) == 2


def test_primary_and_cleanup_failures_remain_nonzero_and_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cleanup evidence is not hidden by the primary restore failure."""
    _events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise called_process_error(8)

    def cleanup(
        _compose: list[str],
        _environment: dict[str, str],
        _user: str,
        *,
        verification_database: str,
    ) -> None:
        cleanups.append(verification_database)
        if len(cleanups) == 2:
            message = "Restore drill cleanup failed."
            raise OpsError(message)

    monkeypatch.setattr(restore_drill, "run_checked", run)
    monkeypatch.setattr(restore_drill, "cleanup_drill_database", cleanup)

    assert restore_drill.restore_drill(backup_path(tmp_path)) == 8
    captured = capsys.readouterr()
    assert "restore_or_validation_failed" in captured.err
    assert "cleanup_failed" in captured.err


def test_image_head_failure_occurs_after_verified_pre_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ambiguous image metadata leaves the already-clean drill namespace absent."""
    events, cleanups = prepare_restore(monkeypatch, tmp_path)

    def fail_head(_image: str) -> str:
        message = "Release image must report exactly one valid migration head."
        raise OpsError(message)

    monkeypatch.setattr(restore_drill, "read_image_migration_head", fail_head)

    with pytest.raises(OpsError, match="exactly one"):
        restore_drill.restore_drill(backup_path(tmp_path))
    assert events == ["cleanup"]
    assert cleanups == ["production"]


def test_main_returns_success_and_converts_safe_error_to_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes deterministic success and safe precondition failure."""
    backup = tmp_path / "backup.dump"
    manifest = tmp_path / "backup.sha256"
    passphrase = tmp_path / "passphrase"
    monkeypatch.setattr(
        restore_drill,
        "prepare_encrypted_restore",
        lambda *_args: ["gpg", "--decrypt"],
    )

    def succeed(_path: Path, *, decrypt_command: list[str]) -> int:
        assert decrypt_command == ["gpg", "--decrypt"]
        return 0

    monkeypatch.setattr(
        restore_drill,
        "restore_drill",
        succeed,
    )
    arguments = [
        str(backup),
        "--sha256-manifest",
        str(manifest),
        "--gpg-passphrase-file",
        str(passphrase),
    ]
    assert restore_drill.main(arguments) == 0

    def fail(_path: Path, *, decrypt_command: list[str]) -> int:
        assert decrypt_command == ["gpg", "--decrypt"]
        message = "Safe restore failure."
        raise OpsError(message)

    monkeypatch.setattr(restore_drill, "restore_drill", fail)
    with pytest.raises(SystemExit) as exc_info:
        restore_drill.main(arguments)
    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "Safe restore failure.\n"
