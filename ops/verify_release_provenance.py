#!/usr/bin/env python3
# ruff: noqa: S603, S607
"""Fail-closed proof that a main merge tree passed the pull-request CI."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import zipfile
from io import BytesIO

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_WORKFLOW_FILE = "ci.yml"
_ARTIFACT_NAME = "verified-merge-tree"


class ProvenanceError(RuntimeError):
    """Raised when the reviewed-tree proof is absent or ambiguous."""


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _gh_json(endpoint: str, *, paginate: bool = False) -> object:
    command = ["gh", "api"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(endpoint)
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _download_evidence(repository: str, artifact_id: int) -> dict[str, object]:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
        check=True,
        capture_output=True,
    )
    with zipfile.ZipFile(BytesIO(completed.stdout)) as archive:
        names = [name for name in archive.namelist() if name.endswith("provenance.json")]
        if names != ["provenance.json"]:
            message = "provenance artifact must contain one root provenance.json"
            raise ProvenanceError(message)
        payload: object = json.loads(archive.read(names[0]))
        if not isinstance(payload, dict):
            message = "provenance payload must be a JSON object"
            raise ProvenanceError(message)
        return payload


def _flatten_pages(payload: object, key: str | None = None) -> list[dict[str, object]]:
    pages = payload if isinstance(payload, list) else [payload]
    values: list[dict[str, object]] = []
    for page in pages:
        page_values = page
        if key is not None:
            page_values = page.get(key, []) if isinstance(page, dict) else []
        if isinstance(page_values, list):
            values.extend(item for item in page_values if isinstance(item, dict))
    return values


def _nested_mapping(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int):
        message = f"{field} must be an integer"
        raise ProvenanceError(message)
    return value


def _pull_matches(
    pull: dict[str, object],
    *,
    commit_sha: str,
    head_sha: str,
) -> bool:
    base = _nested_mapping(pull.get("base"))
    head = _nested_mapping(pull.get("head"))
    return (
        bool(pull.get("merged_at"))
        and pull.get("merge_commit_sha") == commit_sha
        and base is not None
        and base.get("ref") == "main"
        and head is not None
        and head.get("sha") == head_sha
    )


def _run_matches(run: dict[str, object], *, head_sha: str, pr_number: int) -> bool:
    pull_requests = run.get("pull_requests")
    return (
        run.get("conclusion") == "success"
        and run.get("head_sha") == head_sha
        and isinstance(pull_requests, list)
        and any(
            isinstance(item, dict) and item.get("number") == pr_number for item in pull_requests
        )
    )


def _evidence_matches(
    evidence: dict[str, object],
    expected: dict[str, object],
) -> bool:
    synthetic_merge_sha = evidence.get("synthetic_merge_sha")
    return (
        all(evidence.get(key) == value for key, value in expected.items())
        and isinstance(synthetic_merge_sha, str)
        and _HEX_40.fullmatch(synthetic_merge_sha) is not None
    )


def verify(repository: str, commit_sha: str) -> dict[str, object]:
    """Return the unique matching proof or fail without publishing an image."""
    if _HEX_40.fullmatch(commit_sha) is None:
        message = "release commit must be a full lowercase SHA"
        raise ProvenanceError(message)

    parents = _git("show", "-s", "--format=%P", commit_sha).split()
    if len(parents) != 2:  # noqa: PLR2004 - merge commits have exactly two parents here.
        message = "release commit must be a two-parent merge commit"
        raise ProvenanceError(message)
    base_sha, head_sha = parents
    tree_sha = _git("rev-parse", f"{commit_sha}^{{tree}}")

    pulls_payload = _gh_json(
        f"repos/{repository}/commits/{commit_sha}/pulls?per_page=100",
        paginate=True,
    )
    pulls = [
        pull
        for pull in _flatten_pages(pulls_payload)
        if _pull_matches(pull, commit_sha=commit_sha, head_sha=head_sha)
    ]
    if len(pulls) != 1:
        message = "release commit must map to exactly one merged pull request"
        raise ProvenanceError(message)
    pr_number = _required_int(pulls[0].get("number"), "pull request number")

    encoded_head = urllib.parse.quote(head_sha, safe="")
    runs_payload = _gh_json(
        f"repos/{repository}/actions/workflows/{_WORKFLOW_FILE}/runs"
        f"?event=pull_request&status=completed&head_sha={encoded_head}&per_page=100",
        paginate=True,
    )
    runs = [
        run
        for run in _flatten_pages(runs_payload, "workflow_runs")
        if _run_matches(run, head_sha=head_sha, pr_number=pr_number)
    ]

    matches: list[dict[str, object]] = []
    for run in runs:
        artifacts_payload = _gh_json(
            f"repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100",
            paginate=True,
        )
        artifacts = [
            artifact
            for artifact in _flatten_pages(artifacts_payload, "artifacts")
            if artifact.get("name") == _ARTIFACT_NAME and artifact.get("expired") is False
        ]
        if len(artifacts) != 1:
            continue
        artifact_id = _required_int(artifacts[0].get("id"), "artifact id")
        evidence = _download_evidence(repository, artifact_id)
        expected = {
            "repository": repository,
            "event": "pull_request",
            "pr_number": pr_number,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "tree_sha": tree_sha,
            "workflow_ref": (
                f"{repository}/.github/workflows/{_WORKFLOW_FILE}@refs/pull/{pr_number}/merge"
            ),
            "run_id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
        }
        if _evidence_matches(evidence, expected):
            matches.append(evidence)

    if len(matches) != 1:
        message = "expected exactly one current, unambiguous CI provenance proof"
        raise ProvenanceError(message)
    return matches[0]


def main() -> int:
    """Verify provenance using GitHub Actions environment defaults."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA"))
    arguments = parser.parse_args()
    if not arguments.repository or not arguments.commit:
        parser.error("repository and commit are required")
    try:
        evidence = verify(arguments.repository, arguments.commit)
    except (ProvenanceError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"Release provenance rejected: {error}", file=sys.stderr)  # noqa: T201
        return 1
    print(  # noqa: T201
        json.dumps(
            {
                "pr_number": evidence["pr_number"],
                "run_id": evidence["run_id"],
                "tree_sha": evidence["tree_sha"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
