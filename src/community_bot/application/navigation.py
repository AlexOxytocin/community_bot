"""Authorization helpers for the Telegram MVP navigation layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from community_bot.domain.members import MemberRole, MemberStatus

if TYPE_CHECKING:
    from uuid import UUID

    from community_bot.application.economy import EconomyUnitOfWorkFactory


class NavigationService:
    """Resolve navigation access without weakening downstream services."""

    def __init__(self, unit_of_work_factory: EconomyUnitOfWorkFactory) -> None:
        """Bind the shared read transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def require_active_administrator(self, telegram_user_id: int) -> UUID:
        """Return an exact active administrator or a state-independent denial."""
        async with self._unit_of_work_factory() as unit_of_work:
            actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            if (
                actor is None
                or actor.status is not MemberStatus.ACTIVE
                or actor.role is not MemberRole.ADMINISTRATOR
            ):
                message = "Navigation action is unavailable."
                raise PermissionError(message)
            return actor.id
