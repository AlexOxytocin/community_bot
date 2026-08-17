"""Tests for the retained Mini App backend operations boundary."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_production_compose_contains_only_database_migration_and_worker() -> None:
    """The transitional runtime has no public port or legacy bot process."""
    root = Path(__file__).parents[2]
    manifest = yaml.safe_load((root / "compose.production.yaml").read_text(encoding="utf-8"))
    services = manifest["services"]

    assert set(services) == {"postgres", "migrate", "worker"}
    assert "ports" not in services["postgres"]
    assert services["postgres"]["networks"] == ["internal"]
    assert manifest["networks"]["internal"]["internal"] is True
    assert services["worker"]["networks"] == ["internal", "egress"]
    assert {services[name]["image"] for name in ("migrate", "worker")} == {"${COMMUNITY_BOT_IMAGE}"}
    assert services["migrate"]["command"] == "community-migrate"
    assert services["worker"]["command"] == "community-worker"
    assert services["worker"]["healthcheck"]["test"][-1] == "community-worker"

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
    assert "read_current_image" in backup
    assert "read_current_image" in restore
    assert "COMMUNITY_BOT_ENV_FILE" in runtime
    assert "mode 0600" in runtime


def test_ci_has_no_release_or_legacy_runtime_dependency() -> None:
    """Pull-request CI validates the retained source and full PostgreSQL suite."""
    root = Path(__file__).parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in ci
    assert "push:" not in ci
    assert "uv run ty check src tests ops" in ci
    assert "uv run pytest" in ci
    assert "verify_release_provenance.py" not in ci
    assert not (root / ".github" / "workflows" / "release.yml").exists()


def test_host_maintenance_surface_is_python_and_data_only() -> None:
    """Only backup/restore helpers remain after deleting the old bot release path."""
    root = Path(__file__).parents[2]
    assert {path.name for path in (root / "ops").glob("*.py")} == {
        "__init__.py",
        "_runtime.py",
        "backup_postgres.py",
        "check_refactor_contract.py",
        "restore_drill.py",
    }
    assert list((root / "ops").glob("*.sh")) == []
    assert list((root / "ops" / "systemd").glob("*")) == []
