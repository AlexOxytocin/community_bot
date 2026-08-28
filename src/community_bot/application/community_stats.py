"""Authorized Community Stats reads for the Mini App."""

# ruff: noqa: D101, D102, D105, D107

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, Self

from community_bot.domain.members import MemberStatus
from community_bot.domain.reputation import ProfileUnavailableError, require_profile_visible

if TYPE_CHECKING:
    from uuid import UUID

    from community_bot.application.identity import ActorContext
    from community_bot.domain.members import Member

StatsPeriod = Literal["week", "month", "year", "all"]
StatsActivityMetric = Literal["messages", "reactions_given", "reactions_received"]
BotLeaderboardMetric = Literal["experience", "karma"]
StatsLeaderboardMetric = str

ACHIEVEMENT_CODES = frozenset({"speaker", "magnet", "support", "regular", "explorer", "streak"})


class CommunityStatsUnavailableError(RuntimeError):
    """The private Stats service could not provide a trustworthy response."""


@dataclass(frozen=True, slots=True)
class ActivityValues:
    messages: int
    reactions_given: int
    reactions_received: int


@dataclass(frozen=True, slots=True)
class ActivityBucket(ActivityValues):
    bucket_start: datetime.date


@dataclass(frozen=True, slots=True)
class ReactionBreakdown:
    reaction: dict[str, object]
    given: int
    received: int


@dataclass(frozen=True, slots=True)
class AchievementProgress:
    code: str
    level: int
    current: int
    next_level_at: int | None
    unlocked: bool


@dataclass(frozen=True, slots=True)
class Pulse:
    tracking_started_at: datetime.datetime
    calculated_at: datetime.datetime
    summary: ActivityValues
    series: tuple[ActivityBucket, ...]
    reaction_breakdown: tuple[ReactionBreakdown, ...]
    achievements: tuple[AchievementProgress, ...]


@dataclass(frozen=True, slots=True)
class StatsLeaderboardItem:
    telegram_user_id: int
    value: int
    rank: int


@dataclass(frozen=True, slots=True)
class StatsLeaderboard:
    items: tuple[StatsLeaderboardItem, ...]
    tracking_started_at: datetime.datetime
    calculated_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class StatsMemberIdentity:
    member_id: UUID
    telegram_user_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class BotLeaderboardItem:
    member_id: UUID
    display_name: str
    value: int
    rank: int


@dataclass(frozen=True, slots=True)
class EnrichedLeaderboardItem:
    member_id: UUID
    display_name: str
    value: int
    rank: int


@dataclass(frozen=True, slots=True)
class EnrichedLeaderboard:
    items: tuple[EnrichedLeaderboardItem, ...]
    tracking_started_at: datetime.datetime | None
    calculated_at: datetime.datetime


class CommunityStatsGateway(Protocol):
    async def pulse(
        self,
        *,
        chat_id: int,
        user_id: int,
        period: StatsPeriod,
        topic_id: int | None,
    ) -> Pulse: ...

    async def leaderboard(
        self,
        *,
        chat_id: int,
        period: StatsPeriod,
        metric: StatsLeaderboardMetric,
        topic_id: int | None,
        limit: int,
    ) -> StatsLeaderboard: ...

    async def close(self) -> None: ...


class CommunityStatsUnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *args: object) -> None: ...
    async def get_member(self, member_id: UUID) -> Member | None: ...
    async def community_stats_member_identities(
        self, telegram_user_ids: tuple[int, ...]
    ) -> tuple[StatsMemberIdentity, ...]: ...
    async def community_bot_leaderboard(
        self, *, metric: BotLeaderboardMetric, limit: int
    ) -> tuple[BotLeaderboardItem, ...]: ...


class CommunityStatsService:
    """Authorize one community, call Stats, and enrich numeric rows in batches."""

    def __init__(self, unit_of_work_factory, gateway: CommunityStatsGateway, chat_id: int) -> None:  # noqa: ANN001
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._chat_id = chat_id

    async def pulse(
        self,
        *,
        actor: ActorContext,
        target_member_id: UUID,
        period: StatsPeriod,
        topic_id: int | None,
    ) -> Pulse:
        """Resolve the visible target before sending its Telegram ID to Stats."""
        async with self._unit_of_work_factory() as uow:
            member = await uow.get_member(actor.member_id)
            if member is None or member.status is not MemberStatus.ACTIVE:
                message = "Profile unavailable."
                raise ProfileUnavailableError(message)
            target = require_profile_visible(member, await uow.get_member(target_member_id))
            target_user_id = target.telegram_user_id
        return await self._gateway.pulse(
            chat_id=self._chat_id,
            user_id=target_user_id,
            period=period,
            topic_id=topic_id,
        )

    async def leaderboard(
        self,
        *,
        actor: ActorContext,
        period: StatsPeriod,
        metric: StatsLeaderboardMetric,
        topic_id: int | None,
        limit: int,
    ) -> EnrichedLeaderboard:
        """Return a profile-enriched ranking without one profile query per row."""
        self.validate_metric(metric, period=period, topic_id=topic_id)
        async with self._unit_of_work_factory() as uow:
            member = await uow.get_member(actor.member_id)
            if member is None or member.status is not MemberStatus.ACTIVE:
                message = "Profile unavailable."
                raise ProfileUnavailableError(message)
            if metric in {"experience", "karma"}:
                native = await uow.community_bot_leaderboard(metric=metric, limit=limit)
                return EnrichedLeaderboard(
                    items=tuple(
                        EnrichedLeaderboardItem(
                            item.member_id, item.display_name, item.value, item.rank
                        )
                        for item in native
                    ),
                    tracking_started_at=None,
                    calculated_at=datetime.datetime.now(datetime.UTC),
                )

        raw = await self._gateway.leaderboard(
            chat_id=self._chat_id,
            period=period,
            metric=metric,
            topic_id=topic_id,
            limit=limit,
        )
        user_ids = tuple(dict.fromkeys(item.telegram_user_id for item in raw.items))
        async with self._unit_of_work_factory() as uow:
            identities = await uow.community_stats_member_identities(user_ids)
        by_user_id = {item.telegram_user_id: item for item in identities}
        return EnrichedLeaderboard(
            items=tuple(
                EnrichedLeaderboardItem(
                    identity.member_id,
                    identity.display_name,
                    item.value,
                    item.rank,
                )
                for item in raw.items
                if (identity := by_user_id.get(item.telegram_user_id)) is not None
            ),
            tracking_started_at=raw.tracking_started_at,
            calculated_at=raw.calculated_at,
        )

    @staticmethod
    def validate_metric(metric: str, *, period: StatsPeriod, topic_id: int | None) -> None:
        """Accept only the versioned cross-project leaderboard vocabulary."""
        if metric in {"experience", "karma", "messages", "reactions_given", "reactions_received"}:
            return
        if metric.startswith("achievement:"):
            code = metric.removeprefix("achievement:")
            if code in ACHIEVEMENT_CODES and period == "all" and topic_id is None:
                return
        message = "Unsupported Community Stats metric."
        raise ValueError(message)
