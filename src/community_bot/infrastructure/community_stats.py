"""Typed HTTP adapter for the private Community Stats read API."""

# ruff: noqa: D102, D107

from __future__ import annotations

import datetime  # noqa: TC003 - Pydantic resolves the runtime annotation.
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from community_bot.application.community_stats import (
    AchievementProgress,
    ActivityBucket,
    ActivityValues,
    CommunityStatsUnavailableError,
    Pulse,
    ReactionBreakdown,
    StatsLeaderboard,
    StatsLeaderboardItem,
    StatsLeaderboardMetric,
    StatsPeriod,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Activity(_Model):
    messages: int
    reactions_given: int
    reactions_received: int


class _Bucket(_Activity):
    bucket_start: datetime.date


class _Reaction(_Model):
    reaction: dict[str, Any]
    given: int
    received: int


class _Achievement(_Model):
    code: str
    level: int
    current: int
    next_level_at: int | None
    unlocked: bool


class _Pulse(_Model):
    tracking_started_at: datetime.datetime
    calculated_at: datetime.datetime
    summary: _Activity
    series: tuple[_Bucket, ...]
    reaction_breakdown: tuple[_Reaction, ...]
    achievements: tuple[_Achievement, ...]


class _LeaderboardItem(_Model):
    telegram_user_id: int
    value: int
    rank: int


class _Leaderboard(_Model):
    items: tuple[_LeaderboardItem, ...]
    tracking_started_at: datetime.datetime
    calculated_at: datetime.datetime


class HttpCommunityStatsGateway:
    """Call only the non-archive Stats API with one service credential."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def pulse(
        self,
        *,
        chat_id: int,
        user_id: int,
        period: StatsPeriod,
        topic_id: int | None,
    ) -> Pulse:
        payload = await self._get(
            f"v1/chats/{chat_id}/users/{user_id}/pulse",
            params=self._params(period=period, topic_id=topic_id),
        )
        try:
            model = _Pulse.model_validate(payload)
        except ValidationError as error:
            raise CommunityStatsUnavailableError from error
        return Pulse(
            tracking_started_at=model.tracking_started_at,
            calculated_at=model.calculated_at,
            summary=ActivityValues(**model.summary.model_dump()),
            series=tuple(ActivityBucket(**item.model_dump()) for item in model.series),
            reaction_breakdown=tuple(
                ReactionBreakdown(**item.model_dump()) for item in model.reaction_breakdown
            ),
            achievements=tuple(
                AchievementProgress(**item.model_dump()) for item in model.achievements
            ),
        )

    async def leaderboard(
        self,
        *,
        chat_id: int,
        period: StatsPeriod,
        metric: StatsLeaderboardMetric,
        topic_id: int | None,
        limit: int,
    ) -> StatsLeaderboard:
        params = self._params(period=period, topic_id=topic_id)
        params.update({"metric": metric, "limit": limit})
        payload = await self._get(f"v1/chats/{chat_id}/leaderboard", params=params)
        try:
            model = _Leaderboard.model_validate(payload)
        except ValidationError as error:
            raise CommunityStatsUnavailableError from error
        return StatsLeaderboard(
            items=tuple(StatsLeaderboardItem(**item.model_dump()) for item in model.items),
            tracking_started_at=model.tracking_started_at,
            calculated_at=model.calculated_at,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, params: dict[str, Any]) -> object:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as error:
            raise CommunityStatsUnavailableError from error
        if response.status_code != httpx.codes.OK:
            raise CommunityStatsUnavailableError
        try:
            return response.json()
        except ValueError as error:
            raise CommunityStatsUnavailableError from error

    @staticmethod
    def _params(*, period: StatsPeriod, topic_id: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {"period": period}
        if topic_id is not None:
            params["topic_id"] = topic_id
        return params
