from __future__ import annotations

import json

# ruff: noqa: D102, D107, EM101, TRY003 - deliberately minimal fault-injection adapter.
from typing import TYPE_CHECKING, Any

import pytest
from ops import wallet_cutover as cutover

if TYPE_CHECKING:
    from pathlib import Path


class FakeHost(cutover.Host):
    """Record each release boundary and inject exactly one failure."""

    def __init__(self, failure: str | None = None) -> None:
        self.receipt: dict[str, Any] = {}
        self.events: list[str] = []
        self.failure = failure

    def event(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name:
            self.failure = None
            raise cutover.CutoverError("injected failure")

    def stop(self) -> None:
        self.event("stop")

    def backup_restore(self) -> None:
        self.event("backup_restore")

    def migrate(self, *, database: str | None = None, downgrade: bool = False) -> None:
        del database, downgrade
        self.event("migrate")

    def check_snapshot(self, database: str | None, head: str) -> None:
        del database, head
        self.event("invariants")

    def start(self, *, maintenance: bool = False, old: bool = False) -> None:
        del old
        self.event("start_frozen" if maintenance else "start_open")

    def verify(self, *, maintenance: bool = False, old: bool = False) -> None:
        del old
        self.event("verify_frozen" if maintenance else "verify_open")

    def rollback(self) -> None:
        self.event("rollback")


@pytest.mark.parametrize(
    "failure", ["stop", "backup_restore", "migrate", "invariants", "start_frozen", "verify_frozen"]
)
def test_pre_activation_failure_restores_old_runtime(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = FakeHost(failure)
    monkeypatch.setattr(cutover, "save", lambda *_: None)
    with pytest.raises(cutover.CutoverError, match="injected"):
        cutover.execute(host, tmp_path / "receipt.json")
    assert host.events[-1] == "rollback"
    assert "start_open" not in host.events
    assert host.receipt["phase"] == "rolled_back"


def test_frozen_backup_and_activation_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = FakeHost()
    phases: list[str] = []
    monkeypatch.setattr(cutover, "save", lambda _, data: phases.append(data["phase"]))
    cutover.execute(host, tmp_path / "receipt.json")
    assert host.events == [
        "stop",
        "backup_restore",
        "migrate",
        "invariants",
        "start_frozen",
        "verify_frozen",
        "invariants",
        "start_open",
        "verify_open",
    ]
    assert phases == ["stopping", "backup", "migrating", "writers_enabled", "ready"]


@pytest.mark.parametrize("failure", ["start_open", "verify_open"])
def test_after_activation_failure_recovers_forward_without_discarding_data(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = FakeHost(failure)
    monkeypatch.setattr(cutover, "save", lambda *_: None)
    cutover.execute(host, tmp_path / "receipt.json")
    assert "rollback" not in host.events
    assert host.receipt["phase"] == "ready"
    assert host.events.count("start_open") == 2


@pytest.mark.parametrize("changed", [None, "identity", "service"])
def test_postgres_old_package_requires_same_identity_and_service(
    changed: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = FakeHost()
    host.receipt = {
        "postgres": "postgres",
        "postgres_id": "container-id",
        "postgres_image": "image-id",
        "postgres_config": "/measured/old.yaml",
        "postgres_config_sha256": "digest",
    }
    item = {
        "Id": "changed" if changed == "identity" else "container-id",
        "Image": "image-id",
        "Config": {
            "Labels": {
                "com.docker.compose.project.config_files": "/measured/old.yaml",
                "com.docker.compose.project": cutover.PROJECT,
            }
        },
    }
    monkeypatch.setattr(cutover, "inspect", lambda _: item)
    monkeypatch.setattr(cutover, "digest", lambda _: "digest")
    monkeypatch.setattr(
        host,
        "compose",
        lambda *_, **kwargs: json.dumps(
            {
                "services": {
                    "postgres": {
                        "image": (
                            "changed" if changed == "service" and kwargs.get("config") else "same"
                        )
                    }
                }
            }
        ),
    )
    if changed:
        with pytest.raises(cutover.CutoverError, match="PostgreSQL"):
            cutover.validate_postgres(host)
    else:
        cutover.validate_postgres(host)
