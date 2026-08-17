"""Durable scope for quarantined synthetic test data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class TestRunScope:
    """Active test context attached to live actions of one participant."""

    id: UUID
    marker: str
