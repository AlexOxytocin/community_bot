"""Compact evidence for encrypted backup and restore boundaries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from ops import backup_postgres, restore_drill
from ops._runtime import OpsError

if TYPE_CHECKING:
    from pathlib import Path


def _secure_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def test_manifest_is_exactly_verified_before_gpg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup = _secure_file(tmp_path / "source.dump.gpg", b"encrypted")
    manifest = tmp_path / "source.dump.gpg.sha256"
    passphrase = _secure_file(tmp_path / "passphrase", b"secret")
    backup_postgres.write_sha256_manifest(backup, manifest)
    monkeypatch.setattr(restore_drill, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(restore_drill.shutil, "which", lambda _name: "/usr/bin/gpg")

    command = restore_drill.prepare_encrypted_restore(backup, manifest, passphrase)

    assert command[-1] == str(backup)
    assert "--decrypt" in command


def test_manifest_mismatch_fails_before_gpg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup = _secure_file(tmp_path / "source.dump.gpg", b"encrypted")
    manifest = _secure_file(tmp_path / "source.dump.gpg.sha256", b"{}")
    passphrase = _secure_file(tmp_path / "passphrase", b"secret")
    monkeypatch.setattr(restore_drill, "require_root_owned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        restore_drill.shutil,
        "which",
        lambda _name: pytest.fail("GPG lookup must happen after manifest verification"),
    )

    with pytest.raises(OpsError, match="manifest does not match"):
        restore_drill.prepare_encrypted_restore(backup, manifest, passphrase)


def test_manifest_contains_only_encrypted_file_identity(tmp_path: Path) -> None:
    backup = _secure_file(tmp_path / "source.dump.gpg", b"encrypted")
    manifest = tmp_path / "source.dump.gpg.sha256"

    backup_postgres.write_sha256_manifest(backup, manifest)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload == {
        "schema": "community_bot.encrypted_backup.v1",
        "file": backup.name,
        "sha256": backup_postgres.sha256_file(backup),
        "size": len(b"encrypted"),
    }
