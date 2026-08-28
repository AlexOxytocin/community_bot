from __future__ import annotations

import datetime

import httpx
import pytest

from community_bot.application.community_stats import CommunityStatsUnavailableError
from community_bot.infrastructure.community_stats import HttpCommunityStatsGateway


@pytest.mark.asyncio
async def test_typed_stats_client_sends_service_auth_and_topic() -> None:
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
                        "next_level_at": 50,
                        "unlocked": True,
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
