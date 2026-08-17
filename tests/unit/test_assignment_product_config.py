"""Assignment policy product-configuration compatibility tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from community_bot.bootstrap.product_config import (
    ProductConfigCandidateModel,
    load_product_config_candidate,
)


def test_legacy_v1_hash_is_stable_and_v2_contains_assignment_policy() -> None:
    """Version one keeps its canonical identity while version two adds the policy."""
    v1 = load_product_config_candidate(Path("config/product-config.v1.json"))
    v2 = load_product_config_candidate(Path("config/product-config.v2.json"))
    assert v1.content_hash == "c4b26a06a1436c887cfe738e704f99700ec17c58b7f3f820c9902ba27a19220f"
    assert "assignment_policy" not in v1.payload()
    assert v1.maximum_active_assignments == 3
    assert v2.payload()["assignment_policy"] == {"maximum_active_assignments": 3}
    assert v2.content_hash != v1.content_hash


def test_candidate_normalizes_blank_optional_text() -> None:
    payload = json.loads(Path("config/product-config.v2.json").read_text(encoding="utf-8"))
    payload["levels"][0]["description"] = "   "

    model = ProductConfigCandidateModel.model_validate(payload)

    assert model.levels[0].description is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("nonzero_first_level", "Level 1 must start"),
        ("missing_assignment_policy", "requires assignment_policy"),
    ],
)
def test_candidate_rejects_cross_field_contract_breaks(mutation: str, message: str) -> None:
    payload = json.loads(Path("config/product-config.v2.json").read_text(encoding="utf-8"))
    if mutation == "nonzero_first_level":
        payload["levels"][0]["experience_required"] = 1
    else:
        payload.pop("assignment_policy")

    with pytest.raises(ValueError, match=message):
        ProductConfigCandidateModel.model_validate(payload)
