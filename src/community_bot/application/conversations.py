"""Current durable owner for free-form user input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class TextFlow:
    """Current text consumer selected for one member."""

    member_id: UUID
    flow_type: str
    step: str
    reference_id: UUID | None
    revision: int
