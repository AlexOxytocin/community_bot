from __future__ import annotations

from community_bot.application.cities import canonical_task_city, search_task_cities


def test_city_labels_use_commas_and_are_canonical() -> None:
    """The text presented by the picker is also accepted by offline task validation."""
    items = search_task_cities("Moscow", limit=8)

    assert items
    selected = items[0]
    assert " — " not in selected
    assert ", " in selected
    assert canonical_task_city(selected) == selected
