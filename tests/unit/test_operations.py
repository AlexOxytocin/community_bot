"""Tests for deterministic self-hosted release and recovery contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WINDOWS_GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
_BASH = str(_WINDOWS_GIT_BASH) if _WINDOWS_GIT_BASH.exists() else shutil.which("bash")
_FLOCK = shutil.which("flock")


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
    assert {services[name]["environment"]["RELEASE"] for name in ("migrate", "worker", "bot")} == {
        "${COMMUNITY_BOT_RELEASE:-manual}"
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
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    migrate = script.index('"${compose[@]}" run --rm migrate')
    config = script.index('"${compose[@]}" run --rm migrate community-bootstrap-product-config')
    worker = script.index('"${compose[@]}" up -d --no-deps --force-recreate worker')
    worker_health = script.index("wait_for_health worker community-worker")
    bot = script.index('"${compose[@]}" up -d --no-deps --force-recreate bot')
    bot_health = script.index("wait_for_health bot community-bot")
    assert migrate < config < worker < worker_health < bot < bot_health
    assert "community-bootstrap-admin" in script[migrate:config]
    assert "COPY config ./config" in dockerfile
    assert "previous-image" in script
    assert "docker pull" in script
    assert "immutable image digest or image ID" in script
    assert "^sha256:[0-9a-f]{64}$" in script
    assert "docker image inspect" in script
    assert "0:600" in script
    assert "COMMUNITY_BOT_RELEASE" in script
    assert "--not-before" in script
    assert script.count("--force-recreate") == 2
    assert "worker_not_before" in script
    assert "bot_not_before" in script


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
    assert "@${DIGEST}" in workflow
    assert "platforms: linux/arm64" in workflow
    assert "linux/amd64" not in workflow
    assert "retention-days: 30" in workflow
    assert "RENDER_" not in workflow
    for forbidden in ("R2", "Cloudflare", "webhook"):
        assert forbidden.lower() not in (backup + restore).lower()


def test_ci_and_release_keep_one_fail_closed_full_test_path() -> None:
    """PR CI proves the tree and release consumes the proof before build and deploy."""
    root = Path(__file__).parents[2]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "pull_request:" in ci
    assert "push:" not in ci
    assert "name: Verified merge tree" in ci
    assert "needs: [quality, postgresql]" in ci
    assert "provenance.json" in ci
    assert release.index("Verify pull-request CI provenance") < release.index(
        "Build and publish linux/arm64 image"
    )
    assert "StrictHostKeyChecking=yes" in release
    assert "ssh-keyscan" not in release
    assert "${GITHUB_RUN_NUMBER} ${GITHUB_RUN_ATTEMPT}" in release
    assert '"root@${PRODUCTION_HOST}"' in release
    assert "environment: production" in release


def test_forced_deploy_entrypoint_is_narrow_and_monotonic() -> None:
    """The automation key cannot request a shell or deploy an older workflow run."""
    root = Path(__file__).parents[2]
    script = (root / "ops" / "github_deploy_entrypoint.sh").read_text(encoding="utf-8")

    assert "SSH_ORIGINAL_COMMAND" in script
    assert "eval" not in script
    assert "ghcr\\.io/alexgoodman53/community_bot" in script
    assert "flock -x" in script
    assert "run_number < current_number" in script
    assert "run_attempt <= current_attempt" in script
    assert "$(id -u)" in script
    assert ".run${run_number}.${run_attempt}" in script
    assert 'trusted_bin_dir="${root_dir}/shared/bin"' in script
    assert 'deploy_script="${trusted_bin_dir}/deploy_self_hosted.sh"' in script
    assert "stat -c '%u:%a'" in script


@pytest.mark.skipif(_BASH is None, reason="requires bash")
@pytest.mark.parametrize(
    "command",
    [
        "deploy 1 1 " + "a" * 40 + " ghcr.io/alexgoodman53/community_bot:latest",
        "deploy 1 1 " + "a" * 40 + " ghcr.io/other/repo@sha256:" + "b" * 64,
        "deploy 1 1 "
        + "a" * 40
        + " ghcr.io/alexgoodman53/community_bot@sha256:"
        + "b" * 64
        + " extra",
        "deploy 1 1 "
        + "a" * 40
        + " ghcr.io/alexgoodman53/community_bot@sha256:"
        + "b" * 64
        + "; id",
        "deploy 1 1 "
        + "a" * 40
        + " ghcr.io/alexgoodman53/community_bot@sha256:"
        + "b" * 64
        + " && id",
        "deploy 1 1 "
        + "a" * 40
        + " ghcr.io/alexgoodman53/community_bot@sha256:"
        + "b" * 64
        + " $(id)",
        "deploy 1 1 "
        + "a" * 40
        + " ghcr.io/alexgoodman53/community_bot@sha256:"
        + "b" * 64
        + "\nwhoami",
        "deploy one 1 " + "a" * 40 + " ghcr.io/alexgoodman53/community_bot@sha256:" + "b" * 64,
    ],
)
def test_forced_deploy_entrypoint_rejects_untrusted_commands(command: str) -> None:
    """Parser rejects mutable, foreign, injected, and malformed commands."""
    root = Path(__file__).parents[2]
    completed = subprocess.run(  # noqa: S603 - fixed local parser-only script.
        [
            _BASH or "bash",
            str(root / "ops" / "github_deploy_entrypoint.sh"),
            "--validate-command",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2


@pytest.mark.skipif(_BASH is None, reason="requires bash")
def test_forced_deploy_entrypoint_accepts_exact_contract() -> None:
    """The exact immutable deployment command passes parser-only validation."""
    root = Path(__file__).parents[2]
    command = "deploy 15 2 " + "a" * 40 + " ghcr.io/alexgoodman53/community_bot@sha256:" + "b" * 64
    completed = subprocess.run(  # noqa: S603 - fixed local parser-only script.
        [
            _BASH or "bash",
            str(root / "ops" / "github_deploy_entrypoint.sh"),
            "--validate-command",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0


@pytest.mark.skipif(_BASH is None or _FLOCK is None, reason="requires bash and flock")
def test_forced_deploy_entrypoint_rejects_stale_and_duplicate_sequences(
    tmp_path: Path,
) -> None:
    """The marker changes after success and rejects older or repeated deployments."""
    root = tmp_path / "community-bot"
    shared_dir = root / "shared"
    deploy_script = shared_dir / "bin" / "deploy_self_hosted.sh"
    deploy_script.parent.mkdir(parents=True)
    shared_dir.chmod(0o700)
    deploy_script.parent.chmod(0o700)
    deploy_script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf \'%s|%s\\n\' "$1" "$COMMUNITY_BOT_RELEASE" >> "$CALLS_FILE"\n',
        encoding="utf-8",
    )
    deploy_script.chmod(0o700)
    calls_file = tmp_path / "calls.txt"
    script = Path(__file__).parents[2] / "ops" / "github_deploy_entrypoint.sh"
    image = "ghcr.io/alexgoodman53/community_bot@sha256:" + "b" * 64

    def invoke(run_number: int, run_attempt: int) -> subprocess.CompletedProcess[str]:
        command = f"deploy {run_number} {run_attempt} {'a' * 40} {image}"
        return subprocess.run(  # noqa: S603 - fixed test harness and isolated root.
            [_BASH or "bash", str(script), "--test-deploy", str(root), command],
            env={"PATH": str(Path(_BASH or "bash").parent), "CALLS_FILE": str(calls_file)},
            capture_output=True,
            text=True,
            check=False,
        )

    first = invoke(20, 1)
    newer_attempt = invoke(20, 2)
    duplicate = invoke(20, 2)
    stale = invoke(19, 9)

    assert first.returncode == 0
    assert newer_attempt.returncode == 0
    assert duplicate.returncode == 3
    assert stale.returncode == 3
    digest = "sha256:" + "b" * 64
    assert calls_file.read_text(encoding="utf-8").splitlines() == [
        f"{image}|{digest}.run20.1",
        f"{image}|{digest}.run20.2",
    ]
    marker = root / "shared" / "releases" / "github-deploy-sequence"
    assert marker.read_text(encoding="utf-8").startswith("20 2 ")

    deploy_script.chmod(0o777)
    unsafe = invoke(21, 1)
    assert unsafe.returncode == 1
    assert "unsafe ownership or mode" in unsafe.stderr
