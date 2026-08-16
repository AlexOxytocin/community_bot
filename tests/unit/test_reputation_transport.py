"""Presentation tests for reputation Telegram routes."""

# ruff: noqa: RUF001 - Russian expected output is intentional.

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
    MemberCatalogCursor,
    MemberCatalogPage,
    ReliabilityView,
    SafeProfile,
)
from community_bot.domain.reputation import ProfileUnavailableError
from community_bot.transport.telegram.reputation import (
    build_reputation_router,
    present_leaderboard,
    present_member_catalog,
    present_profile,
)
from tests.integration.test_navigation import CapturingSession

if TYPE_CHECKING:
    from community_bot.application.member_foundation import MemberFoundationService
    from community_bot.application.moderation import ModerationService
    from community_bot.application.reputation import ReputationService

_HIDDEN = "hidden"


def test_safe_profile_presentation_never_contains_raw_karma() -> None:
    """Participant profile output includes only anonymous aggregate values."""
    profile = SafeProfile(
        member_id=uuid4(),
        telegram_username="participant",
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


def test_member_catalog_presentation_compacts_rows_and_expands_one_profile() -> None:
    """Member catalog text shows only the selected profile details."""
    first = _safe_profile("Анна", "anna")
    second = _safe_profile("Иван", None)
    page = MemberCatalogPage((first, second), None)

    rendered = present_member_catalog(page, query="@Ann", expanded_member_id=first.member_id)

    assert "Поиск: ann" in rendered
    assert "@anna · Анна · ур.2 · карма +3 (4)" in rendered
    assert "Иван · ур.2" not in rendered
    assert "Город: Буэнос-Айрес" in rendered
    assert str(first.member_id) not in rendered


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


class _CatalogReputationService:
    def __init__(self) -> None:
        self.profile = _safe_profile("Анна", "anna")
        self.calls: list[dict[str, object]] = []

    async def members(self, **kwargs: object) -> MemberCatalogPage:
        self.calls.append(kwargs)
        if kwargs.get("query") == "ab":
            raise ValueError
        return MemberCatalogPage((self.profile,), None)


class _PagingCatalogReputationService:
    def __init__(self) -> None:
        self.first = _safe_profile("Анна", "anna")
        self.second = _safe_profile("Иван", "ivan")
        self.calls: list[dict[str, object]] = []

    async def members(self, **kwargs: object) -> MemberCatalogPage:
        self.calls.append(kwargs)
        if kwargs.get("cursor_member_id") == self.first.member_id:
            return MemberCatalogPage((self.second,), None)
        return MemberCatalogPage(
            (self.first,),
            MemberCatalogCursor("анна", self.first.member_id),
        )


class _AllowingModerationService:
    async def is_administrator(self, telegram_user_id: int) -> bool:
        del telegram_user_id
        return True


class _AllowingFoundationService:
    async def is_active_superadministrator(self, telegram_user_id: int) -> bool:
        del telegram_user_id
        return True


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
        message_update(91_001, f"/profile {target_id}"),
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


@pytest.mark.asyncio
async def test_members_command_renders_searchable_compact_catalog_and_expands_row() -> None:
    """The members route keeps the catalog in one editable message."""
    service = _CatalogReputationService()
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_reputation_router(
            cast("ReputationService", service),
            cast("ModerationService", _AllowingModerationService()),
            cast("MemberFoundationService", _AllowingFoundationService()),
        )
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'R' * 35}", session=capture)
    actor = User(id=9102, is_bot=False, first_name="Participant")

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

    def callback_update(update_id: int, data: str, text: str) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"member-catalog-{update_id}",
                from_user=actor,
                chat_instance="reputation",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text=text,
                ),
            ),
        )

    await dispatcher.feed_update(bot, message_update(92_001, "/members @Anna"))
    assert service.calls[0]["query"] == "@Anna"
    assert capture.texts[-1] == "Участники\nПоиск: anna"
    assert ("+ @anna · Анна · ур.2 · карма +3 (4)", "mc:o:0:0") in capture.inline_buttons
    assert "mc:o:0:0" in capture.callbacks
    assert "mc:s" in capture.callbacks

    await dispatcher.feed_update(bot, callback_update(92_002, "mc:o:0:0", capture.texts[-1]))
    assert "@anna · Анна · ур.2 · карма +3 (4)" in capture.texts[-1]
    assert "01 -" not in capture.texts[-1]
    assert ("- @anna · Анна · ур.2 · карма +3 (4)", "mc:x:0:0") in capture.inline_buttons
    assert f"member:profile:{service.profile.member_id.hex}" in capture.callbacks
    assert f"karma:begin:{service.profile.member_id.hex}" in capture.callbacks
    assert f"karma:raw:{service.profile.member_id.hex}" in capture.callbacks
    assert f"mod:restrict:{service.profile.member_id.hex}" in capture.callbacks
    assert f"member:role:administrator:{service.profile.member_id.hex}" in capture.callbacks

    await dispatcher.feed_update(bot, callback_update(92_002_1, "mc:x:0:0", capture.texts[-1]))
    assert capture.texts[-1] == "Участники\nПоиск: anna"

    capture.texts.clear()
    await dispatcher.feed_update(bot, message_update(92_003, "/members ab"))
    assert capture.texts == ["Для поиска нужно минимум 3 символа после @ и пробелов."]
    await bot.session.close()


@pytest.mark.asyncio
async def test_members_catalog_paginates_resets_and_prompts_for_search() -> None:
    """Member catalog callbacks keep pagination and search state compact."""
    service = _PagingCatalogReputationService()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_reputation_router(cast("ReputationService", service)))
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'R' * 35}", session=capture)
    actor = User(id=9103, is_bot=False, first_name="Participant")

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

    def callback_update(update_id: int, data: str, text: str) -> Update:
        return Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"member-catalog-extra-{update_id}",
                from_user=actor,
                chat_instance="reputation",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text=text,
                ),
            ),
        )

    await dispatcher.feed_update(bot, message_update(92_010, "/members ann"))
    first_text = capture.texts[-1]
    next_page = next(value for value in capture.callbacks if value.startswith("mc:p:"))
    assert "Поиск: ann" in first_text
    assert "mc:r" in capture.callbacks

    await dispatcher.feed_update(bot, callback_update(92_011, "mc:s", first_text))
    assert capture.callback_answers[-1].startswith("Для поиска напишите /members")

    await dispatcher.feed_update(bot, callback_update(92_012, next_page, first_text))
    assert service.calls[-1]["cursor_member_id"] == service.first.member_id
    assert service.calls[-1]["query"] == "ann"
    assert capture.texts[-1] == "Участники\nПоиск: ann"
    assert any(
        text == "+ @ivan · Иван · ур.2 · карма +3 (4)"
        and callback == f"mc:o:{service.first.member_id.hex}:0"
        for text, callback in capture.inline_buttons
    )

    await dispatcher.feed_update(bot, callback_update(92_013, "mc:r", capture.texts[-1]))
    assert service.calls[-1].get("query") is None
    assert capture.texts[-1] == "Участники"
    assert any(
        text == "+ @anna · Анна · ур.2 · карма +3 (4)" and callback == "mc:o:0:0"
        for text, callback in capture.inline_buttons
    )
    await bot.session.close()


def _safe_profile(display_name: str, telegram_username: str | None) -> SafeProfile:
    return SafeProfile(
        member_id=uuid4(),
        telegram_username=telegram_username,
        display_name=display_name,
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
