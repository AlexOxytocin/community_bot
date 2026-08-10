"""Assignment policy product-configuration compatibility tests."""

from __future__ import annotations

from pathlib import Path

from community_bot.bootstrap.product_config import load_product_config_candidate


def test_legacy_v1_hash_is_stable_and_v2_contains_assignment_policy() -> None:
    """Version one keeps its canonical identity while version two adds the policy."""
    v1 = load_product_config_candidate(Path("config/product-config.v1.json"))
    v2 = load_product_config_candidate(Path("config/product-config.v2.json"))
    assert v1.content_hash == "c4b26a06a1436c887cfe738e704f99700ec17c58b7f3f820c9902ba27a19220f"
    assert "assignment_policy" not in v1.payload()
    assert v1.maximum_active_assignments == 3
    assert v2.payload()["assignment_policy"] == {"maximum_active_assignments": 3}
    assert v2.content_hash != v1.content_hash
