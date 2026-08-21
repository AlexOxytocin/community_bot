"""Build, verify, and manually activate one Community Mini App release tuple."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "community-mini-app-release/v1"
REPOSITORY = "AlexOxytocin/community_bot"
IMAGE_RE = re.compile(r"^ghcr\.io/alexoxytocin/community_bot@sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
HEAD_RE = re.compile(r"^[0-9A-Za-z_]{1,128}$")
PACKAGE_FILES = {
    "compose.production.yaml": 0o600,
    "ops/__init__.py": 0o600,
    "ops/_runtime.py": 0o600,
    "ops/backup_postgres.py": 0o700,
    "ops/restore_drill.py": 0o700,
}
MANIFEST_KEYS = {
    "contract_version",
    "repository",
    "commit_sha",
    "tree_sha",
    "pr_number",
    "ci_run_id",
    "ci_run_attempt",
    "release_run_number",
    "release_run_attempt",
    "image",
    "migration_head",
    "host_package",
}
MAX_BUNDLE = 2_000_000
MAX_PACKAGE = 1_000_000
CUTOVER_FROM_HEAD = "0021"
CUTOVER_TO_HEAD = "0022"
CUTOVER_PROOF_VERSION = "community-mini-app-cutover-proof/v1"


class ContractError(RuntimeError):
    """A fail-closed release contract rejection."""


def _json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ContractError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Invalid UTF-8 JSON.") from exc


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _positive(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ContractError(f"{name} must be a positive integer.")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ContractError(f"{name} must be a lowercase 40-character SHA.")
    return value


def _member_name(member: tarfile.TarInfo) -> str:
    path = PurePosixPath(member.name)
    if (
        member.name != path.as_posix()
        or path.is_absolute()
        or "\\" in member.name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractError("Archive contains a non-canonical path.")
    if not member.isreg():
        raise ContractError("Archive members must be regular files.")
    return member.name


def _tar_files(raw: bytes, expected: dict[str, int], limit: int) -> dict[str, bytes]:
    if len(raw) > limit:
        raise ContractError("Archive exceeds its size limit.")
    found: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                name = _member_name(member)
                if name in found or name not in expected:
                    raise ContractError("Archive has duplicate or unexpected members.")
                if stat.S_IMODE(member.mode) != expected[name] or member.size > limit:
                    raise ContractError("Archive member has an unsafe mode or size.")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ContractError("Archive member cannot be read.")
                found[name] = stream.read(limit + 1)
                if len(found[name]) != member.size:
                    raise ContractError("Archive member size is inconsistent.")
    except (tarfile.TarError, OSError) as exc:
        raise ContractError("Invalid tar archive.") from exc
    if set(found) != set(expected):
        raise ContractError("Archive is missing required members.")
    return found


def _validate_manifest(value: Any, package: bytes) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise ContractError("Manifest fields do not match the closed schema.")
    if value["contract_version"] != VERSION or value["repository"] != REPOSITORY:
        raise ContractError("Manifest contract or repository is invalid.")
    _sha(value["commit_sha"], "commit_sha")
    _sha(value["tree_sha"], "tree_sha")
    for key in (
        "pr_number",
        "ci_run_id",
        "ci_run_attempt",
        "release_run_number",
        "release_run_attempt",
    ):
        _positive(value[key], key)
    if not IMAGE_RE.fullmatch(value["image"] or "") or not HEAD_RE.fullmatch(
        value["migration_head"] or ""
    ):
        raise ContractError("Manifest image or migration head is invalid.")
    host = value["host_package"]
    if not isinstance(host, dict) or set(host) != {"sha256", "size", "files"}:
        raise ContractError("Host package fields do not match the closed schema.")
    if host["sha256"] != _digest(package) or host["size"] != len(package):
        raise ContractError("Host package identity does not match its bytes.")
    files = _tar_files(package, PACKAGE_FILES, MAX_PACKAGE)
    expected = [
        {"path": path, "sha256": _digest(files[path]), "mode": f"{mode:04o}"}
        for path, mode in PACKAGE_FILES.items()
    ]
    if host["files"] != expected:
        raise ContractError("Host package file identities are invalid.")
    return value


def verify_bundle(path: Path) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    """Verify one bounded release bundle without changing host state."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_BUNDLE + 1)
    if len(raw) > MAX_BUNDLE:
        raise ContractError("Release bundle exceeds its size limit.")
    outer = _tar_files(raw, {"host-package.tar": 0o600, "manifest.json": 0o600}, MAX_BUNDLE)
    manifest = _validate_manifest(_json(outer["manifest.json"]), outer["host-package.tar"])
    if outer["manifest.json"] != _canonical(manifest):
        raise ContractError("Manifest is not canonical JSON.")
    return (
        manifest,
        outer["manifest.json"],
        _tar_files(outer["host-package.tar"], PACKAGE_FILES, MAX_PACKAGE),
    )


def _tar(entries: dict[str, tuple[bytes, int]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in sorted(entries):
            raw, mode = entries[name]
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime, info.uid, info.gid = len(raw), mode, 0, 0, 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(raw))
    return output.getvalue()


def _git(source: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_blob(source: Path, commit: str, path: str) -> bytes:
    identity = f"{commit}:{path}"
    if _git(source, "cat-file", "-t", identity) != "blob":
        raise ContractError(f"Packaged path is not a regular Git blob: {path}")
    return subprocess.run(
        ["git", "-C", str(source), "show", identity], check=True, capture_output=True
    ).stdout


def build_bundle(source: Path, output: Path, evidence_path: Path, values: dict[str, Any]) -> None:
    """Build deterministic package bytes after checking reviewed-tree evidence."""
    evidence = _json(evidence_path.read_bytes())
    keys = {
        "repository",
        "event",
        "pr_number",
        "base_sha",
        "head_sha",
        "synthetic_merge_sha",
        "tree_sha",
        "workflow_ref",
        "run_id",
        "run_attempt",
    }
    if not isinstance(evidence, dict) or set(evidence) != keys:
        raise ContractError("Reviewed-tree evidence fields are invalid.")
    commit = _sha(values["commit_sha"], "commit_sha")
    pr_number = _positive(values["pr_number"], "pr_number")
    _positive(values["release_run_number"], "release_run_number")
    _positive(values["release_run_attempt"], "release_run_attempt")
    for key in ("base_sha", "head_sha", "synthetic_merge_sha", "tree_sha"):
        _sha(evidence[key], key)
    _positive(evidence["pr_number"], "evidence pr_number")
    _positive(evidence["run_id"], "evidence run_id")
    _positive(evidence["run_attempt"], "evidence run_attempt")
    workflow_ref = f"{REPOSITORY}/.github/workflows/ci.yml@refs/pull/{pr_number}/merge"
    parents = _git(source, "show", "-s", "--format=%P", commit).split()
    if (
        evidence["repository"] != REPOSITORY
        or evidence["event"] != "pull_request"
        or evidence["pr_number"] != pr_number
        or evidence["workflow_ref"] != workflow_ref
        or parents != [evidence["base_sha"], evidence["head_sha"]]
        or _git(source, "rev-parse", f"{commit}^{{tree}}") != evidence["tree_sha"]
        or _git(source, "rev-parse", "HEAD") != commit
    ):
        raise ContractError("Reviewed-tree evidence does not match the release commit.")
    package_entries = {}
    for path, mode in PACKAGE_FILES.items():
        source_path = source / path
        status = source_path.lstat()
        raw = _git_blob(source, commit, path)
        if (
            stat.S_ISLNK(status.st_mode)
            or not stat.S_ISREG(status.st_mode)
            or source_path.read_bytes() != raw
        ):
            raise ContractError(f"Packaged path differs from the reviewed commit: {path}")
        package_entries[path] = (raw, mode)
    package = _tar(package_entries)
    manifest = {
        "contract_version": VERSION,
        "repository": REPOSITORY,
        "commit_sha": commit,
        "tree_sha": evidence["tree_sha"],
        "pr_number": evidence["pr_number"],
        "ci_run_id": evidence["run_id"],
        "ci_run_attempt": evidence["run_attempt"],
        "release_run_number": values["release_run_number"],
        "release_run_attempt": values["release_run_attempt"],
        "image": values["image"],
        "migration_head": values["migration_head"],
        "host_package": {
            "sha256": _digest(package),
            "size": len(package),
            "files": [
                {"path": path, "sha256": _digest(raw), "mode": f"{mode:04o}"}
                for path, (raw, mode) in package_entries.items()
            ],
        },
    }
    _validate_manifest(manifest, package)
    output.write_bytes(
        _tar({"host-package.tar": (package, 0o600), "manifest.json": (_canonical(manifest), 0o600)})
    )


def _secure(path: Path, mode: int, *, directory: bool = False) -> None:
    status = path.lstat()
    correct_type = stat.S_ISDIR(status.st_mode) if directory else stat.S_ISREG(status.st_mode)
    if (
        stat.S_ISLNK(status.st_mode)
        or not correct_type
        or status.st_uid != 0
        or stat.S_IMODE(status.st_mode) != mode
    ):
        raise ContractError(f"Unsafe owner, type, or mode: {path}")


@contextlib.contextmanager
def _exclusive_lock(root: Path) -> Iterator[None]:
    releases = root / "shared" / "releases"
    _secure(releases, 0o700, directory=True)
    lock_path = releases / "operations.lock"
    lock_path.touch(mode=0o600, exist_ok=True)
    _secure(lock_path, 0o600)
    with lock_path.open("rb") as lock:
        if os.name != "posix":
            raise ContractError("Host activation requires POSIX flock.")
        import fcntl  # noqa: PLC0415 - unavailable on the non-POSIX test host

        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _state(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    if optional and not path.exists():
        return None
    _secure(path, 0o600)
    value = _json(path.read_bytes())
    if not isinstance(value, dict) or set(value) != {"status", "operation", "current", "previous"}:
        raise ContractError("Active state fields are invalid.")

    def ref(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and set(item) == {"manifest_sha256"}
            and DIGEST_RE.fullmatch(item["manifest_sha256"] or "") is not None
        )

    if not ref(value["current"]) or (value["previous"] is not None and not ref(value["previous"])):
        raise ContractError("Active state release identities are invalid.")
    operation = value["operation"]
    if value["status"] == "ready" and operation is None:
        return value
    if (
        value["status"] != "pending"
        or not isinstance(operation, dict)
        or set(operation) != {"kind", "target_manifest_sha256"}
        or operation["kind"] not in {"activate", "rollback", "cutover"}
        or operation["target_manifest_sha256"] != value["current"]["manifest_sha256"]
    ):
        raise ContractError("Active state status and operation are inconsistent.")
    return value


def _durable(path: Path, value: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".active.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            Path(name).unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _release(root: Path, digest: str) -> tuple[dict[str, Any], Path]:
    directory = root / "shared" / "releases" / digest
    _secure(directory, 0o700, directory=True)
    manifest_path = directory / "manifest.json"
    _secure(manifest_path, 0o600)
    raw = manifest_path.read_bytes()
    if _digest(raw) != digest:
        raise ContractError("Release directory does not match its manifest.")
    manifest = _json(raw)
    package_entries = {}
    for path, mode in PACKAGE_FILES.items():
        installed = directory / path
        _secure(installed, mode)
        package_entries[path] = (installed.read_bytes(), mode)
    package = _tar(package_entries)
    return _validate_manifest(manifest, package), directory


def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(argv, check=True, **kwargs)


def _compose(
    root: Path, directory: Path, manifest: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    env_file = root / "shared" / ".env"
    _secure(env_file, 0o600)
    env = os.environ.copy()
    env.update(
        COMMUNITY_BOT_IMAGE=manifest["image"],
        COMMUNITY_BOT_RELEASE=manifest["commit_sha"],
        COMMUNITY_BOT_ENV_FILE=str(env_file),
    )
    return [
        "docker",
        "compose",
        "--project-directory",
        str(directory),
        "--env-file",
        str(env_file),
        "-f",
        str(directory / "compose.production.yaml"),
    ], env


def _image_head(manifest: dict[str, Any]) -> str:
    try:
        inspected = json.loads(
            _run(
                ["docker", "image", "inspect", manifest["image"]],
                capture_output=True,
                text=True,
            ).stdout
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("Docker image inspect returned invalid JSON.") from exc
    if not isinstance(inspected, list) or len(inspected) != 1 or not isinstance(inspected[0], dict):
        raise ContractError("Docker image inspect must return exactly one image.")
    config = inspected[0].get("Config")
    labels = config.get("Labels", {}) if isinstance(config, dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    repo_digests = inspected[0].get("RepoDigests")
    repo_digests = repo_digests if isinstance(repo_digests, list) else []
    if (
        manifest["image"] not in repo_digests
        or labels.get("org.opencontainers.image.source")
        != "https://github.com/AlexOxytocin/community_bot"
        or labels.get("org.opencontainers.image.revision") != manifest["commit_sha"]
    ):
        raise ContractError("Local image identity does not match the manifest.")
    return _migration_output(
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                manifest["image"],
                "community-migration-head",
            ],
            capture_output=True,
            text=True,
        ).stdout,
        "Image migration head",
    )


def _preflight(
    root: Path, manifest: dict[str, Any], directory: Path, current: dict[str, Any] | None
) -> tuple[list[str], dict[str, str]]:
    image_head = _image_head(manifest)
    compose, env = _compose(root, directory, manifest)
    _run([*compose, "config", "--quiet"], env=env)
    live_head = _live_head(compose, env)
    current_head = (
        manifest["migration_head"]
        if current is None
        else _release(root, current["current"]["manifest_sha256"])[0]["migration_head"]
    )
    if (
        image_head != manifest["migration_head"]
        or current_head != manifest["migration_head"]
        or live_head != manifest["migration_head"]
    ):
        raise ContractError("Target, current, image, and live database migration heads must match.")
    return compose, env


def _live_head(compose: list[str], env: dict[str, str]) -> str:
    return _migration_output(
        _run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                (
                    'exec psql --username="$POSTGRES_USER" '
                    '--dbname="$POSTGRES_DB" --tuples-only --no-align '
                    "--command 'SELECT version_num FROM alembic_version ORDER BY version_num'"
                ),
            ],
            env=env,
            capture_output=True,
            text=True,
        ).stdout,
        "Live database migration head",
    )


def _cutover_preflight(
    root: Path,
    target_manifest: dict[str, Any],
    target_directory: Path,
    current_manifest: dict[str, Any],
) -> tuple[list[str], dict[str, str], str]:
    if (
        current_manifest["migration_head"] != CUTOVER_FROM_HEAD
        or target_manifest["migration_head"] != CUTOVER_TO_HEAD
    ):
        raise ContractError("Cutover supports only migration 0021 to 0022.")
    compose, env = _compose(root, target_directory, target_manifest)
    _run([*compose, "config", "--quiet"], env=env)
    image_head = _image_head(target_manifest)
    if image_head != CUTOVER_TO_HEAD:
        raise ContractError("Cutover target image migration head is invalid.")
    live_head = _live_head(compose, env)
    if live_head not in {CUTOVER_FROM_HEAD, CUTOVER_TO_HEAD}:
        raise ContractError("Cutover live database head is neither source nor target.")
    return compose, env, live_head


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _cutover_proof_path(root: Path, target_digest: str) -> Path:
    return root / "shared" / "releases" / f"cutover-{target_digest}.json"


def _cutover_backup_directory() -> Path:
    path = Path(os.environ.get("COMMUNITY_BOT_BACKUP_DIR", "/var/backups/community-bot"))
    _secure(path, 0o700, directory=True)
    return path.resolve(strict=True)


def _create_cutover_backup(
    backup_dir: Path,
    database: str,
    postgres_user: str,
    compose: list[str],
    environment: dict[str, str],
) -> Path:
    _secure(backup_dir, 0o700, directory=True)
    backup_dir = backup_dir.resolve(strict=True)
    descriptor, name = tempfile.mkstemp(prefix=".cutover-", suffix=".dump.part", dir=backup_dir)
    os.close(descriptor)
    temporary = Path(name)
    temporary.chmod(0o600)
    target = Path(str(temporary).removesuffix(".part"))
    try:
        with temporary.open("wb") as output:
            _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "--username",
                    postgres_user,
                    "--dbname",
                    database,
                    "--format",
                    "custom",
                    "--no-owner",
                    "--no-privileges",
                ],
                env=environment,
                stdout=output,
            )
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size == 0:
            raise ContractError("Cutover backup is empty.")
        temporary.replace(target)
        _fsync_directory(backup_dir)
        return target
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _verify_cutover_proof(
    path: Path, current_digest: str, target_digest: str, backup_dir: Path
) -> Path:
    _secure(backup_dir, 0o700, directory=True)
    _secure(path, 0o600)
    proof = _json(path.read_bytes())
    expected = {
        "contract_version",
        "from_head",
        "to_head",
        "current_manifest_sha256",
        "target_manifest_sha256",
        "backup_path",
        "backup_sha256",
    }
    if not isinstance(proof, dict) or set(proof) != expected:
        raise ContractError("Cutover proof fields are invalid.")
    if (
        proof["contract_version"] != CUTOVER_PROOF_VERSION
        or proof["from_head"] != CUTOVER_FROM_HEAD
        or proof["to_head"] != CUTOVER_TO_HEAD
        or proof["current_manifest_sha256"] != current_digest
        or proof["target_manifest_sha256"] != target_digest
        or DIGEST_RE.fullmatch(proof["backup_sha256"] or "") is None
        or not isinstance(proof["backup_path"], str)
    ):
        raise ContractError("Cutover proof identity is invalid.")
    backup = Path(proof["backup_path"])
    try:
        resolved_directory = backup_dir.resolve(strict=True)
        resolved_backup = backup.resolve(strict=True)
        resolved_backup.relative_to(resolved_directory)
    except (OSError, ValueError) as exc:
        raise ContractError("Cutover backup is outside the configured backup directory.") from exc
    _secure(resolved_backup, 0o600)
    if _file_digest(resolved_backup) != proof["backup_sha256"]:
        raise ContractError("Cutover backup digest does not match its proof.")
    return resolved_backup


def _create_cutover_proof(
    root: Path,
    current_manifest: dict[str, Any],
    current_directory: Path,
    current_digest: str,
    target_digest: str,
    *,
    backup_dir: Path,
) -> Path:
    env_file = root / "shared" / ".env"
    sys.path.insert(0, str(current_directory))
    try:
        try:
            runtime_module = importlib.import_module("ops._runtime")
            restore_module = importlib.import_module("ops.restore_drill")
        except (AttributeError, ImportError) as exc:
            raise ContractError("Cutover operations package cannot be loaded.") from exc
        expected_ops = (current_directory / "ops").resolve(strict=True)
        for module in (runtime_module, restore_module):
            if Path(module.__file__).resolve(strict=True).parent != expected_ops:
                raise ContractError(
                    "Cutover operations package is not the current release package."
                )
        try:
            values = runtime_module.require_env_values(
                runtime_module.read_dotenv(env_file), "POSTGRES_DB", "POSTGRES_USER"
            )
            compose = runtime_module.compose_command(current_directory, env_file)
            environment = runtime_module.operations_environment(
                env_file, current_manifest["image"], current_manifest["commit_sha"]
            )
            backup = _create_cutover_backup(
                backup_dir,
                values["POSTGRES_DB"],
                values["POSTGRES_USER"],
                compose,
                environment,
            )
            if (
                restore_module._restore_selected(  # noqa: SLF001 - exclusive cutover lock is held
                    backup,
                    current_directory,
                    env_file,
                    current_manifest["image"],
                    current_manifest["commit_sha"],
                )
                != 0
            ):
                raise ContractError("Cutover restore drill failed.")
        except runtime_module.OpsError as exc:
            raise ContractError(str(exc)) from exc
    finally:
        sys.path.remove(str(current_directory))
    proof_path = _cutover_proof_path(root, target_digest)
    _durable(
        proof_path,
        {
            "contract_version": CUTOVER_PROOF_VERSION,
            "from_head": CUTOVER_FROM_HEAD,
            "to_head": CUTOVER_TO_HEAD,
            "current_manifest_sha256": current_digest,
            "target_manifest_sha256": target_digest,
            "backup_path": str(backup),
            "backup_sha256": _file_digest(backup),
        },
    )
    return backup


def _migration_output(raw: Any, name: str) -> str:
    if not isinstance(raw, str):
        raise ContractError(f"{name} output is invalid.")
    value = raw.removesuffix("\n")
    if HEAD_RE.fullmatch(value) is None:
        raise ContractError(f"{name} output must be exactly one line.")
    return value


def _ready(compose: list[str], env: dict[str, str]) -> None:
    output = _run(
        [*compose, "ps", "--format", "json", "worker", "web"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    if {(row.get("Service"), row.get("State"), row.get("Health")) for row in rows} != {
        ("worker", "running", "healthy"),
        ("web", "running", "healthy"),
    }:
        raise ContractError("Worker and web are not ready.")


def _lifecycle(
    compose: list[str], env: dict[str, str], *, stop_old: tuple[list[str], dict[str, str]] | None
) -> None:
    if stop_old:
        _run([*stop_old[0], "stop", "web"], env=stop_old[1])
    for service in ("worker", "web"):
        _run([*compose, "up", "-d", "--no-deps", "--force-recreate", "--wait", service], env=env)
    _ready(compose, env)


def _install_release(
    releases: Path,
    target: Path,
    manifest_raw: bytes,
    files: dict[str, bytes],
) -> None:
    stage = Path(tempfile.mkdtemp(prefix=".release.", dir=releases))
    stage.chmod(0o700)
    try:
        for name, raw in {"manifest.json": manifest_raw, **files}.items():
            path = stage / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.parent != stage:
                path.parent.chmod(0o700)
            path.write_bytes(raw)
            path.chmod(0o600 if name == "manifest.json" else PACKAGE_FILES[name])
            with path.open("rb") as installed_file:
                os.fsync(installed_file.fileno())
        nested = {stage / PurePosixPath(name).parent for name in files}
        for directory in sorted(nested - {stage}, key=lambda item: len(item.parts), reverse=True):
            _fsync_directory(directory)
        _fsync_directory(stage)
        stage.replace(target)
        _fsync_directory(releases)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _ensure_initial_processes_absent(root: Path, target: Path, manifest: dict[str, Any]) -> None:
    compose, env = _compose(root, target, manifest)
    processes = _run(
        [*compose, "ps", "--quiet", "worker", "web"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout
    if processes != "":
        raise ContractError("Initial activation requires worker and web to be absent.")


def activate(bundle: Path, root: Path) -> None:
    """Stage and activate an owner-transferred bundle under the exclusive lock."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ContractError("Activation requires root.")
    _secure(bundle, 0o600)
    with _exclusive_lock(root):
        _manifest, manifest_raw, files = verify_bundle(bundle)
        digest = _digest(manifest_raw)
        releases = root / "shared" / "releases"
        target = releases / digest
        if not target.exists():
            _install_release(releases, target, manifest_raw, files)
        installed, target = _release(root, digest)
        state_path = releases / "active.json"
        state = _state(state_path, optional=True)
        if state is None and any(
            path.name != digest and not path.name.startswith(".") and path.is_dir()
            for path in releases.iterdir()
        ):
            raise ContractError("Initial activation requires an empty managed release set.")
        if (
            state
            and state["status"] == "pending"
            and state["operation"] != {"kind": "activate", "target_manifest_sha256": digest}
        ):
            raise ContractError("A different operation is pending.")
        current_manifest = _release(root, state["current"]["manifest_sha256"])[0] if state else None
        pair = (installed["release_run_number"], installed["release_run_attempt"])
        if state and state["status"] == "ready" and state["current"]["manifest_sha256"] != digest:
            if current_manifest is None:
                raise ContractError("Current release manifest is missing.")
            old_pair = (
                current_manifest["release_run_number"],
                current_manifest["release_run_attempt"],
            )
            if pair <= old_pair:
                raise ContractError("Activation is stale or conflicts with an existing run.")
        if state is None:
            _ensure_initial_processes_absent(root, target, installed)
        compose, env = _preflight(root, installed, target, state)
        if state and state["status"] == "ready" and state["current"]["manifest_sha256"] == digest:
            _ready(compose, env)
            return
        previous = (
            state["previous"]
            if state and state["status"] == "pending"
            else (state["current"] if state else None)
        )
        pending = {
            "status": "pending",
            "operation": {"kind": "activate", "target_manifest_sha256": digest},
            "current": {"manifest_sha256": digest},
            "previous": previous,
        }
        _durable(state_path, pending)
        old = (
            _compose(
                root,
                _release(root, previous["manifest_sha256"])[1],
                _release(root, previous["manifest_sha256"])[0],
            )
            if previous
            else None
        )
        _lifecycle(compose, env, stop_old=old)
        _durable(state_path, {**pending, "status": "ready", "operation": None})


def cutover_0021_to_0022(bundle: Path, root: Path) -> None:  # noqa: C901
    """Activate one exact forward schema cutover with backup and restore proof."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ContractError("Cutover requires root.")
    _secure(bundle, 0o600)
    with _exclusive_lock(root):
        _manifest, manifest_raw, files = verify_bundle(bundle)
        target_digest = _digest(manifest_raw)
        releases = root / "shared" / "releases"
        target_directory = releases / target_digest
        if not target_directory.exists():
            _install_release(releases, target_directory, manifest_raw, files)
        target_manifest, target_directory = _release(root, target_digest)
        state_path = releases / "active.json"
        state = _state(state_path)
        if state is None:
            raise ContractError("Cutover requires an existing ready source release.")
        if state["status"] == "ready" and state["current"]["manifest_sha256"] == target_digest:
            compose, env = _preflight(root, target_manifest, target_directory, state)
            if state["previous"] is None:
                raise ContractError("Completed cutover is missing its source release identity.")
            _verify_cutover_proof(
                _cutover_proof_path(root, target_digest),
                state["previous"]["manifest_sha256"],
                target_digest,
                _cutover_backup_directory(),
            )
            _ready(compose, env)
            return
        if state["status"] == "pending":
            if (
                state["operation"] != {"kind": "cutover", "target_manifest_sha256": target_digest}
                or state["previous"] is None
            ):
                raise ContractError("A different operation is pending.")
            source_ref = state["previous"]
        else:
            source_ref = state["current"]
        source_digest = source_ref["manifest_sha256"]
        source_manifest, source_directory = _release(root, source_digest)
        target_pair = (
            target_manifest["release_run_number"],
            target_manifest["release_run_attempt"],
        )
        source_pair = (
            source_manifest["release_run_number"],
            source_manifest["release_run_attempt"],
        )
        if target_pair <= source_pair:
            raise ContractError("Cutover target release is stale or conflicting.")
        compose, env, live_head = _cutover_preflight(
            root, target_manifest, target_directory, source_manifest
        )
        backup_dir = _cutover_backup_directory()
        pending = {
            "status": "pending",
            "operation": {"kind": "cutover", "target_manifest_sha256": target_digest},
            "current": {"manifest_sha256": target_digest},
            "previous": {"manifest_sha256": source_digest},
        }
        _durable(state_path, pending)
        source_compose, source_env = _compose(root, source_directory, source_manifest)
        _run([*source_compose, "stop", "web", "worker"], env=source_env)
        proof_path = _cutover_proof_path(root, target_digest)
        if live_head == CUTOVER_FROM_HEAD:
            _create_cutover_proof(
                root,
                source_manifest,
                source_directory,
                source_digest,
                target_digest,
                backup_dir=backup_dir,
            )
            _run([*compose, "run", "--rm", "--no-deps", "migrate"], env=env)
        else:
            _verify_cutover_proof(proof_path, source_digest, target_digest, backup_dir)
        if _live_head(compose, env) != CUTOVER_TO_HEAD:
            raise ContractError("Cutover did not reach the exact target migration head.")
        _lifecycle(compose, env, stop_old=None)
        _durable(state_path, {**pending, "status": "ready", "operation": None})


def rollback(root: Path) -> None:
    """Consume the single previous release and activate it without migrations."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ContractError("Rollback requires root.")
    with _exclusive_lock(root):
        path = root / "shared" / "releases" / "active.json"
        state = _state(path)
        if state is None:
            raise ContractError("Active state is missing.")
        pending = state["status"] == "pending"
        if pending:
            operation = state["operation"]
            if (
                operation is None
                or operation["kind"] != "rollback"
                or operation["target_manifest_sha256"] != state["current"]["manifest_sha256"]
                or state["previous"] is not None
            ):
                raise ContractError("A different operation is pending.")
            target_digest = state["current"]["manifest_sha256"]
        else:
            if state["previous"] is None:
                raise ContractError("No previous release is available.")
            target_digest = state["previous"]["manifest_sha256"]
        manifest, directory = _release(root, target_digest)
        if not pending:
            current_manifest = _release(root, state["current"]["manifest_sha256"])[0]
            if current_manifest["migration_head"] != manifest["migration_head"]:
                raise ContractError("Rollback cannot downgrade the database schema.")
        compose, env = _preflight(root, manifest, directory, state)
        next_state = {
            "status": "pending",
            "operation": {"kind": "rollback", "target_manifest_sha256": target_digest},
            "current": {"manifest_sha256": target_digest},
            "previous": None,
        }
        _durable(path, next_state)
        _lifecycle(
            compose,
            env,
            stop_old=(
                (compose, env)
                if pending
                else _compose(root, *_release(root, state["current"]["manifest_sha256"])[::-1])
            ),
        )
        _durable(path, {**next_state, "status": "ready", "operation": None})


def main(argv: Sequence[str] | None = None) -> int:
    """Run the small explicit release-contract CLI."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for flag in ("source", "output", "evidence", "commit-sha", "image", "migration-head"):
        build.add_argument(f"--{flag}", required=True)
    for flag in ("pr-number", "release-run-number", "release-run-attempt"):
        build.add_argument(f"--{flag}", required=True, type=int)
    verify = commands.add_parser("verify")
    verify.add_argument("bundle")
    activation = commands.add_parser("activate")
    activation.add_argument("bundle")
    activation.add_argument("--root", default="/opt/community-bot")
    cutover = commands.add_parser("cutover-0021-to-0022")
    cutover.add_argument("bundle")
    cutover.add_argument("--root", default="/opt/community-bot")
    reversal = commands.add_parser("rollback")
    reversal.add_argument("--root", default="/opt/community-bot")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_bundle(Path(args.source), Path(args.output), Path(args.evidence), vars(args))
        elif args.command == "verify":
            manifest, raw, _ = verify_bundle(Path(args.bundle))
            print(_digest(raw), manifest["image"])
        elif args.command == "activate":
            activate(Path(args.bundle), Path(args.root))
        elif args.command == "cutover-0021-to-0022":
            cutover_0021_to_0022(Path(args.bundle), Path(args.root))
        else:
            rollback(Path(args.root))
    except (ContractError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"release contract rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
