from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage

from community_bot.bootstrap.telegram_menu_refresh import claim_receipt, deliver_menu

if TYPE_CHECKING:
    from pathlib import Path


def test_receipt_claim_is_exclusive_and_preserves_uncertain_attempt(tmp_path: Path) -> None:
    path = tmp_path / "member.receipt"
    assert claim_receipt(path)
    assert not claim_receipt(path)
    assert path.read_text() == "attempted"


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_refresh_preserves_preferences_and_never_resends(
    tmp_path: Path, *, apply: bool
) -> None:
    member_id = uuid4()
    store = AsyncMock()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status="active")
    store.preferences.return_value = {"tasks": True, "nomad": True, "revision": 1}
    bot, membership = AsyncMock(), AsyncMock()
    membership.is_member.return_value = True
    operation = partial(
        deliver_menu,
        bot=bot,
        store=store,
        membership=membership,
        chat_id=-100123,
        member_id=member_id,
        telegram_user_id=456,
        receipts=tmp_path,
        apply=apply,
    )
    assert await operation() == ("sent" if apply else "eligible")
    assert await operation() == ("already_attempted" if apply else "eligible")
    assert bot.send_message.await_count == int(apply)
    store.set_preference.assert_not_awaited()
    if apply:
        reply = bot.send_message.call_args.kwargs
        assert reply["disable_notification"] is True
        assert reply["reply_markup"].remove_keyboard is True
    else:
        assert not list(tmp_path.iterdir())  # noqa: ASYNC240 - tiny local test fixture.


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unreachable", "uncertain"])
async def test_refresh_failure_is_not_retried(tmp_path: Path, outcome: str) -> None:
    member_id = uuid4()
    store, bot, membership = AsyncMock(), AsyncMock(), AsyncMock()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status="active")
    store.preferences.return_value = {"nomad": False}
    membership.is_member.return_value = True
    exception = TelegramForbiddenError if outcome == "unreachable" else TelegramNetworkError
    bot.send_message.side_effect = exception(SendMessage(chat_id=456, text="test"), "test")
    operation = partial(
        deliver_menu,
        bot=bot,
        store=store,
        membership=membership,
        chat_id=-100123,
        member_id=member_id,
        telegram_user_id=456,
        receipts=tmp_path,
        apply=True,
    )
    assert await operation() == outcome
    assert await operation() == "already_attempted"
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["banned", "active"])
async def test_refresh_excludes_nonmembers(tmp_path: Path, status: str) -> None:
    member_id = uuid4()
    store, bot, membership = AsyncMock(), AsyncMock(), AsyncMock()
    store.member_for_telegram.return_value = SimpleNamespace(id=member_id, status=status)
    membership.is_member.return_value = False
    result = await deliver_menu(
        bot=bot,
        store=store,
        membership=membership,
        chat_id=-100123,
        member_id=member_id,
        telegram_user_id=456,
        receipts=tmp_path,
        apply=True,
    )
    assert result == ("ineligible" if status == "banned" else "not_in_chat")
    bot.send_message.assert_not_awaited()
    assert not list(tmp_path.iterdir())  # noqa: ASYNC240 - tiny local test fixture.
