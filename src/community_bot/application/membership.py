"""Telegram community membership contracts shared by web and infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MembershipCheckUnavailableError(RuntimeError):
    """Telegram could not confirm membership at this moment."""


class InvalidMembershipResourceError(ValueError):
    """A Telegram chat cannot be used as a membership requirement."""


@dataclass(frozen=True, slots=True)
class ResolvedTelegramResource:
    """Telegram chat identity verified by the bot before persistence."""

    telegram_chat_id: int
    telegram_username: str | None
    title: str


class TelegramMembershipChecker(Protocol):
    """Minimal Telegram API required by the membership gate."""

    async def is_member(self, *, chat_id: int, telegram_user_id: int) -> bool:
        """Return whether the user currently belongs to the chat."""
        ...

    async def resolve_chat(self, reference: str) -> ResolvedTelegramResource:
        """Resolve and validate a chat that the bot is able to inspect."""
        ...

    async def close(self) -> None:
        """Release the owned Telegram client session."""
        ...
