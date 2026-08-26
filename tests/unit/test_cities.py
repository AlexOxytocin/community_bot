"""Shared city catalog and timezone resolution."""

from __future__ import annotations

import pytest

from community_bot.application.cities import (
    TaskCityError,
    canonical_city_and_timezone,
    canonical_task_city,
    search_task_cities,
)


def test_catalog_city_exposes_canonical_label_and_iana_timezone() -> None:
    city, timezone = canonical_city_and_timezone("Buenos Aires — Argentina")

    assert city == "Buenos Aires — Argentina"
    assert timezone == "America/Argentina/Buenos_Aires"
    assert canonical_task_city(city) == city
    assert search_task_cities(city, limit=8) == (city,)


def test_catalog_city_rejects_free_text() -> None:
    with pytest.raises(TaskCityError):
        canonical_city_and_timezone("Buenos Aires")
