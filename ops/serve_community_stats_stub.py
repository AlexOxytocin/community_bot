"""Serve realistic Community Stats responses for the loopback Mini App review."""

from __future__ import annotations

import argparse
import datetime
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

_PULSE_PATH = re.compile(r"^/v1/chats/-?\d+/users/\d+/pulse$")
_LEADERBOARD_PATH = re.compile(r"^/v1/chats/-?\d+/leaderboard$")


def _activity_series(period: str) -> list[dict[str, bool | int | str]]:
    today = datetime.datetime.now(datetime.UTC).date()
    tracking_started = datetime.date(2026, 8, 1)
    if period == "week":
        dates = [today - datetime.timedelta(days=offset) for offset in range(6, -1, -1)]
        messages = (4, 7, 5, 11, 8, 13, 10)
    elif period == "month":
        dates = [today - datetime.timedelta(days=offset) for offset in range(29, -1, -1)]
        messages = tuple(2 + (index * 7) % 13 for index in range(30))
    elif period in {"year", "all"}:
        dates = [
            (today.replace(day=1) - datetime.timedelta(days=32 * offset)).replace(day=1)
            for offset in range(11, -1, -1)
        ]
        messages = tuple(24 + (index * 17) % 61 for index in range(12))
    else:
        return []
    series: list[dict[str, int | str]] = []
    for bucket, message_count in zip(dates, messages, strict=True):
        value = 0 if period == "all" and bucket < tracking_started.replace(day=1) else message_count
        series.append(
            {
                "bucket_start": bucket.isoformat(),
                "tracked": True,
                "messages": value,
                "reactions_given": value // 2,
                "reactions_received": value // 3,
            }
        )
    return series


def _pulse(period: str) -> dict[str, object]:
    series = _activity_series(period)
    messages = sum(int(item["messages"]) for item in series) if series else 286
    reactions_given = sum(int(item["reactions_given"]) for item in series) if series else 143
    reactions_received = sum(int(item["reactions_received"]) for item in series) if series else 98
    return {
        "tracking_started_at": "2026-08-01T00:00:00Z",
        "calculated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "summary": {
            "messages": messages,
            "reactions_given": reactions_given,
            "reactions_received": reactions_received,
        },
        "series": series,
        "reaction_breakdown": [
            {"reaction": {"type": "emoji", "emoji": emoji}, "given": given, "received": received}
            for emoji, given, received in (
                ("👍", 22, 18),
                ("🔥", 17, 15),
                ("💗", 13, 11),
                ("👏", 11, 9),
                ("🎉", 9, 8),
                ("😁", 7, 6),
                ("🤝", 6, 5),
                ("⚡", 5, 4),
            )
        ],
        "achievements": [
            {"code": "speaker", "level": 1, "current": 58, "next_level_at": 100, "unlocked": True},
            {"code": "magnet", "level": 1, "current": 26, "next_level_at": 50, "unlocked": True},
            {"code": "petrosyan", "level": 1, "current": 8, "next_level_at": 15, "unlocked": True},
            {"code": "sharp", "level": 0, "current": 3, "next_level_at": 5, "unlocked": False},
            {
                "code": "firefighter",
                "level": 0,
                "current": 4,
                "next_level_at": 5,
                "unlocked": False,
            },
            {
                "code": "heartbreaker",
                "level": 1,
                "current": 6,
                "next_level_at": 15,
                "unlocked": True,
            },
            {"code": "support", "level": 0, "current": 6, "next_level_at": 10, "unlocked": False},
            {"code": "regular", "level": 0, "current": 2, "next_level_at": 3, "unlocked": False},
            {"code": "explorer", "level": 1, "current": 4, "next_level_at": 10, "unlocked": True},
            {"code": "streak", "level": 0, "current": 2, "next_level_at": 3, "unlocked": False},
            {"code": "dialog", "level": 0, "current": 9, "next_level_at": 10, "unlocked": False},
        ],
    }


class CommunityStatsStubHandler(BaseHTTPRequestHandler):
    """Return only the two private Stats read contracts used by the Mini App."""

    server_version = "CommunityStatsStub/1"

    def do_GET(self) -> None:
        """Serve one authorized local read without persisting request data."""
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) < 23:
            self._json(HTTPStatus.UNAUTHORIZED, {"code": "unauthorized"})
            return
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        period = query.get("period", ["week"])[0]
        if period not in {"week", "month", "year", "all"}:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"code": "invalid_period"})
            return
        if _PULSE_PATH.fullmatch(parsed.path):
            self._json(HTTPStatus.OK, _pulse(period))
            return
        if _LEADERBOARD_PATH.fullmatch(parsed.path):
            self._json(
                HTTPStatus.OK,
                {
                    "items": [],
                    "tracking_started_at": "2026-08-01T00:00:00Z",
                    "calculated_at": datetime.datetime.now(datetime.UTC).isoformat(),
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"code": "not_found"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress paths because they contain the local review Telegram ID."""
        del format, args

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """Bind the stub to loopback and serve until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), CommunityStatsStubHandler)
    print(f"Community Stats stub: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
