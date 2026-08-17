"""Direct tests for transport-neutral durable free-form input ownership."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Self
from uuid import UUID, uuid4

import pytest

from community_bot.application.conversations import ConversationService, TextFlow
from community_bot.domain.members import Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    from types import TracebackType


class _UnitOfWork(AbstractAsyncContextManager["_UnitOfWork"]):
    def __init__(self, *, known: bool) -> None:
        self.member = Member(uuid4(), 42, MemberRole.MEMBER, MemberStatus.ACTIVE) if known else None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        del telegram_user_id
        return self.member

    async def get_text_flow(
        self,
        member_id: UUID,
        *,
        for_update: bool = False,
    ) -> TextFlow:
        del for_update
        assert self.member is not None
        assert member_id == self.member.id
        return TextFlow(self.member.id, "registration", "profile", None, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [False, True])
async def test_current_returns_only_the_durable_owner(known: bool) -> None:  # noqa: FBT001
    result = await ConversationService(lambda: _UnitOfWork(known=known)).current(42)

    assert (result is not None) is known
