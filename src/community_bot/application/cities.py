"""Bounded offline city lookup for task creation."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

from geonamescache import GeonamesCache


class TaskCityError(ValueError):
    """The submitted task city is not an exact catalog selection."""


@lru_cache(maxsize=1)
def _catalog() -> tuple[GeonamesCache, dict[int, str]]:
    cache = GeonamesCache()
    cities = cache.get_cities()
    countries = cache.get_countries()
    bases = Counter((item["name"], item["countrycode"]) for item in cities.values())
    candidates: list[tuple[str, int, int]] = []
    for item in cities.values():
        country = countries[item["countrycode"]]["name"]
        region = f" · {item['admin1code']}" if bases[item["name"], item["countrycode"]] > 1 else ""
        candidates.append(
            (f"{item['name']} — {country}{region}", item["population"], item["geonameid"])
        )
    labels: dict[int, str] = {}
    seen: set[str] = set()
    for label, _population, geoname_id in sorted(
        candidates, key=lambda item: (item[0].casefold(), -item[1], item[2])
    ):
        if label in seen:
            continue
        seen.add(label)
        labels[geoname_id] = label
    return cache, labels


def search_task_cities(query: str, *, limit: int) -> tuple[str, ...]:
    """Search city names and library-provided alternate names deterministically."""
    normalized = " ".join(query.split()).casefold()
    if not normalized:
        return ()
    cache, labels = _catalog()
    found = {
        item["geonameid"]: item
        for attribute in ("name", "alternatenames")
        for item in cache.search_cities(normalized, attribute=attribute)
        if item["geonameid"] in labels
    }
    ordered = sorted(
        found.values(),
        key=lambda item: (
            0 if item["name"].casefold().startswith(normalized) else 1,
            -item["population"],
            labels[item["geonameid"]].casefold(),
        ),
    )
    return tuple(labels[item["geonameid"]] for item in ordered[:limit])


def canonical_task_city(value: str | None) -> str:
    """Return an exact library-owned display value or reject free text."""
    normalized = " ".join((value or "").split())
    if not normalized:
        raise TaskCityError
    _cache, labels = _catalog()
    canonical = next((label for label in labels.values() if label == normalized), None)
    if canonical is None:
        raise TaskCityError
    return canonical
