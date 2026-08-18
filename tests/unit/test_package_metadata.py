"""Package metadata consistency tests."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import community_bot


def test_package_metadata_is_consistently_1_0_0() -> None:
    """Source, installed distribution, project, and lock stay aligned."""
    root = Path(__file__).parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked_project = next(
        package for package in lock["package"] if package["name"] == "community-bot"
    )

    assert project["project"]["version"] == "1.0.0"
    assert locked_project["version"] == "1.0.0"
    assert community_bot.__version__ == "1.0.0"
    assert importlib.metadata.version("community-bot") == "1.0.0"
    assert set(project["project"]["scripts"]) == {
        "community-bootstrap-admin",
        "community-repair-bootstrap-admin-profile",
        "community-bootstrap-product-config",
        "community-health",
        "community-migrate",
        "community-migration-head",
        "community-web",
        "community-worker",
    }
