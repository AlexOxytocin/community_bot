"""Create a root-only PostgreSQL logical backup for the Mini App backend."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import stat
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
    validate_environment_file,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one encrypted backup and print the created dump path."""
    parser = argparse.ArgumentParser(prog="backup_postgres.py")
    parser.add_argument("--encrypted-output", required=True, type=Path)
    parser.add_argument("--sha256-manifest", required=True, type=Path)
    parser.add_argument("--gpg-passphrase-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        backup_path = create_backup(
            args.encrypted_output,
            args.sha256_manifest,
            args.gpg_passphrase_file,
        )
    except OpsError as exc:
        fail(str(exc))
    print(backup_path)
    return 0


def create_backup(output: Path, manifest: Path, passphrase_file: Path) -> Path:
    """Stream one custom-format dump into GPG without a plaintext file."""
    root_dir = default_root_dir()
    env_file = root_dir / "shared" / ".env"

    validate_environment_file(env_file)
    validate_secure_targets(output, manifest, passphrase_file)
    gpg = shutil.which("gpg")
    if gpg is None:
        raise OpsError("GPG is required for encrypted PostgreSQL backup.")
    image_reference = read_current_image(root_dir)
    env_values = require_env_values(read_dotenv(env_file), "POSTGRES_DB", "POSTGRES_USER")
    environment = operations_environment(env_file, image_reference)
    compose = compose_command(root_dir, env_file)

    temporary = output.with_name(f".{output.name}.part")

    previous_umask = os.umask(0o077)
    try:
        stream_encrypt(
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
            [
                gpg,
                "--batch",
                "--yes",
                "--pinentry-mode",
                "loopback",
                "--symmetric",
                "--cipher-algo",
                "AES256",
                "--passphrase-file",
                str(passphrase_file),
                "--output",
                str(temporary),
            ],
            environment,
        )
        if temporary.stat().st_size == 0:
            raise OpsError("PostgreSQL backup is empty.")
        temporary.replace(output)
        write_sha256_manifest(output, manifest)
    finally:
        os.umask(previous_umask)
        if temporary.exists():
            temporary.unlink()

    prune_old_backups(output.parent, now=dt.datetime.now(dt.UTC), retention_days=7)
    return output


def validate_secure_targets(output: Path, manifest: Path, passphrase_file: Path) -> None:
    """Require external owner-only paths and a root-owned passphrase file."""
    if not output.is_absolute() or not manifest.is_absolute() or not passphrase_file.is_absolute():
        raise OpsError("Backup, manifest and passphrase paths must be absolute.")
    repository = Path(__file__).resolve().parents[1]
    for path in (output, manifest):
        if path.resolve().is_relative_to(repository):
            raise OpsError("Encrypted backup artifacts must stay outside the repository.")
        if path.exists():
            raise OpsError("Encrypted backup artifacts must not overwrite existing files.")
    if output.parent != manifest.parent:
        raise OpsError("Backup and manifest must use the same secure directory.")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    require_root_owned(output.parent, expected_mode=0o700, regular=False)
    require_root_owned(passphrase_file, expected_mode=0o600, regular=True)


def require_root_owned(path: Path, *, expected_mode: int, regular: bool) -> None:
    """Require an unsymlinked root-owned file or directory with an exact mode."""
    try:
        status = path.lstat()
    except FileNotFoundError as exc:
        raise OpsError("Secure backup path is missing.") from exc
    expected_type = stat.S_ISREG if regular else stat.S_ISDIR
    if stat.S_ISLNK(status.st_mode) or not expected_type(status.st_mode):
        raise OpsError("Secure backup path has an invalid type.")
    if status.st_uid != 0 or stat.S_IMODE(status.st_mode) != expected_mode:
        raise OpsError("Secure backup path must be root-owned with owner-only permissions.")


def stream_encrypt(
    dump_command: list[str], gpg_command: list[str], environment: dict[str, str]
) -> None:
    """Connect pg_dump stdout directly to GPG stdin and require both processes."""
    dump = subprocess.Popen(
        dump_command,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if dump.stdout is None:
        dump.kill()
        raise OpsError("PostgreSQL backup pipe could not be created.")
    encrypt = subprocess.Popen(
        gpg_command,
        stdin=dump.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    dump.stdout.close()
    encrypt_code = encrypt.wait()
    dump_code = dump.wait()
    if dump_code or encrypt_code:
        raise OpsError("Encrypted PostgreSQL backup failed.")


def sha256_file(path: Path) -> str:
    """Return the exact SHA-256 digest of a file."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_sha256_manifest(backup: Path, manifest: Path) -> None:
    """Atomically write one owner-only manifest for the encrypted backup."""
    payload = {
        "schema": "community_bot.encrypted_backup.v1",
        "file": backup.name,
        "sha256": sha256_file(backup),
        "size": backup.stat().st_size,
    }
    temporary = manifest.with_name(f".{manifest.name}.part")
    try:
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(manifest)
    finally:
        if temporary.exists():
            temporary.unlink()


def prune_old_backups(backup_dir: Path, *, now: dt.datetime, retention_days: int) -> None:
    """Remove old dump files from the configured backup directory."""
    cutoff = now.timestamp() - retention_days * 24 * 60 * 60
    for dump_file in backup_dir.glob("*.dump.gpg"):
        if dump_file.is_file() and dump_file.stat().st_mtime < cutoff:
            dump_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
