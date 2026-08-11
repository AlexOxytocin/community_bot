"""Presentation tests for reputation Telegram routes."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.application.reputation import (
    KarmaAggregate,
    LeaderboardEntry,
    LeaderboardPage,
    ReliabilityView,
    SafeProfile,
)
from community_bot.domain.reputation import ProfileUnavailableError
from community_bot.transport.telegram.reputation import (
    build_reputation_router,
    present_leaderboard,
    present_profile,
)
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from community_bot.application.reputation import ReputationService

_HIDDEN = "hidden"


def test_safe_profile_presentation_never_contains_raw_karma() -> None:
    """Participant profile output includes only anonymous aggregate values."""
    profile = SafeProfile(
        member_id=uuid4(),
        display_name="Участник",
        city="Буэнос-Айрес",
        short_bio="Помогаю проектам",
        current_goal="Развивать сообщество",
        help_categories=("Тексты",),
        skill_tags=("Редактура",),
        availability="Вечером",
        experience_total=12,
        level_number=2,
        karma=KarmaAggregate(3, 4),
        reliability=ReliabilityView(5, Decimal("4.5"), 0, Decimal("0.9")),
    )
    rendered = present_profile(profile)
    assert "Карма: 3 (4 оценок)" in rendered
    assert "rater" not in rendered.lower()
    assert "comment" not in rendered.lower()


def test_leaderboard_presentation_uses_experience_only() -> None:
    """Main leaderboard text does not expose credits or karma."""
    now = datetime.datetime.now(datetime.UTC)
    page = LeaderboardPage(
        (
            LeaderboardEntry(1, uuid4(), "Первый", 20, 2, None, 0, now),
            LeaderboardEntry(2, uuid4(), "Второй", 10, 1, Decimal(1), 0, now),
        ),
        None,
    )
    rendered = present_leaderboard(page)
    assert "20 опыта" in rendered
    assert "кредит" not in rendered.lower()
    assert "карм" not in rendered.lower()


class _FailingReputationService:
    async def profile(self, **kwargs: object) -> None:
        del kwargs
        raise ProfileUnavailableError(_HIDDEN)

    async def statistics(self, *args: object) -> None:
        del args
        raise ProfileUnavailableError(_HIDDEN)

    async def members(self, **kwargs: object) -> None:
        del kwargs
        raise ProfileUnavailableError(_HIDDEN)

    async def leaderboard(self, **kwargs: object) -> None:
        del kwargs
        raise ProfileUnavailableError(_HIDDEN)

    async def begin_vote(self, **kwargs: object) -> None:
        del kwargs
        raise PermissionError

    async def save_value(self, **kwargs: object) -> None:
        del kwargs
        raise ValueError

    async def save_comment(self, **kwargs: object) -> None:
        del kwargs
        raise ValueError

    async def confirm_vote(self, **kwargs: object) -> None:
        del kwargs
        raise ValueError

    async def cancel_vote(self, **kwargs: object) -> bool:
        del kwargs
        return False


@pytest.mark.asyncio
async def test_reputation_router_safely_handles_all_synthetic_updates() -> None:
    """All profile and karma routes reject unavailable or stale input safely."""
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_reputation_router(cast("ReputationService", _FailingReputationService()))
    )
    fallback = Router(name="fallback-cancel")

    async def cancel_other_flow(message: Message) -> None:
        await message.answer("Другой диалог отменён.")

    fallback.message.register(cancel_other_flow, Command("cancel"))
    dispatcher.include_router(fallback)
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'R' * 35}", session=capture)
    actor = User(id=9101, is_bot=False, first_name="Participant")
    target_id = uuid4()

    def message_update(update_id: int, text: str) -> Update:
        return Update(
            update_id=update_id,
            message=Message(
                message_id=update_id,
                date=datetime.datetime.now(datetime.UTC),
                chat=Chat(id=actor.id, type="private"),
                from_user=actor,
                text=text,
            ),
        )

    def callback_update(update_id: int, data: str) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"karma-{update_id}",
                from_user=actor,
                chat_instance="reputation",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text="karma",
                ),
            ),
        )

    updates = [
        message_update(91_001, "/profile"),
        message_update(91_002, "/stats"),
        message_update(91_003, "/members"),
        message_update(91_004, "/leaderboard"),
        message_update(91_005, f"/karma {target_id}"),
        callback_update(91_006, "karma:value:1:1"),
        message_update(91_007, "/karma_comment 1 a sufficiently long comment"),
        callback_update(91_008, "karma:confirm:1"),
        message_update(91_009, "/cancel"),
    ]
    for update in updates:
        await dispatcher.feed_update(bot, update)

    assert len(capture.texts) == 9
    assert capture.texts[-1] == "Другой диалог отменён."
    await bot.session.close()
