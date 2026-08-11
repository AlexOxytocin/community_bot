"""Tests for deterministic self-hosted release and recovery contracts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_production_compose_is_private_and_uses_one_application_image() -> None:
    """The production project has no public port and one application image."""
    root = Path(__file__).parents[2]
    manifest = yaml.safe_load((root / "compose.production.yaml").read_text(encoding="utf-8"))
    services = manifest["services"]

    assert set(services) == {"postgres", "migrate", "worker", "bot"}
    assert "ports" not in services["postgres"]
    assert services["postgres"]["networks"] == ["internal"]
    assert services["postgres"]["volumes"] == ["postgres-data:/var/lib/postgresql"]
    assert manifest["networks"]["internal"]["internal"] is True
    assert services["worker"]["networks"] == ["internal", "egress"]
    assert services["bot"]["networks"] == ["internal", "egress"]
    assert {services[name]["image"] for name in ("migrate", "worker", "bot")} == {
        "${COMMUNITY_BOT_IMAGE}"
    }
    assert services["migrate"]["command"] == "community-migrate"
    assert services["worker"]["healthcheck"]["test"][-1] == "community-worker"
    assert services["bot"]["healthcheck"]["test"][-1] == "community-bot"

    serialized = json.dumps(manifest).lower()
    assert "bot_token" not in serialized
    assert "r2" not in serialized
    assert "webhook" not in serialized


def test_deployment_script_keeps_migration_worker_bot_order() -> None:
    """The bot starts only after migration and worker readiness."""
    root = Path(__file__).parents[2]
    script = (root / "ops" / "deploy_self_hosted.sh").read_text(encoding="utf-8")

    migrate = script.index('"${compose[@]}" run --rm migrate')
    worker = script.index('"${compose[@]}" up -d --no-deps worker')
    worker_health = script.index("wait_for_health worker community-worker")
    bot = script.index('"${compose[@]}" up -d --no-deps bot')
    bot_health = script.index("wait_for_health bot community-bot")
    assert migrate < worker < worker_health < bot < bot_health
    assert "previous-image" in script
    assert "docker pull" in script
    assert "immutable image digest or image ID" in script
    assert "^sha256:[0-9a-f]{64}$" in script
    assert "docker image inspect" in script
    assert "0:600" in script


def test_backup_restore_and_release_assets_keep_mvp_boundaries() -> None:
    """Backup is local, restore isolated, and CI records an immutable image."""
    root = Path(__file__).parents[2]
    backup = (root / "ops" / "backup_postgres.sh").read_text(encoding="utf-8")
    restore = (root / "ops" / "restore_drill.sh").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "pg_dump" in backup
    assert "/var/backups/community-bot" in backup
    assert "-mtime +7 -delete" in backup
    assert "community_bot_restore_drill" in restore
    assert "pg_restore" in restore
    assert "alembic_version" in restore
    assert "account_transactions" in restore
    assert "credit_balance_cached" in restore
    assert "experience_total_cached" in restore
    assert "Ledger reconciliation failed" in restore
    assert "ledger_mismatch_count" in restore
    assert "ledger_entries" not in restore
    assert "current-image" in backup
    assert "COMMUNITY_BOT_ENV_FILE" in backup
    assert "0:600" in backup
    assert "current-image" in restore
    assert "COMMUNITY_BOT_ENV_FILE" in restore
    assert "0:600" in restore
    assert "@${{ steps.image.outputs.digest }}" in workflow
    assert "platforms: linux/arm64" in workflow
    assert "linux/amd64" not in workflow
    assert "retention-days: 30" in workflow
    assert "RENDER_" not in workflow
    for forbidden in ("R2", "Cloudflare", "webhook"):
        assert forbidden.lower() not in (backup + restore).lower()
