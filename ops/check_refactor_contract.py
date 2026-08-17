"""Проверить измеримый контракт компактного рефакторинга."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

SCHEMA = "community_bot.capability_parity.v1"
PARITY_PATH = Path("tasks/CB-64/parity-map.json")
PASSING = "passing"
EXTERNAL = "planned_external"
ALLOWED_STATUSES = {"planned", PASSING, EXTERNAL}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Telegram bot token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
}


class ContractError(ValueError):
    """Контракт рефакторинга нарушен."""


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode() for item in result.stdout.split(b"\0") if item]


def _line_count(paths: list[Path]) -> int:
    return sum(len(path.read_text(encoding="utf-8").splitlines()) for path in paths)


def _is_under(path: Path, directory: str) -> bool:
    return path.parts[0] == directory


def measure(root: Path) -> dict[str, int]:
    """Измерить только tracked tree без generated artifacts."""
    tracked = _tracked_files(root)
    python = [path for path in tracked if path.suffix == ".py"]
    production = [
        path
        for path in python
        if _is_under(path.relative_to(root), "src") or path.parent == root / "ops"
    ]
    tests = [path for path in python if _is_under(path.relative_to(root), "tests")]
    migrations = [path for path in python if _is_under(path.relative_to(root), "migrations")]
    docs = [
        path
        for path in tracked
        if path.suffix == ".md" and _is_under(path.relative_to(root), "docs")
    ]
    test_functions = 0
    for path in tests:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        test_functions += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "production_loc": _line_count(production),
        "tests_loc": _line_count(tests),
        "migration_loc": _line_count(migrations),
        "docs_loc": _line_count(docs),
        "test_functions": test_functions,
        "tables": len(_model_tables(root)),
        "dependencies": len(project["project"]["dependencies"]),
    }


def _model_tables(root: Path) -> set[str]:
    tables: set[str] = set()
    for path in (root / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            is_table = any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in node.targets
            )
            if (
                is_table
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                tables.add(node.value.value)
    return tables


def load_contract(root: Path) -> dict[str, Any]:
    """Загрузить parity map."""
    return json.loads((root / PARITY_PATH).read_text(encoding="utf-8"))


def _duplicate_ids(items: list[dict[str, Any]], key: str) -> set[str]:
    values = [str(item[key]) for item in items]
    return {value for value in values if values.count(value) > 1}


def _evidence_path(reference: str) -> str:
    return reference.split("::", maxsplit=1)[0].split("#", maxsplit=1)[0]


def _node_exists(root: Path, node_id: str) -> bool:
    path_text, separator, function = node_id.partition("::")
    path = root / path_text
    if not separator or not path.is_file() or path.suffix != ".py":
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
        for node in ast.walk(tree)
    )


def _validate_ids(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    for label, items, key in (
        ("legacy table", contract.get("legacy_tables", []), "old"),
        ("capability", contract.get("capabilities", []), "id"),
        ("constraint", contract.get("target_constraints", []), "id"),
    ):
        duplicates = _duplicate_ids(items, key)
        if duplicates:
            errors.append(f"duplicate {label} IDs: {sorted(duplicates)}")
    return errors


def _validate_links(root: Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    table_ids = {item["old"] for item in contract["legacy_tables"]}
    capability_ids = {item["id"] for item in contract["capabilities"]}
    constraint_ids = {item["id"] for item in contract["target_constraints"]}
    links = contract.get("table_links", {})
    model_tables = _model_tables(root)
    if table_ids != model_tables:
        errors.append(
            f"legacy table map differs from models: missing={sorted(model_tables - table_ids)}, "
            f"extra={sorted(table_ids - model_tables)}"
        )
    if set(links) != table_ids:
        errors.append("table_links keys must equal legacy table IDs")
    for table, link in links.items():
        unknown_capabilities = set(link.get("capability_ids", [])) - capability_ids
        unknown_constraints = set(link.get("constraint_ids", [])) - constraint_ids
        if unknown_capabilities:
            errors.append(f"{table}: unknown capabilities {sorted(unknown_capabilities)}")
        if unknown_constraints:
            errors.append(f"{table}: unknown constraints {sorted(unknown_constraints)}")
    return errors


def _validate_capabilities(root: Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    capability_ids = {item["id"] for item in contract["capabilities"]}
    status_map = contract.get("capability_status", {})
    if set(status_map) != capability_ids:
        errors.append("capability_status keys must equal capability IDs")
        return errors
    for capability in contract["capabilities"]:
        capability_id = capability["id"]
        status = status_map.get(capability_id, {}).get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{capability_id}: invalid status {status!r}")
        if status == EXTERNAL and not status_map[capability_id].get("owner"):
            errors.append(f"{capability_id}: external owner is required")
        if status == PASSING and not _node_exists(root, capability["planned_test"]):
            errors.append(f"{capability_id}: passing node does not exist")
        missing_evidence = [
            reference
            for reference in capability.get("old_evidence", "").split("; ")
            if reference and not (root / _evidence_path(reference)).exists()
        ]
        errors.extend(
            f"{capability_id}: missing old evidence {reference}" for reference in missing_evidence
        )
    return errors


def _validate_deletions(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    table_ids = {item["old"] for item in contract["legacy_tables"]}
    links = contract["table_links"]
    status_map = contract["capability_status"]
    deleted = set(contract.get("deleted_legacy_tables", []))
    if not deleted <= table_ids:
        errors.append(f"unknown deleted legacy tables: {sorted(deleted - table_ids)}")
    for table in deleted:
        blocking = [
            capability_id
            for capability_id in links[table]["capability_ids"]
            if status_map[capability_id]["status"] != PASSING
        ]
        if blocking:
            errors.append(f"{table}: deleted before passing {sorted(blocking)}")
    return errors


def validate(root: Path, contract: dict[str, Any]) -> list[str]:
    """Вернуть все нарушения структуры и deletion gate."""
    return [
        *_validate_ids(contract),
        *_validate_links(root, contract),
        *_validate_capabilities(root, contract),
        *_validate_deletions(contract),
    ]


def _net_deletion(baseline: dict[str, int], current: dict[str, int]) -> int:
    keys = ("production_loc", "tests_loc", "migration_loc", "docs_loc")
    return sum(baseline[key] - current[key] for key in keys)


def enforce_final(root: Path, contract: dict[str, Any], current: dict[str, int]) -> list[str]:
    """Проверить финальные ceilings и backend statuses."""
    errors = validate(root, contract)
    status_map = contract["capability_status"]
    for capability_id, state in status_map.items():
        if state["status"] not in {PASSING, EXTERNAL}:
            errors.append(f"{capability_id}: final status is {state['status']}")
    ceilings = contract["metrics"]["ceilings"]
    for key in ("production_loc", "tests_loc", "test_functions", "tables", "dependencies"):
        if current[key] > ceilings[key]:
            errors.append(f"{key}: {current[key]} exceeds {ceilings[key]}")
    net_deletion = _net_deletion(contract["metrics"]["baseline"], current)
    if net_deletion < ceilings["net_deletion_min"]:
        errors.append(f"net_deletion: {net_deletion} below {ceilings['net_deletion_min']}")
    for capability in contract["capabilities"]:
        if status_map[capability["id"]]["status"] == PASSING:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-q",
                    capability["planned_test"],
                ],
                cwd=root,
                check=False,
                capture_output=True,
            )
            if result.returncode:
                errors.append(f"{capability['id']}: pytest cannot collect passing node")
    return errors


def scan_secrets(root: Path) -> list[str]:
    """Найти только сигнатуры реальных ключей/токенов в tracked text."""
    errors: list[str] = []
    for path in _tracked_files(root):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{path.relative_to(root)}: possible {label}")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--enforce-final", action="store_true")
    parser.add_argument("--scope", choices=["backend"], default="backend")
    parser.add_argument("--scan-secrets", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Запустить contract gate."""
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    contract = load_contract(root)
    current = measure(root)
    errors = validate(root, contract)
    if args.enforce_final:
        errors = enforce_final(root, contract, current)
    if args.scan_secrets:
        errors.extend(scan_secrets(root))
    if args.report:
        baseline = contract["metrics"]["baseline"]
        print(
            json.dumps(
                {
                    "baseline": baseline,
                    "current": current,
                    "delta": {key: current[key] - baseline[key] for key in baseline},
                    "net_deletion": _net_deletion(baseline, current),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    if errors:
        raise ContractError("\n".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
