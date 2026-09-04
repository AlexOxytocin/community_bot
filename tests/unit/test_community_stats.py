from __future__ import annotations

import datetime
import re
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from community_bot.application.community_stats import (
    ACHIEVEMENT_CODES,
    BotAchievementValues,
    CommunityStatsService,
    CommunityStatsUnavailableError,
    StatsMemberIdentity,
    bot_achievement_progress,
)
from community_bot.application.identity import ActorContext
from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.infrastructure.community_stats import HttpCommunityStatsGateway


def test_bot_achievement_progress_uses_maximum_balance_and_published_tasks() -> None:
    progress = {
        item.code: item
        for item in bot_achievement_progress(
            BotAchievementValues(maximum_credit_balance=70, created_tasks=5)
        )
    }

    assert progress["wealth"].level == 3
    assert progress["wealth"].next_level_at == 100
    assert progress["manager"].level == 3
    assert progress["manager"].next_level_at == 10


def test_bot_achievement_progress_redacts_another_members_exact_balance() -> None:
    progress = {
        item.code: item
        for item in bot_achievement_progress(
            BotAchievementValues(maximum_credit_balance=85, created_tasks=5),
            reveal_wealth_current=False,
        )
    }

    assert progress["wealth"].level == 3
    assert progress["wealth"].current == 70
    assert progress["wealth"].next_level_at == 100


@pytest.mark.parametrize(
    "code",
    [
        "petrosyan",
        "sharp",
        "firefighter",
        "heartbreaker",
        "dialog",
        "wake_up",
        "bread_and_salt",
        "onboarder",
    ],
)
def test_new_stats_achievement_metrics_are_allowed_for_all_time(code: str) -> None:
    CommunityStatsService.validate_metric(
        f"achievement:{code}",
        period="all",
        topic_id=None,
    )
    with pytest.raises(ValueError, match="Unsupported Community Stats metric"):
        CommunityStatsService.validate_metric(
            f"achievement:{code}",
            period="week",
            topic_id=None,
        )
    with pytest.raises(ValueError, match="Unsupported Community Stats metric"):
        CommunityStatsService.validate_metric(
            f"achievement:{code}",
            period="all",
            topic_id=17,
        )


def test_selectable_ui_achievements_match_backend_leaderboard_contract() -> None:
    source = (Path(__file__).parents[2] / "src/community_bot/transport/static/app.js").read_text(
        encoding="utf-8"
    )
    catalog = source.split("const communityAchievementCatalog = [", 1)[1].split("\n];", 1)[0]
    definitions = re.findall(r'\{\s*code: "([^"]+)"(.*?)\n  \}', catalog, re.DOTALL)
    selectable = {code for code, fields in definitions if "record: true" not in fields}
    assert selectable == ACHIEVEMENT_CODES
    for code in selectable:
        CommunityStatsService.validate_metric(f"achievement:{code}", period="all", topic_id=None)
    for code in ("unknown", "star", "consilium"):
        with pytest.raises(ValueError, match="Unsupported Community Stats metric"):
            CommunityStatsService.validate_metric(
                f"achievement:{code}",
                period="all",
                topic_id=None,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["wake_up", "bread_and_salt", "onboarder"])
async def test_new_achievement_rankings_reach_stats_and_resolve_member(code: str) -> None:
    member_id = uuid4()
    uow = AsyncMock()
    uow.__aenter__.return_value = uow
    uow.get_member.return_value = Member(member_id, 42, MemberRole.MEMBER, MemberStatus.ACTIVE)
    uow.community_stats_member_identities.return_value = (
        StatsMemberIdentity(member_id, 42, "Участник"),
    )
    observed: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chats/-100200/leaderboard"
        observed.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "items": [{"telegram_user_id": 42, "value": 2, "rank": 1}],
                "tracking_started_at": "2026-08-28T00:00:00Z",
                "calculated_at": "2026-09-04T12:00:00Z",
            },
        )

    gateway = HttpCommunityStatsGateway(
        base_url="http://community-stats:8080",
        token="test-service-token",  # noqa: S106
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    service = CommunityStatsService(lambda: uow, gateway, -100_200)
    try:
        result = await service.leaderboard(
            actor=ActorContext(member_id, "telegram", datetime.datetime.now(datetime.UTC)),
            metric=f"achievement:{code}",
            period="all",
            topic_id=None,
            limit=30,
        )
    finally:
        await gateway.close()
    assert observed == [{"period": "all", "metric": f"achievement:{code}", "limit": "30"}]
    assert len(result.items) == 1
    assert result.items[0].member_id == member_id
    assert result.items[0].display_name == "Участник"
    assert result.items[0].value == 2
    uow.community_stats_member_identities.assert_awaited_once_with((42,))


@pytest.mark.asyncio
@pytest.mark.parametrize("message_url", [None, "https://t.me/c/1234567890/42"])
async def test_typed_stats_client_sends_service_auth_and_topic(message_url: str | None) -> None:
    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["query"] = dict(request.url.params)
        observed["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "tracking_started_at": "2026-08-28T00:00:00Z",
                "calculated_at": "2026-08-28T12:00:00Z",
                "summary": {
                    "messages": 4,
                    "reactions_given": 2,
                    "reactions_received": 3,
                },
                "series": [
                    {
                        "bucket_start": "2026-08-28",
                        "messages": 4,
                        "reactions_given": 2,
                        "reactions_received": 3,
                    }
                ],
                "reaction_breakdown": [
                    {
                        "reaction": {"type": "emoji", "emoji": "👍"},
                        "given": 2,
                        "received": 3,
                    }
                ],
                "achievements": [
                    {
                        "code": "speaker",
                        "level": 1,
                        "current": 10,
                        "next_level_at": 30,
                        "unlocked": True,
                        **({"message_url": message_url} if message_url else {}),
                    }
                ],
            },
        )

    gateway = HttpCommunityStatsGateway(
        base_url="http://community-stats:8080",
        token="private-service-token",  # noqa: S106
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        pulse = await gateway.pulse(
            chat_id=-100_200,
            user_id=42,
            period="week",
            topic_id=17,
        )
    finally:
        await gateway.close()

    assert observed == {
        "path": "/v1/chats/-100200/users/42/pulse",
        "query": {"period": "week", "topic_id": "17"},
        "authorization": "Bearer private-service-token",
    }
    assert pulse.series[0].bucket_start == datetime.date(2026, 8, 28)
    assert pulse.reaction_breakdown[0].reaction["emoji"] == "👍"
    assert pulse.achievements[0].message_url == message_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "Statistics unavailable"}),
        httpx.Response(200, json={"items": "invalid"}),
    ],
)
async def test_typed_stats_client_maps_remote_failures_to_unavailable(
    response: httpx.Response,
) -> None:
    gateway = HttpCommunityStatsGateway(
        base_url="http://community-stats:8080",
        token="private-service-token",  # noqa: S106
        timeout_seconds=1,
        transport=httpx.MockTransport(lambda _request: response),
    )
    try:
        with pytest.raises(CommunityStatsUnavailableError):
            await gateway.leaderboard(
                chat_id=-100_200,
                period="all",
                metric="messages",
                topic_id=None,
                limit=30,
            )
    finally:
        await gateway.close()
