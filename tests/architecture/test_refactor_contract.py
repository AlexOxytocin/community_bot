from __future__ import annotations

import copy
from pathlib import Path

from ops.check_refactor_contract import load_contract, measure, scan_secrets, validate

ROOT = Path(__file__).resolve().parents[2]


def test_repository_refactor_contract_is_complete_and_measurable() -> None:
    contract = load_contract(ROOT)

    assert validate(ROOT, contract) == []
    assert measure(ROOT)["tables"] == 43


def test_deleted_table_requires_every_linked_capability_to_pass() -> None:
    contract = copy.deepcopy(load_contract(ROOT))
    contract["deleted_legacy_tables"] = ["tasks"]

    errors = validate(ROOT, contract)

    assert any("tasks: deleted before passing" in error for error in errors)


def test_passing_status_requires_a_real_exact_test_node() -> None:
    contract = copy.deepcopy(load_contract(ROOT))
    contract["capability_status"]["REGISTRATION"]["status"] = "passing"

    errors = validate(ROOT, contract)

    assert "REGISTRATION: passing node does not exist" in errors


def test_versionable_tree_contains_no_real_secret_signature() -> None:
    assert scan_secrets(ROOT) == []
