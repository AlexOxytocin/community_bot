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


def test_ci_and_publication_keep_legacy_runtime_out_of_scope() -> None:
    """CI proof and publication do not regain deployment authority or R1 runtime."""
    root = Path(__file__).parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "pull_request:" in ci
    assert "push:" not in ci
    assert "uv run ty check src tests ops" in ci
    assert "uv run pytest" in ci
    workflow = yaml.safe_load(ci)
    assert "image-contract" in workflow["jobs"]["verified-merge-tree"]["needs"]
    assert "verify_release_provenance.py" not in ci
    publication = yaml.safe_load(release)
    assert publication[True]["push"]["branches"] == ["main"]
    assert set(publication["jobs"]) == {"publish"}
    assert "path: release-bundle.tar" in release
    for forbidden in ("ssh", "deploy-key", "forced-command", "environment: production"):
        assert forbidden not in release.lower()


def test_host_maintenance_surface_is_python_and_data_only() -> None:
    """The manual contract adds one Python tool, not an R1 deployment surface."""
    root = Path(__file__).parents[2]
    assert {path.name for path in (root / "ops").glob("*.py")} == {
        "__init__.py",
        "_runtime.py",
        "backup_postgres.py",
        "release_contract.py",
        "restore_drill.py",
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
