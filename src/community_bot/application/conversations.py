"""Single durable owner for free-form Telegram text."""

# ruff: noqa: D102, D107, TC003

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from community_bot.domain.members import Member


@dataclass(frozen=True, slots=True)
class TextFlow:
    """Current text consumer selected for one member."""

    member_id: UUID
    flow_type: str
    step: str
    reference_id: UUID | None
    revision: int


class ConversationUnitOfWork(Protocol):  # pragma: no cover - structural typing contract.
    """Read boundary for the current durable text owner."""

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...
    async def get_text_flow(
        self, member_id: UUID, *, for_update: bool = False
    ) -> TextFlow | None: ...


class ConversationUnitOfWorkFactory(Protocol):  # pragma: no cover - structural typing contract.
    """Create one read transaction."""

    def __call__(self) -> AbstractAsyncContextManager[ConversationUnitOfWork]: ...


class ConversationService:
    """Resolve exactly one text owner before transport dispatch."""

    def __init__(self, unit_of_work_factory: ConversationUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def current(self, telegram_user_id: int) -> TextFlow | None:
        """Return the current owner, or no owner for an unknown member."""
        async with self._unit_of_work_factory() as uow:
            actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
            if actor is None:
                return None
            return await uow.get_text_flow(actor.id)
