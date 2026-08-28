"""Tests for the retained Mini App backend operations boundary."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from ops import _runtime as runtime

if TYPE_CHECKING:
    from collections.abc import Iterator


def test_production_compose_contains_internal_web_without_public_ports() -> None:
    """One image serves the private database, migration, worker, and web contract."""
    root = Path(__file__).parents[2]
    manifest = yaml.safe_load((root / "compose.production.yaml").read_text(encoding="utf-8"))
    services = manifest["services"]

    assert set(services) == {"postgres", "migrate", "worker", "web"}
    assert "ports" not in services["postgres"]
    assert "ports" not in services["web"]
    assert services["postgres"]["networks"] == ["internal"]
    assert manifest["networks"]["internal"]["internal"] is True
    assert services["worker"]["networks"] == ["internal", "egress"]
    assert services["web"]["networks"] == ["internal"]
    assert {services[name]["image"] for name in ("migrate", "worker", "web")} == {
        "${COMMUNITY_BOT_IMAGE}"
    }
    assert services["migrate"]["command"] == "community-migrate"
    assert services["worker"]["command"] == "community-worker"
    assert services["web"]["command"] == "community-web"
    assert services["worker"]["healthcheck"]["test"][-1] == "community-worker"
    assert "/readyz" in services["web"]["healthcheck"]["test"][-1]
    assert services["worker"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["web"]["depends_on"]["worker"]["condition"] == "service_healthy"
    assert all(
        service["environment"]["RELEASE"]
        == "${COMMUNITY_BOT_RELEASE:?COMMUNITY_BOT_RELEASE is required}"
        for service in (services["migrate"], services["worker"], services["web"])
    )

    serialized = json.dumps(manifest["services"]).lower()
    assert '"bot"' not in serialized
    assert "webhook" not in serialized


def test_backup_and_restore_keep_database_safety_contract() -> None:
    """Cleanup preserves recoverability and exact migration verification."""
    root = Path(__file__).parents[2]
    runtime = (root / "ops" / "_runtime.py").read_text(encoding="utf-8")
    backup = (root / "ops" / "backup_postgres.py").read_text(encoding="utf-8")
    restore = (root / "ops" / "restore_drill.py").read_text(encoding="utf-8")

    assert "pg_dump" in backup
    assert "retention_days=7" in backup
    assert "community_bot_restore_drill" in restore
    assert "pg_restore" in restore
    assert "SELECT version_num FROM alembic_version ORDER BY version_num" in restore
    assert "community-migration-head" in restore
    assert "account_transactions" in restore
    assert "Ledger reconciliation failed" in restore
    assert "selected_release" in backup
    assert "selected_release" in restore
    assert "active.json" in runtime
    assert "current-image" not in runtime
    assert "COMMUNITY_BOT_ENV_FILE" in runtime
    assert "COMMUNITY_BOT_RELEASE" in runtime
    assert "mode 0600" in runtime


def test_ci_and_deploy_use_one_bounded_manual_dev_path() -> None:
    """Dev delivery keeps one bounded path without deploying every main push."""
    root = Path(__file__).parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "pull_request:" in ci
    assert "push:" not in ci
    assert "uv run ty check src tests ops" in ci
    assert "uv run pytest" in ci
    assert "verified-merge-tree" not in ci
    assert "image-contract" not in ci
    assert "release-bundle" not in release
    publication = yaml.safe_load(release)
    assert publication[True] == {"workflow_dispatch": None}
    assert "push:" not in release
    assert publication["concurrency"]["cancel-in-progress"] is False
    assert set(publication["jobs"]) == {"deploy"}
    assert "DEV_DEPLOY_SSH_PRIVATE_KEY" in release
    assert 'started="$(date +%s)"' in release
    assert "PUSHED_AT" not in release


def test_fast_deploy_uses_the_running_release_as_its_safety_baseline() -> None:
    """A stale legacy manifest cannot turn an ordinary update into a slow path."""
    root = Path(__file__).parents[2]
    deploy = (root / "ops" / "deploy_dev.py").read_text(encoding="utf-8")

    assert "before_release" in deploy
    assert '"diff"' in deploy
    assert '"--quiet"' in deploy
    assert "before_release," in deploy
    assert "before_image = require_release_image(before_release)" in deploy
    assert 'run("docker", "tag", before_image, PREVIOUS_IMAGE)' in deploy
    assert "if target_head != live_head:" in deploy
    assert 'manifest["commit_sha"]' not in deploy
    assert 'manifest["migration_head"]' not in deploy


def test_migration_deploy_is_private_backup_first_and_non_interactive() -> None:
    root = Path(__file__).parents[2]
    deploy = (root / "ops" / "deploy_dev.py").read_text(encoding="utf-8")

    assert "allo.godmodetools.com" not in deploy
    assert "urllib.request" not in deploy
    assert "def backup_restore_drill(" in deploy
    assert 'Path("/var/backups/community-bot")' in deploy
    assert 'RESTORE_DATABASE = "community_bot_restore_drill"' in deploy
    assert "Migration rehearsal did not reach the target head." in deploy
    assert 'f"DATABASE_URL={restore_url}"' in deploy
    assert "def run_migration(" in deploy
    assert '"--no-deps",\n                    "-T",\n                    "migrate"' in deploy
    assert "Forward migration completed; automatic image rollback is unsafe." in deploy


def test_host_maintenance_surface_is_python_and_data_only() -> None:
    """The manual contract adds one Python tool, not an R1 deployment surface."""
    root = Path(__file__).parents[2]
    assert {path.name for path in (root / "ops").glob("*.py")} == {
        "__init__.py",
        "_runtime.py",
        "backup_postgres.py",
        "deploy_dev.py",
        "prepare_onboarding_local.py",
        "release_contract.py",
        "restore_drill.py",
        "seed_task_home_local.py",
    }
    assert list((root / "ops").glob("*.sh")) == []
    assert list((root / "ops" / "systemd").glob("*")) == []


def test_selected_release_binds_one_ready_tuple_and_rejects_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared-lock selection resolves one content-addressed ready tuple."""
    releases = tmp_path / "shared" / "releases"
    releases.mkdir(parents=True)
    manifest = {
        "contract_version": "community-mini-app-release/v1",
        "repository": "AlexOxytocin/community_bot",
        "commit_sha": "a" * 40,
        "image": f"ghcr.io/alexoxytocin/community_bot@sha256:{'b' * 64}",
    }
    raw = json.dumps(manifest, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    release = releases / digest
    (release / "ops").mkdir(parents=True)
    (release / "manifest.json").write_bytes(raw)
    (release / "compose.production.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "shared" / ".env").write_text("POSTGRES_DB=test\n", encoding="utf-8")

    @contextmanager
    def unlocked(_path: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(runtime, "_shared_lock", unlocked)
    monkeypatch.setattr(runtime, "validate_environment_file", lambda _path: None)
    active = releases / "active.json"
    ready = {
        "status": "ready",
        "operation": None,
        "current": {"manifest_sha256": digest},
        "previous": None,
    }
    active.write_text(json.dumps(ready), encoding="utf-8")
    with runtime.selected_release(tmp_path) as selected:
        assert selected == (
            release,
            tmp_path / "shared" / ".env",
            manifest["image"],
            manifest["commit_sha"],
        )

    for invalid_previous in ("too-short", "A" * 64, 7):
        ready["previous"] = {"manifest_sha256": invalid_previous}
        active.write_text(json.dumps(ready), encoding="utf-8")
        with (
            pytest.raises(runtime.OpsError, match="invalid previous manifest identity"),
            runtime.selected_release(tmp_path),
        ):
            pass

    ready["status"] = "pending"
    ready["operation"] = {"kind": "activate", "target_manifest_sha256": digest}
    ready["previous"] = None
    active.write_text(json.dumps(ready), encoding="utf-8")
    with (
        pytest.raises(runtime.OpsError, match=r"blocked while.*pending"),
        runtime.selected_release(tmp_path),
    ):
        pass
