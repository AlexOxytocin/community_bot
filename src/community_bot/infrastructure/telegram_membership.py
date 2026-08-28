"""Telegram Bot API adapter for community membership checks."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramServerError,
)

from community_bot.application.membership import (
    InvalidMembershipResourceError,
    MembershipCheckUnavailableError,
    ResolvedTelegramResource,
)

_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


class AiogramTelegramMembershipChecker:
    """Check chat membership through one owned aiogram bot client."""

    def __init__(self, token: str) -> None:
        """Create an owned bot client without making a network request."""
        self._bot = Bot(token)

    async def is_member(self, *, chat_id: int, telegram_user_id: int) -> bool:
        """Return Telegram's current membership decision."""
        try:
            member = await self._bot.get_chat_member(chat_id=chat_id, user_id=telegram_user_id)
        except (TelegramNetworkError, TelegramServerError) as error:
            raise MembershipCheckUnavailableError from error
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            raise MembershipCheckUnavailableError from error
        if member.status in _MEMBER_STATUSES:
            return True
        return bool(
            member.status is ChatMemberStatus.RESTRICTED
            and getattr(member, "is_member", False)
        )

    async def resolve_chat(self, reference: str) -> ResolvedTelegramResource:
        """Resolve a chat and ensure this bot administers it."""
        normalized = reference.strip()
        if normalized.lstrip("-").isdigit():
            chat_reference: int | str = int(normalized)
        else:
            chat_reference = normalized if normalized.startswith("@") else f"@{normalized}"
        try:
            chat = await self._bot.get_chat(chat_reference)
            bot = await self._bot.get_me()
            bot_member = await self._bot.get_chat_member(chat.id, bot.id)
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            raise InvalidMembershipResourceError from error
        except (TelegramNetworkError, TelegramServerError) as error:
            raise MembershipCheckUnavailableError from error
        if bot_member.status not in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        }:
            raise InvalidMembershipResourceError
        title = (chat.title or "Telegram resource").strip()[:120]
        return ResolvedTelegramResource(
            telegram_chat_id=chat.id,
            telegram_username=chat.username,
            title=title,
        )

    async def close(self) -> None:
        """Close the owned aiogram client session."""
        await self._bot.session.close()
