"""Unit coverage for fail-closed release provenance selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


def _load_module() -> ModuleType:
    path = Path(__file__).parents[2] / "ops" / "verify_release_provenance.py"
    spec = importlib.util.spec_from_file_location("verify_release_provenance", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixtures() -> tuple[str, str, str, str, dict[str, object]]:
    repository = "alexgoodman53/community_bot"
    commit = "c" * 40
    base = "a" * 40
    head = "b" * 40
    evidence = {
        "repository": repository,
        "event": "pull_request",
        "pr_number": 38,
        "base_sha": base,
        "head_sha": head,
        "synthetic_merge_sha": "d" * 40,
        "tree_sha": "e" * 40,
        "workflow_ref": ("alexgoodman53/community_bot/.github/workflows/ci.yml@refs/pull/38/merge"),
        "run_id": 101,
        "run_attempt": 1,
    }
    return repository, commit, base, head, evidence


def test_verify_accepts_one_exact_current_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    """One exact PR/run/artifact match proves the merged tree."""
    module = _load_module()
    repository, commit, base, head, evidence = _fixtures()

    monkeypatch.setattr(
        module,
        "_git",
        lambda *args: f"{base} {head}" if "--format=%P" in args else evidence["tree_sha"],
    )

    def fake_gh(endpoint: str, *, paginate: bool = False) -> object:
        assert paginate
        if "/commits/" in endpoint:
            return [
                [
                    {
                        "number": 38,
                        "merged_at": "2026-08-14T12:00:00Z",
                        "merge_commit_sha": commit,
                        "base": {"ref": "main"},
                        "head": {"sha": head},
                    }
                ]
            ]
        if "/runs?" in endpoint:
            return [
                {
                    "workflow_runs": [
                        {
                            "id": 101,
                            "run_attempt": 1,
                            "conclusion": "success",
                            "head_sha": head,
                            "pull_requests": [],
                        }
                    ]
                }
            ]
        return [{"artifacts": [{"id": 202, "name": "verified-merge-tree", "expired": False}]}]

    monkeypatch.setattr(module, "_gh_json", fake_gh)
    monkeypatch.setattr(module, "_download_evidence", lambda *_args: evidence)

    assert module.verify(repository, commit) == evidence


def test_verify_rejects_ambiguous_current_proofs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two matching successful runs are rejected instead of selecting one implicitly."""
    module = _load_module()
    repository, commit, base, head, evidence = _fixtures()
    monkeypatch.setattr(
        module,
        "_git",
        lambda *args: f"{base} {head}" if "--format=%P" in args else evidence["tree_sha"],
    )

    def fake_gh(endpoint: str, *, paginate: bool = False) -> object:
        assert paginate
        if "/commits/" in endpoint:
            return [
                [
                    {
                        "number": 38,
                        "merged_at": "2026-08-14T12:00:00Z",
                        "merge_commit_sha": commit,
                        "base": {"ref": "main"},
                        "head": {"sha": head},
                    }
                ]
            ]
        if "/runs?" in endpoint:
            runs = [
                {
                    "id": run_id,
                    "run_attempt": 1,
                    "conclusion": "success",
                    "head_sha": head,
                    "pull_requests": [],
                }
                for run_id in (101, 102)
            ]
            return [{"workflow_runs": runs}]
        run_id = 101 if "/101/" in endpoint else 102
        return [{"artifacts": [{"id": run_id, "name": "verified-merge-tree", "expired": False}]}]

    monkeypatch.setattr(module, "_gh_json", fake_gh)
    monkeypatch.setattr(
        module,
        "_download_evidence",
        lambda _repository, artifact_id: evidence | {"run_id": artifact_id},
    )

    with pytest.raises(module.ProvenanceError, match="exactly one"):
        module.verify(repository, commit)
