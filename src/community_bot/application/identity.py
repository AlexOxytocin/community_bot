"""Transport-neutral authenticated actor identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Server-issued identity without mutable authorization claims."""

    member_id: UUID
    provider: Literal["telegram"]
    authenticated_at: datetime.datetime
