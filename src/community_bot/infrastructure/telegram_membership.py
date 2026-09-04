"""Telegram Bot API adapter for community membership checks."""

from __future__ import annotations

from io import BytesIO

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramServerError,
)

from community_bot.application.membership import (
    InvalidMembershipResourceError,
    MembershipCheckUnavailableError,
    ProfilePhotoUnavailableError,
    ResolvedTelegramResource,
    TelegramProfilePhoto,
)

_PROFILE_PHOTO_MAX_BYTES = 5 * 1024 * 1024
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
        except TelegramAPIError as error:
            raise MembershipCheckUnavailableError from error
        if member.status in _MEMBER_STATUSES:
            return True
        return bool(
            member.status is ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)
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

    async def profile_photo(self, telegram_user_id: int) -> TelegramProfilePhoto | None:
        """Download the best available static Telegram profile photo."""
        try:
            profile_photos = await self._bot.get_user_profile_photos(
                user_id=telegram_user_id,
                offset=0,
                limit=1,
                request_timeout=10,
            )
            if not profile_photos.photos:
                return None
            largest = max(
                profile_photos.photos[0],
                key=lambda item: item.width * item.height,
            )
            telegram_file = await self._bot.get_file(largest.file_id, request_timeout=10)
            if not telegram_file.file_path:
                return None
            destination = BytesIO()
            await self._bot.download_file(
                telegram_file.file_path,
                destination=destination,
                timeout=10,
            )
        except TelegramAPIError as error:
            raise ProfilePhotoUnavailableError from error
        content = destination.getvalue()
        if not content or len(content) > _PROFILE_PHOTO_MAX_BYTES:
            raise ProfilePhotoUnavailableError
        return TelegramProfilePhoto(content=content)

    async def close(self) -> None:
        """Close the owned aiogram client session."""
        await self._bot.session.close()
