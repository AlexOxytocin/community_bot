from __future__ import annotations

# ruff: noqa: SLF001 - this module directly verifies private trust-boundary branches
import json
import os
import subprocess
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, BinaryIO, cast

import pytest
from ops import release_contract as contract

if TYPE_CHECKING:
    from collections.abc import Iterator


def _bundle(
    tmp_path: Path,
    *,
    release_run_number: int = 3,
    marker: str = "",
    filename: str = "release-bundle.tar",
) -> Path:
    entries = {
        name: (f"content:{marker}:{name}".encode(), mode)
        for name, mode in contract.PACKAGE_FILES.items()
    }
    package = contract._tar(entries)
    manifest = {
        "contract_version": contract.VERSION,
        "repository": contract.REPOSITORY,
        "commit_sha": (marker or "a") * 40,
        "tree_sha": "b" * 40,
        "pr_number": 1,
        "ci_run_id": 2,
        "ci_run_attempt": 1,
        "release_run_number": release_run_number,
        "release_run_attempt": 1,
        "image": f"ghcr.io/alexoxytocin/community_bot@sha256:{(marker or 'c') * 64}",
        "migration_head": "migration_head",
        "host_package": {
            "sha256": contract._digest(package),
            "size": len(package),
            "files": [
                {
                    "path": name,
                    "sha256": contract._digest(raw),
                    "mode": f"{mode:04o}",
                }
                for name, (raw, mode) in entries.items()
            ],
        },
    }
    path = tmp_path / filename
    path.write_bytes(
        contract._tar(
            {
                "host-package.tar": (package, 0o600),
                "manifest.json": (contract._canonical(manifest), 0o600),
            }
        )
    )
    return path


def test_bundle_is_deterministic_and_tamper_fails_closed(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    manifest, raw, files = contract.verify_bundle(bundle)

    assert manifest["image"].endswith("c" * 64)
    assert contract._digest(raw) == contract._digest(contract._canonical(manifest))
    assert list(files) == list(contract.PACKAGE_FILES)
    assert _bundle(tmp_path).read_bytes() == bundle.read_bytes()

    package = contract._tar({"extra": (b"unsafe", 0o600)})
    bad = tmp_path / "bad.tar"
    bad.write_bytes(
        contract._tar(
            {
                "host-package.tar": (package, 0o600),
                "manifest.json": (raw, 0o600),
            }
        )
    )
    with pytest.raises(contract.ContractError):
        contract.verify_bundle(bad)


def test_bundle_read_is_bounded_before_tar_parsing(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.tar"
    oversized.write_bytes(b"x" * (contract.MAX_BUNDLE + 1))

    with pytest.raises(contract.ContractError, match="exceeds its size limit"):
        contract.verify_bundle(oversized)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"status":"ready","status":"pending"}',
        b'{"unknown":true}',
        b"\xff",
    ],
)
def test_json_rejects_duplicate_unknown_or_invalid_input(raw: bytes) -> None:
    def parse_and_validate() -> None:
        value = contract._json(raw)
        if isinstance(value, dict):
            contract._validate_manifest(value, b"")

    with pytest.raises(contract.ContractError):
        parse_and_validate()


def test_state_accepts_only_ready_or_exact_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "d" * 64
    path = tmp_path / "active.json"
    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    states: list[dict[str, Any]] = [
        {
            "status": "ready",
            "operation": None,
            "current": {"manifest_sha256": digest},
            "previous": None,
        },
        {
            "status": "pending",
            "operation": {"kind": "activate", "target_manifest_sha256": digest},
            "current": {"manifest_sha256": digest},
            "previous": None,
        },
    ]
    for state in states:
        path.write_text(json.dumps(state), encoding="utf-8")
        assert contract._state(path) == state
    operation = states[-1]["operation"]
    assert isinstance(operation, dict)
    operation["target_manifest_sha256"] = "e" * 64
    path.write_text(json.dumps(states[-1]), encoding="utf-8")
    with pytest.raises(contract.ContractError):
        contract._state(path)


def test_durable_state_fsyncs_parent_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_open, real_replace, real_fsync = os.open, Path.replace, os.fsync

    def mkstemp(*, prefix: str, dir: Path) -> tuple[int, str]:  # noqa: A002
        name = str(dir / f"{prefix}test")
        return real_open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), name

    def replace(source: Path, target: Path) -> Path:
        events.append("replace")
        return real_replace(source, target)

    def fsync(descriptor: int) -> None:
        events.append(
            "parent_fsync" if tmp_path.is_dir() and events.count("replace") else "file_fsync"
        )
        if descriptor != 999:
            real_fsync(descriptor)

    monkeypatch.setattr(contract.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(contract.os, "open", lambda *_args: 999)
    monkeypatch.setattr(contract.os, "close", lambda _descriptor: None)
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(contract.os, "fsync", fsync)
    path = tmp_path / "active.json"
    contract._durable(path, {"status": "ready"})

    assert events[0] == "file_fsync"
    assert events[-2:] == ["replace", "parent_fsync"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "ready"}


def _reviewed_evidence() -> dict[str, Any]:
    return {
        "repository": contract.REPOSITORY,
        "event": "pull_request",
        "pr_number": 17,
        "base_sha": "1" * 40,
        "head_sha": "2" * 40,
        "synthetic_merge_sha": "6" * 40,
        "tree_sha": "4" * 40,
        "workflow_ref": (f"{contract.REPOSITORY}/.github/workflows/ci.yml@refs/pull/17/merge"),
        "run_id": 23,
        "run_attempt": 1,
    }


def _build_values() -> dict[str, Any]:
    return {
        "commit_sha": "3" * 40,
        "pr_number": 17,
        "release_run_number": 29,
        "release_run_attempt": 1,
        "image": f"ghcr.io/alexoxytocin/community_bot@sha256:{'5' * 64}",
        "migration_head": "migration_head",
    }


def _prepare_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for name in contract.PACKAGE_FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"source:{name}", encoding="utf-8")
    return source


def _use_worktree_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        contract,
        "_git_blob",
        lambda source, _commit, path: (source / path).read_bytes(),
    )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("base_sha", "7" * 40),
        ("head_sha", "8" * 40),
        ("synthetic_merge_sha", "6" * 39),
        ("tree_sha", "9" * 40),
        ("workflow_ref", "AlexOxytocin/community_bot/.github/workflows/ci.yml@refs/heads/main"),
        ("run_id", 0),
        ("run_attempt", "1"),
    ],
)
def test_build_rejects_non_exact_reviewed_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: object,
) -> None:
    evidence = _reviewed_evidence()
    evidence[field] = bad_value
    evidence_path = tmp_path / "provenance.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    source = _prepare_source(tmp_path)
    _use_worktree_blobs(monkeypatch)
    monkeypatch.setattr(
        contract,
        "_git",
        lambda _source, *args: {
            ("show", "-s", "--format=%P", "3" * 40): f"{'1' * 40} {'2' * 40}",
            ("rev-parse", f"{'3' * 40}^{{tree}}"): "4" * 40,
            ("rev-parse", "HEAD"): "3" * 40,
        }[args],
    )

    with pytest.raises(contract.ContractError):
        contract.build_bundle(source, tmp_path / "bundle.tar", evidence_path, _build_values())


def test_build_accepts_exact_reviewed_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "provenance.json"
    evidence_path.write_text(json.dumps(_reviewed_evidence()), encoding="utf-8")
    source = _prepare_source(tmp_path)
    _use_worktree_blobs(monkeypatch)
    monkeypatch.setattr(
        contract,
        "_git",
        lambda _source, *args: {
            ("show", "-s", "--format=%P", "3" * 40): f"{'1' * 40} {'2' * 40}",
            ("rev-parse", f"{'3' * 40}^{{tree}}"): "4" * 40,
            ("rev-parse", "HEAD"): "3" * 40,
        }[args],
    )
    output = tmp_path / "bundle.tar"

    contract.build_bundle(source, output, evidence_path, _build_values())

    assert contract.verify_bundle(output)[0]["commit_sha"] == "3" * 40


def test_build_rejects_noncanonical_release_commit_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "provenance.json"
    evidence_path.write_text(json.dumps(_reviewed_evidence()), encoding="utf-8")
    values = _build_values()
    values["commit_sha"] = "A" * 40
    monkeypatch.setattr(contract, "_git", lambda *_args: pytest.fail("git must not run"))

    with pytest.raises(contract.ContractError, match="commit_sha"):
        contract.build_bundle(
            _prepare_source(tmp_path),
            tmp_path / "bundle.tar",
            evidence_path,
            values,
        )


def test_build_rejects_dirty_packaged_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_path = tmp_path / "provenance.json"
    evidence_path.write_text(json.dumps(_reviewed_evidence()), encoding="utf-8")
    source = _prepare_source(tmp_path)
    monkeypatch.setattr(
        contract,
        "_git",
        lambda _source, *args: {
            ("show", "-s", "--format=%P", "3" * 40): f"{'1' * 40} {'2' * 40}",
            ("rev-parse", f"{'3' * 40}^{{tree}}"): "4" * 40,
            ("rev-parse", "HEAD"): "3" * 40,
        }[args],
    )
    monkeypatch.setattr(contract, "_git_blob", lambda *_args: b"reviewed bytes")

    with pytest.raises(contract.ContractError, match="differs from the reviewed commit"):
        contract.build_bundle(source, tmp_path / "bundle.tar", evidence_path, _build_values())


def test_git_blob_rejects_non_blob_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contract, "_git", lambda *_args: "tree")

    with pytest.raises(contract.ContractError, match="not a regular Git blob"):
        contract._git_blob(tmp_path, "3" * 40, "ops")


def test_installed_release_checks_every_packaged_file_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _manifest, manifest_raw, files = contract.verify_bundle(_bundle(tmp_path))
    digest = contract._digest(manifest_raw)
    directory = tmp_path / "shared" / "releases" / digest
    for name, raw in {"manifest.json": manifest_raw, **files}.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    checked: list[tuple[Path, int]] = []
    rejected_name: str | None = None

    def secure(path: Path, mode: int, *, directory: bool = False) -> None:
        if not directory:
            checked.append((path.relative_to(directory_path), mode))
        if path.name == rejected_name:
            message = "unsafe packaged file"
            raise contract.ContractError(message)

    directory_path = directory
    monkeypatch.setattr(contract, "_secure", secure)

    contract._release(tmp_path, digest)
    assert checked == [
        (Path("manifest.json"), 0o600),
        *((Path(path), mode) for path, mode in contract.PACKAGE_FILES.items()),
    ]

    checked.clear()
    rejected_name = "restore_drill.py"
    with pytest.raises(contract.ContractError, match="unsafe packaged file"):
        contract._release(tmp_path, digest)

    assert checked == [
        (Path("manifest.json"), 0o600),
        (Path("compose.production.yaml"), 0o600),
        (Path("ops/__init__.py"), 0o600),
        (Path("ops/_runtime.py"), 0o600),
        (Path("ops/backup_postgres.py"), 0o700),
        (Path("ops/restore_drill.py"), 0o700),
    ]


@pytest.mark.parametrize("inspect_output", ["", "[]", "{}"])
def test_preflight_rejects_empty_or_non_list_image_inspect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inspect_output: str,
) -> None:
    manifest = contract.verify_bundle(_bundle(tmp_path))[0]
    monkeypatch.setattr(
        contract,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=inspect_output),
    )

    with pytest.raises(contract.ContractError, match="Docker image inspect"):
        contract._preflight(tmp_path, manifest, tmp_path, None)


@pytest.mark.parametrize(
    ("source", "malformed"),
    [
        ("image", " migration_head\n"),
        ("image", "migration_head\n\n"),
        ("live", "migration_head\r\n"),
        ("live", "migration_head extra\n"),
    ],
)
def test_preflight_rejects_malformed_migration_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    malformed: str,
) -> None:
    manifest = contract.verify_bundle(_bundle(tmp_path))[0]
    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    commands: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(argv)
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "RepoDigests": [manifest["image"]],
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.source": (
                                        "https://github.com/AlexOxytocin/community_bot"
                                    ),
                                    "org.opencontainers.image.revision": manifest["commit_sha"],
                                }
                            },
                        }
                    ]
                )
            )
        if argv[:2] == ["docker", "run"]:
            return SimpleNamespace(stdout=malformed if source == "image" else "migration_head\n")
        if "psql" in " ".join(argv):
            return SimpleNamespace(stdout=malformed if source == "live" else "migration_head\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(contract, "_run", run)

    with pytest.raises(contract.ContractError, match="migration head"):
        contract._preflight(tmp_path, manifest, tmp_path, None)

    if source == "live":
        psql_command = next(command for command in commands if "psql" in " ".join(command))
        assert psql_command[-3:-1] == ["sh", "-c"]
        assert '--username="$POSTGRES_USER"' in psql_command[-1]
        assert '--dbname="$POSTGRES_DB"' in psql_command[-1]


def test_initial_activation_rejects_existing_processes_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"transferred")
    manifest_raw = b'{"release":"initial"}\n'
    digest = contract._digest(manifest_raw)
    target = releases / digest
    target.mkdir()
    manifest = {
        "migration_head": "migration_head",
        "release_run_number": 1,
        "release_run_attempt": 1,
    }

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(
        contract,
        "verify_bundle",
        lambda _bundle: (manifest, manifest_raw, {}),
    )
    monkeypatch.setattr(contract, "_release", lambda *_args: (manifest, target))
    monkeypatch.setattr(contract, "_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_compose", lambda *_args: (["compose"], {}))
    monkeypatch.setattr(contract, "_preflight", lambda *_args: pytest.fail("preflight mutated"))
    monkeypatch.setattr(
        contract,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="existing-container-id\n"),
    )
    monkeypatch.setattr(contract, "_durable", lambda *_args: pytest.fail("state mutated"))
    monkeypatch.setattr(contract, "_lifecycle", lambda *_args, **_kwargs: pytest.fail("lifecycle"))

    with pytest.raises(contract.ContractError, match="worker and web to be absent"):
        contract.activate(bundle, root)


def test_activate_a_then_b_then_rollback_consumes_previous(  # noqa: C901, PLR0915
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    (root / "shared" / ".env").write_text("DATABASE_URL=unused\n", encoding="utf-8")
    bundle_a = _bundle(tmp_path, release_run_number=1, filename="a.tar")
    bundle_b = _bundle(
        tmp_path,
        release_run_number=2,
        marker="d",
        filename="b.tar",
    )
    commits = {
        contract.verify_bundle(bundle_a)[0]["image"]: "a" * 40,
        contract.verify_bundle(bundle_b)[0]["image"]: "d" * 40,
    }
    commands: list[list[str]] = []
    timeline: list[str] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if argv[-2:] == ["stop", "web"] or "up" in argv:
            timeline.append(f"process:{argv[-1]}")
        stdout = ""
        if argv[:3] == ["docker", "image", "inspect"]:
            image = argv[3]
            stdout = json.dumps(
                [
                    {
                        "RepoDigests": [image],
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.source": (
                                    "https://github.com/AlexOxytocin/community_bot"
                                ),
                                "org.opencontainers.image.revision": commits[image],
                            }
                        },
                    }
                ]
            )
        elif argv[:2] == ["docker", "run"] or "psql" in " ".join(argv):
            stdout = "migration_head\n"
        elif "ps" in argv and "--format" in argv:
            stdout = "\n".join(
                json.dumps({"Service": service, "State": "running", "Health": "healthy"})
                for service in ("worker", "web")
            )
        return subprocess.CompletedProcess(argv, 0, stdout=stdout)

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    state_events: list[dict[str, Any]] = []
    durable = contract._durable
    fsync_directory = contract._fsync_directory
    real_replace = Path.replace

    def record_state(path: Path, value: dict[str, Any]) -> None:
        state_events.append(deepcopy(value))
        durable(path, value)
        timeline.append(f"state:{value['status']}")

    def record_directory_sync(path: Path) -> None:
        timeline.append(f"sync:{path.name}")
        fsync_directory(path)

    def record_replace(source: Path, target: Path) -> Path:
        if source.name.startswith(".release."):
            timeline.append("rename:release")
        return real_replace(source, target)

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(contract, "_run", run)
    monkeypatch.setattr(contract, "_durable", record_state)
    monkeypatch.setattr(contract, "_fsync_directory", record_directory_sync)
    monkeypatch.setattr(Path, "replace", record_replace)
    monkeypatch.setattr(contract.os, "fsync", lambda _descriptor: None)
    real_open, real_close = os.open, os.close
    monkeypatch.setattr(
        contract.os,
        "open",
        lambda path, flags, mode=0o777: (
            999 if Path(path).is_dir() else real_open(path, flags, mode)
        ),
    )
    monkeypatch.setattr(
        contract.os,
        "close",
        lambda descriptor: None if descriptor == 999 else real_close(descriptor),
    )

    contract.activate(bundle_a, root)
    assert timeline[0] == "sync:ops"
    assert timeline[1].startswith("sync:.release.")
    assert timeline[2:4] == ["rename:release", "sync:releases"]
    assert timeline.index("state:pending") < timeline.index("process:worker")
    contract.activate(bundle_b, root)
    lifecycle_call = contract._lifecycle
    crash = True

    def crash_once(
        compose: list[str],
        env: dict[str, str],
        *,
        stop_old: tuple[list[str], dict[str, str]] | None,
    ) -> None:
        nonlocal crash
        if crash:
            crash = False
            message = "simulated crash after pending rollback"
            raise contract.ContractError(message)
        lifecycle_call(compose, env, stop_old=stop_old)

    monkeypatch.setattr(contract, "_lifecycle", crash_once)
    with pytest.raises(contract.ContractError, match="simulated crash"):
        contract.rollback(root)
    crashed = json.loads((releases / "active.json").read_text(encoding="utf-8"))
    assert crashed["status"] == "pending"
    assert crashed["operation"]["kind"] == "rollback"
    assert crashed["previous"] is None
    contract.rollback(root)

    final = json.loads((releases / "active.json").read_text(encoding="utf-8"))
    digest_a = contract._digest(contract.verify_bundle(bundle_a)[1])
    assert [
        (state["status"], state["operation"] and state["operation"]["kind"])
        for state in state_events
    ] == [
        ("pending", "activate"),
        ("ready", None),
        ("pending", "activate"),
        ("ready", None),
        ("pending", "rollback"),
        ("pending", "rollback"),
        ("ready", None),
    ]
    assert final == {
        "status": "ready",
        "operation": None,
        "current": {"manifest_sha256": digest_a},
        "previous": None,
    }
    lifecycle = [
        (argv[-2], argv[-1]) if argv[-2:] == ["stop", "web"] else ("up", argv[-1])
        for argv in commands
        if argv[-2:] == ["stop", "web"] or "up" in argv
    ]
    assert lifecycle == [
        ("up", "worker"),
        ("up", "web"),
        ("stop", "web"),
        ("up", "worker"),
        ("up", "web"),
        ("stop", "web"),
        ("up", "worker"),
        ("up", "web"),
    ]
    assert all("migrate" not in argv and "pull" not in argv for argv in commands)
    assert all(
        "--network" not in argv or argv[argv.index("--network") + 1] == "none" for argv in commands
    )


def test_rollback_rejects_other_pending_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    digest = "a" * 64

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(
        contract,
        "_state",
        lambda _path: {
            "status": "pending",
            "operation": {"kind": "activate", "target_manifest_sha256": digest},
            "current": {"manifest_sha256": digest},
            "previous": None,
        },
    )

    with pytest.raises(contract.ContractError, match="different operation is pending"):
        contract.rollback(tmp_path)


@pytest.mark.parametrize(
    ("state_status", "live_head"),
    [("ready", "0021"), ("pending", "0021"), ("pending", "0022")],
)
def test_exact_cutover_orders_durable_freeze_proof_migrate_and_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state_status: str,
    live_head: str,
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"transferred")
    target_raw = b'{"target":"0022"}\n'
    target_digest = contract._digest(target_raw)
    source_digest = "a" * 64
    source_directory = releases / source_digest
    target_directory = releases / target_digest
    source_directory.mkdir()
    target_directory.mkdir()
    source = {
        "migration_head": "0021",
        "release_run_number": 104,
        "release_run_attempt": 1,
        "image": "source-image",
        "commit_sha": "a" * 40,
    }
    target = {
        "migration_head": "0022",
        "release_run_number": 105,
        "release_run_attempt": 1,
        "image": "target-image",
        "commit_sha": "b" * 40,
    }
    state = (
        {
            "status": "pending",
            "operation": {"kind": "cutover", "target_manifest_sha256": target_digest},
            "current": {"manifest_sha256": target_digest},
            "previous": {"manifest_sha256": source_digest},
        }
        if state_status == "pending"
        else {
            "status": "ready",
            "operation": None,
            "current": {"manifest_sha256": source_digest},
            "previous": None,
        }
    )
    timeline: list[str] = []

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    def release(_root: Path, digest: str) -> tuple[dict[str, Any], Path]:
        return (source, source_directory) if digest == source_digest else (target, target_directory)

    def durable(_path: Path, value: dict[str, Any]) -> None:
        timeline.append(f"state:{value['status']}")

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        if "stop" in argv:
            timeline.append("stop:web+worker")
        elif "migrate" in argv:
            timeline.append("migrate")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(contract, "verify_bundle", lambda _bundle: (target, target_raw, {}))
    monkeypatch.setattr(contract, "_release", release)
    monkeypatch.setattr(contract, "_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(contract, "_cutover_preflight", lambda *_args: (["target"], {}, live_head))
    monkeypatch.setattr(contract, "_cutover_backup_directory", lambda: tmp_path)
    monkeypatch.setattr(
        contract,
        "_compose",
        lambda _root, directory, _manifest: ([directory.name], {}),
    )
    monkeypatch.setattr(contract, "_durable", durable)
    monkeypatch.setattr(contract, "_run", run)
    monkeypatch.setattr(
        contract,
        "_create_cutover_proof",
        lambda *_args, **_kwargs: timeline.append("backup+restore") or tmp_path / "backup.dump",
    )
    monkeypatch.setattr(
        contract,
        "_verify_cutover_proof",
        lambda *_args: timeline.append("verify-proof") or tmp_path / "backup.dump",
    )
    monkeypatch.setattr(contract, "_live_head", lambda *_args: "0022")
    monkeypatch.setattr(
        contract,
        "_lifecycle",
        lambda *_args, **_kwargs: timeline.append("lifecycle"),
    )

    contract.cutover_0021_to_0022(bundle, root)

    middle = ["backup+restore", "migrate"] if live_head == "0021" else ["verify-proof"]
    assert timeline == ["state:pending", "stop:web+worker", *middle, "lifecycle", "state:ready"]


def test_cutover_backup_is_durable_before_it_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_replace = Path.replace

    def run(_argv: list[str], **kwargs: object) -> SimpleNamespace:
        events.append("pg_dump")
        output = cast("BinaryIO", kwargs["stdout"])
        output.write(b"durable dump")
        return SimpleNamespace(stdout="")

    def replace(source: Path, target: Path) -> Path:
        events.append("rename")
        return real_replace(source, target)

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_run", run)
    monkeypatch.setattr(contract.os, "fsync", lambda _descriptor: events.append("fsync:dump"))
    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(
        contract, "_fsync_directory", lambda _path: events.append("fsync:directory")
    )

    (tmp_path / "backups").mkdir(mode=0o700)
    backup = contract._create_cutover_backup(
        tmp_path / "backups", "production", "operator", ["compose"], {}
    )

    assert backup.read_bytes() == b"durable dump"
    assert backup.name.startswith(".cutover-")
    assert "production" not in backup.name
    assert events == ["pg_dump", "fsync:dump", "rename", "fsync:directory"]


def test_ready_cutover_requires_existing_proof_before_health_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"transferred")
    raw = b'{"target":"0022"}\n'
    target_digest = contract._digest(raw)
    (releases / target_digest).mkdir()
    source_digest = "a" * 64
    target = {"migration_head": "0022"}
    state = {
        "status": "ready",
        "operation": None,
        "current": {"manifest_sha256": target_digest},
        "previous": {"manifest_sha256": source_digest},
    }

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(contract, "verify_bundle", lambda _bundle: (target, raw, {}))
    monkeypatch.setattr(contract, "_release", lambda *_args: (target, releases / target_digest))
    monkeypatch.setattr(contract, "_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(contract, "_preflight", lambda *_args: (["compose"], {}))
    monkeypatch.setattr(contract, "_cutover_backup_directory", lambda: tmp_path)
    monkeypatch.setattr(
        contract,
        "_verify_cutover_proof",
        lambda *_args: (_ for _ in ()).throw(contract.ContractError("missing proof")),
    )
    monkeypatch.setattr(contract, "_ready", lambda *_args: pytest.fail("health before proof"))

    with pytest.raises(contract.ContractError, match="missing proof"):
        contract.cutover_0021_to_0022(bundle, root)


def test_cutover_proof_rejects_changed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "production.dump"
    backup.write_bytes(b"original")
    proof = tmp_path / "proof.json"
    proof.write_bytes(
        contract._canonical(
            {
                "contract_version": contract.CUTOVER_PROOF_VERSION,
                "from_head": "0021",
                "to_head": "0022",
                "current_manifest_sha256": "a" * 64,
                "target_manifest_sha256": "b" * 64,
                "backup_path": str(backup),
                "backup_sha256": contract._file_digest(backup),
            }
        )
    )
    backup.write_bytes(b"changed")
    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)

    with pytest.raises(contract.ContractError, match="digest"):
        contract._verify_cutover_proof(proof, "a" * 64, "b" * 64, backup_dir)


def test_cutover_proof_rejects_parent_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    escaped = tmp_path / "escaped.dump"
    escaped.write_bytes(b"dump")
    proof = tmp_path / "proof.json"
    proof.write_bytes(
        contract._canonical(
            {
                "contract_version": contract.CUTOVER_PROOF_VERSION,
                "from_head": "0021",
                "to_head": "0022",
                "current_manifest_sha256": "a" * 64,
                "target_manifest_sha256": "b" * 64,
                "backup_path": str(backup_dir / ".." / escaped.name),
                "backup_sha256": contract._file_digest(escaped),
            }
        )
    )
    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)

    with pytest.raises(contract.ContractError, match="outside"):
        contract._verify_cutover_proof(proof, "a" * 64, "b" * 64, backup_dir)


def test_cutover_proof_rechecks_backup_directory_before_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "cutover.dump"
    backup.write_bytes(b"dump")
    proof = tmp_path / "proof.json"
    proof.write_bytes(
        contract._canonical(
            {
                "contract_version": contract.CUTOVER_PROOF_VERSION,
                "from_head": "0021",
                "to_head": "0022",
                "current_manifest_sha256": "a" * 64,
                "target_manifest_sha256": "b" * 64,
                "backup_path": str(backup),
                "backup_sha256": contract._file_digest(backup),
            }
        )
    )
    secure_calls: list[tuple[Path, int, bool]] = []
    monkeypatch.setattr(
        contract,
        "_secure",
        lambda path, mode, *, directory=False: secure_calls.append((path, mode, directory)),
    )

    assert contract._verify_cutover_proof(proof, "a" * 64, "b" * 64, backup_dir) == backup
    assert secure_calls[0] == (backup_dir, 0o700, True)


@pytest.mark.parametrize(
    "case",
    [
        ("0020", "0022", "0021", "only migration"),
        ("0021", "0023", "0021", "only migration"),
        ("0021", "0022", "0020", "neither source nor target"),
    ],
)
def test_cutover_preflight_rejects_wrong_source_target_or_live_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, str, str],
) -> None:
    source_head, target_head, live_head, message = case
    source = {"migration_head": source_head}
    target = {"migration_head": target_head}
    monkeypatch.setattr(contract, "_compose", lambda *_args: (["compose"], {}))
    monkeypatch.setattr(contract, "_run", lambda *_args, **_kwargs: SimpleNamespace(stdout=""))
    monkeypatch.setattr(contract, "_image_head", lambda _manifest: target_head)
    monkeypatch.setattr(contract, "_live_head", lambda *_args: live_head)

    with pytest.raises(contract.ContractError, match=message):
        contract._cutover_preflight(tmp_path, target, tmp_path, source)


@pytest.mark.parametrize("rejection", ["foreign-pending", "stale"])
def test_cutover_rejects_foreign_pending_or_stale_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rejection: str
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"transferred")
    raw = b'{"target":"0022"}\n'
    target_digest = contract._digest(raw)
    source_digest = "a" * 64
    (releases / target_digest).mkdir()
    (releases / source_digest).mkdir()
    target = {"migration_head": "0022", "release_run_number": 2, "release_run_attempt": 1}
    source = {
        "migration_head": "0021",
        "release_run_number": 2 if rejection == "stale" else 1,
        "release_run_attempt": 1,
    }
    state = (
        {
            "status": "pending",
            "operation": {"kind": "activate", "target_manifest_sha256": target_digest},
            "current": {"manifest_sha256": target_digest},
            "previous": {"manifest_sha256": source_digest},
        }
        if rejection == "foreign-pending"
        else {
            "status": "ready",
            "operation": None,
            "current": {"manifest_sha256": source_digest},
            "previous": None,
        }
    )

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(contract, "verify_bundle", lambda _bundle: (target, raw, {}))
    monkeypatch.setattr(
        contract,
        "_release",
        lambda _root, digest: (
            (source, releases / source_digest)
            if digest == source_digest
            else (target, releases / target_digest)
        ),
    )
    monkeypatch.setattr(contract, "_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(contract, "_durable", lambda *_args: pytest.fail("mutation"))

    with pytest.raises(contract.ContractError, match=r"different operation|stale"):
        contract.cutover_0021_to_0022(bundle, root)


def test_cutover_rejects_noncurrent_operations_package_before_backup(
    tmp_path: Path,
) -> None:
    current_directory = tmp_path / "release"
    (current_directory / "ops").mkdir(parents=True)

    with pytest.raises(contract.ContractError, match="not the current release package"):
        contract._create_cutover_proof(
            tmp_path,
            {"image": "source", "commit_sha": "a" * 40},
            current_directory,
            "a" * 64,
            "b" * 64,
            backup_dir=tmp_path,
        )


@pytest.mark.parametrize("failure", ["backup-dir", "restore", "migrate"])
def test_cutover_failure_after_pending_never_writes_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    root = tmp_path / "host"
    releases = root / "shared" / "releases"
    releases.mkdir(parents=True)
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(b"transferred")
    raw = b'{"target":"0022"}\n'
    target_digest = contract._digest(raw)
    source_digest = "a" * 64
    source_directory = releases / source_digest
    target_directory = releases / target_digest
    source_directory.mkdir()
    target_directory.mkdir()
    source = {"migration_head": "0021", "release_run_number": 1, "release_run_attempt": 1}
    target = {"migration_head": "0022", "release_run_number": 2, "release_run_attempt": 1}
    states: list[str] = []

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        if failure == "migrate" and "migrate" in argv:
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(contract, "_secure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(contract, "verify_bundle", lambda _bundle: (target, raw, {}))
    monkeypatch.setattr(
        contract,
        "_release",
        lambda _root, digest: (
            (source, source_directory) if digest == source_digest else (target, target_directory)
        ),
    )
    monkeypatch.setattr(
        contract,
        "_state",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "operation": None,
            "current": {"manifest_sha256": source_digest},
            "previous": None,
        },
    )
    monkeypatch.setattr(contract, "_cutover_preflight", lambda *_args: (["target"], {}, "0021"))
    monkeypatch.setattr(
        contract,
        "_cutover_backup_directory",
        lambda: (
            (_ for _ in ()).throw(contract.ContractError("unsafe backup directory"))
            if failure == "backup-dir"
            else tmp_path
        ),
    )
    monkeypatch.setattr(contract, "_compose", lambda *_args: (["source"], {}))
    monkeypatch.setattr(contract, "_durable", lambda _path, value: states.append(value["status"]))
    monkeypatch.setattr(contract, "_run", run)
    monkeypatch.setattr(
        contract,
        "_create_cutover_proof",
        lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(contract.ContractError("restore failed"))
            if failure == "restore"
            else tmp_path / "backup.dump"
        ),
    )

    with pytest.raises((contract.ContractError, subprocess.CalledProcessError)):
        contract.cutover_0021_to_0022(bundle, root)
    assert states == ([] if failure == "backup-dir" else ["pending"])


def test_rollback_rejects_schema_downgrade_before_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract.os, "geteuid", lambda: 0, raising=False)
    current_digest = "b" * 64
    previous_digest = "a" * 64

    @contextmanager
    def unlocked(_root: Path) -> Iterator[None]:
        yield

    monkeypatch.setattr(contract, "_exclusive_lock", unlocked)
    monkeypatch.setattr(
        contract,
        "_state",
        lambda _path: {
            "status": "ready",
            "operation": None,
            "current": {"manifest_sha256": current_digest},
            "previous": {"manifest_sha256": previous_digest},
        },
    )
    monkeypatch.setattr(
        contract,
        "_release",
        lambda _root, digest: (
            {"migration_head": "0022" if digest == current_digest else "0021"},
            tmp_path,
        ),
    )
    monkeypatch.setattr(contract, "_preflight", lambda *_args: pytest.fail("preflight"))

    with pytest.raises(contract.ContractError, match="cannot downgrade"):
        contract.rollback(tmp_path)


def test_cli_routes_only_the_five_explicit_contract_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(contract, "build_bundle", lambda *_args: calls.append("build"))
    monkeypatch.setattr(contract, "activate", lambda *_args: calls.append("activate"))
    monkeypatch.setattr(contract, "cutover_0021_to_0022", lambda *_args: calls.append("cutover"))
    monkeypatch.setattr(contract, "rollback", lambda *_args: calls.append("rollback"))

    assert (
        contract.main(
            [
                "build",
                "--source",
                str(tmp_path),
                "--output",
                str(tmp_path / "out.tar"),
                "--evidence",
                str(tmp_path / "provenance.json"),
                "--commit-sha",
                "3" * 40,
                "--image",
                f"ghcr.io/alexoxytocin/community_bot@sha256:{'5' * 64}",
                "--migration-head",
                "migration_head",
                "--pr-number",
                "17",
                "--release-run-number",
                "29",
                "--release-run-attempt",
                "1",
            ]
        )
        == 0
    )
    assert contract.main(["verify", str(bundle)]) == 0
    assert contract.main(["activate", str(bundle), "--root", str(tmp_path)]) == 0
    assert contract.main(["cutover-0021-to-0022", str(bundle), "--root", str(tmp_path)]) == 0
    assert contract.main(["rollback", "--root", str(tmp_path)]) == 0

    assert calls == ["build", "activate", "cutover", "rollback"]
    assert "ghcr.io/alexoxytocin/community_bot@sha256:" in capsys.readouterr().out
