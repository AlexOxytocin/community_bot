from __future__ import annotations

from types import SimpleNamespace
from typing import BinaryIO
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter, TelegramUnauthorizedError
from aiogram.methods import GetChatMember

from community_bot.application.membership import MembershipCheckUnavailableError
from community_bot.infrastructure.telegram_membership import AiogramTelegramMembershipChecker


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [TelegramRetryAfter, TelegramUnauthorizedError])
async def test_membership_api_failures_remain_fail_closed(error_type: type) -> None:
    checker = object.__new__(AiogramTelegramMembershipChecker)
    bot = AsyncMock()
    error = error_type(
        method=GetChatMember(chat_id=-100123, user_id=42),
        message="unavailable",
        **({"retry_after": 10} if error_type is TelegramRetryAfter else {}),
    )
    bot.get_chat_member.side_effect = error
    checker._bot = bot  # noqa: SLF001
    with pytest.raises(MembershipCheckUnavailableError):
        await checker.is_member(chat_id=-100123, telegram_user_id=42)


@pytest.mark.asyncio
async def test_profile_photo_downloads_largest_available_size() -> None:
    checker = object.__new__(AiogramTelegramMembershipChecker)
    bot = AsyncMock()
    bot.get_user_profile_photos.return_value = SimpleNamespace(
        photos=[
            [
                SimpleNamespace(file_id="small", width=160, height=160),
                SimpleNamespace(file_id="large", width=640, height=640),
            ]
        ]
    )
    bot.get_file.return_value = SimpleNamespace(file_path="photos/avatar.jpg")

    async def download_file(_path: str, *, destination: BinaryIO, **_kwargs: object) -> None:
        destination.write(b"\xff\xd8\xffavatar\xff\xd9")

    bot.download_file.side_effect = download_file
    checker._bot = bot  # noqa: SLF001

    photo = await checker.profile_photo(123)

    assert photo is not None
    assert photo.content == b"\xff\xd8\xffavatar\xff\xd9"
    assert photo.content_type == "image/jpeg"
    bot.get_file.assert_awaited_once_with("large", request_timeout=10)
    bot.download_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_photo_returns_none_when_telegram_has_no_photo() -> None:
    checker = object.__new__(AiogramTelegramMembershipChecker)
    bot = AsyncMock()
    bot.get_user_profile_photos.return_value = SimpleNamespace(photos=[])
    checker._bot = bot  # noqa: SLF001

    assert await checker.profile_photo(123) is None
    bot.get_file.assert_not_called()
