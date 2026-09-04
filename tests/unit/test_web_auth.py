from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import inspect
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.exc import SQLAlchemyError

from community_bot.application.reputation import ProfileUnavailableError
from community_bot.application.tasks import TaskService
from community_bot.bootstrap.settings import Settings
from community_bot.domain.assignments import AssignmentError, SubmissionDraft
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.tasks import TaskError, TaskKind, TaskStatus, TaskTimeSize
from community_bot.transport.web import (
    ConfirmSubmissionDraftRequest,
    SaveSubmissionDraftRequest,
    TaskFormRequest,
    TelegramIdentity,
    _accept_update_id,
    _assignment_cursor,
    _member_query,
    _parse_assignment_cursor,
    _session_digest,
    _submission_draft_dto,
    _submission_fingerprint,
    _submission_update_id,
    _task_dto,
    create_web_app,
    validate_telegram_init_data,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.routing import Route

    from community_bot.application.tasks import PublishedTask
    from community_bot.infrastructure.db.database import Database

BOT_TOKEN = "123456:TEST_TOKEN"
ORIGIN = "https://mini.example"
AUTH_HEADERS = {"content-type": "text/plain; charset=utf-8", "origin": ORIGIN}
SESSION_TOKEN = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode()
FROZEN_PROOF = (
    b"auth_date=1700000000&query_id=AAEAAAE&"
    b"user=%7B%22id%22%3A123456789%2C%22first_name%22%3A%22Alex%22%7D&"
    b"hash=de4a79281687d51b801120377156fa61e1bd12fead3672239ef71911193761a1"
)


class FakeDatabase:
    def __init__(self) -> None:
        self.member_id = uuid4()
        self.created_digest: bytes | None = None
        self.created_sessions: list[dict[str, object]] = []
        self.consumed_proofs: set[bytes] = set()
        self.fail_create = False
        self.resolve_member = False
        self.return_member = True
        self.disposed = False

    def unit_of_work(self) -> None:
        raise AssertionError("Read services are not used by auth tests.")

    async def create_web_session(self, **values: object) -> object:
        if self.fail_create:
            raise SQLAlchemyError
        proof_digest = values["proof_digest"]
        assert isinstance(proof_digest, bytes)
        if proof_digest in self.consumed_proofs:
            return None
        self.consumed_proofs.add(proof_digest)
        digest = values["token_digest"]
        assert isinstance(digest, bytes)
        self.created_digest = digest
        self.created_sessions.append(values)
        return self.member_id if self.return_member else None

    async def web_session_member_id(
        self, **_values: object
    ) -> tuple[object, datetime.datetime] | None:
        if self.resolve_member:
            return self.member_id, datetime.datetime.now(datetime.UTC)
        return None

    async def revoke_web_session(self, **_values: object) -> None:
        return None

    async def dispose(self) -> None:
        self.disposed = True


def _app(database: FakeDatabase) -> FastAPI:
    return create_web_app(
        settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=ORIGIN, _env_file=None),
        database=cast("Database", database),
    )


def _proof(user_id: int, *, now: datetime.datetime) -> bytes:
    return _signed_fields(
        {
            "auth_date": str(int(now.timestamp())),
            "query_id": "unit-query",
            "signature": "signed-field-is-part-of-the-check-string",
            "user": json.dumps({"id": user_id, "first_name": "Alex"}, separators=(",", ":")),
        }
    )


def _signed_fields(fields: dict[str, str]) -> bytes:
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    signed = dict(fields)
    signed["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(signed).encode()


async def _authenticate(
    client: AsyncClient,
    content: bytes | AsyncIterator[bytes],
    headers: dict[str, str] | None = None,
) -> Response:
    return await client.post(
        "/api/v1/auth/telegram", content=content, headers=headers or AUTH_HEADERS
    )


@pytest.mark.asyncio
async def test_operational_routes_are_private_safe_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime.datetime(2026, 8, 18, tzinfo=datetime.UTC)
    captured: dict[str, object] = {}

    async def fake_readiness_report(database_url: str, **kwargs: object) -> object:
        captured.update(database_url=database_url, **kwargs)
        return SimpleNamespace(
            healthy=False,
            as_dict=lambda: {
                "healthy": False,
                "database": True,
                "migration": True,
                "product_config": True,
                "heartbeat": False,
                "failed_outbox_events": 0,
                "code": "heartbeat_before_deploy",
            },
        )

    monkeypatch.setattr("community_bot.transport.web.readiness_report", fake_readiness_report)
    settings = Settings(
        bot_token=BOT_TOKEN,
        mini_app_origin=ORIGIN,
        release="a" * 40,
        telegram_bot_username="humanquest_bot",
        invite_token_secret="personal-invitation-secret-that-is-long-enough",  # noqa: S106
        community_telegram_chat_id=-1002237685639,
        community_telegram_join_url="https://t.me/+private-community-link",
    )
    app = create_web_app(
        settings=settings,
        database=cast("Database", FakeDatabase()),
        heartbeat_not_before=started_at,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        live = await client.get("/healthz")
        ready = await client.get("/readyz")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 503
    assert ready.json()["code"] == "heartbeat_before_deploy"
    assert ready.json()["invitation_config"] is True
    assert ready.headers["cache-control"] == "no-store"
    assert captured["expected_release"] == "a" * 40
    assert captured["heartbeat_not_before"] == started_at
    assert "database_url" not in ready.text
    assert ready.json()["release"] == settings.release


@pytest.mark.asyncio
async def test_production_readiness_requires_personal_invitation_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_readiness_report(_database_url: str, **_kwargs: object) -> object:
        return SimpleNamespace(
            healthy=True,
            as_dict=lambda: {
                "healthy": True,
                "database": True,
                "migration": True,
                "product_config": True,
                "heartbeat": True,
                "failed_outbox_events": 0,
                "code": "ready",
            },
        )

    monkeypatch.setattr("community_bot.transport.web.readiness_report", fake_readiness_report)
    app = create_web_app(
        settings=Settings(
            environment="production",
            release="a" * 40,
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            _env_file=None,
        ),
        database=cast("Database", FakeDatabase()),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        ready = await client.get("/readyz")

    assert ready.status_code == 503
    assert ready.json()["healthy"] is False
    assert ready.json()["invitation_config"] is False
    assert ready.json()["code"] == "invitation_config_missing"

    configured_app = create_web_app(
        settings=Settings(
            environment="production",
            release="a" * 40,
            bot_token=BOT_TOKEN,
            mini_app_origin=ORIGIN,
            telegram_bot_username="humanquest_bot",
            invite_token_secret="personal-invitation-secret-that-is-long-enough",  # noqa: S106
            community_telegram_chat_id=-1002237685639,
            community_telegram_join_url="https://t.me/+private-community-link",
            _env_file=None,
        ),
        database=cast("Database", FakeDatabase()),
    )
    async with AsyncClient(transport=ASGITransport(app=configured_app), base_url=ORIGIN) as client:
        configured = await client.get("/readyz")

    assert configured.status_code == 200
    assert configured.json()["healthy"] is True
    assert configured.json()["invitation_config"] is True
    assert configured.json()["code"] == "ready"


@pytest.mark.asyncio
async def test_web_lifespan_disposes_database_on_the_server_loop() -> None:
    database = FakeDatabase()
    app = _app(database)

    async with app.router.lifespan_context(app):
        assert not database.disposed

    assert database.disposed


@pytest.mark.asyncio
async def test_web_lifespan_disposes_database_after_application_failure() -> None:
    database = FakeDatabase()
    app = _app(database)

    with pytest.raises(RuntimeError, match="application failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("application failed")

    assert database.disposed


def test_frozen_proof_and_exact_failure_cases() -> None:
    now = datetime.datetime.fromtimestamp(1_700_000_100, datetime.UTC)
    assert validate_telegram_init_data(
        FROZEN_PROOF, bot_token=BOT_TOKEN, now=now
    ) == TelegramIdentity(123456789, None, "Alex")
    username_proof = _signed_fields(
        {
            "auth_date": str(int(now.timestamp())),
            "user": json.dumps({"id": 123456789, "username": "Alex_53"}, separators=(",", ":")),
        }
    )
    assert validate_telegram_init_data(
        username_proof, bot_token=BOT_TOKEN, now=now
    ) == TelegramIdentity(123456789, "Alex_53", "Новый участник")

    failures = (
        (FROZEN_PROOF.replace(b"123456789", b"123456788"), now),
        (FROZEN_PROOF + b"&user=duplicate", now),
        (FROZEN_PROOF.replace(b"auth_date=1700000000&", b""), now),
        (FROZEN_PROOF + b"&broken", now),
        (b"x" * 8193, now),
        (FROZEN_PROOF, now + datetime.timedelta(seconds=201)),
        (FROZEN_PROOF, now - datetime.timedelta(seconds=131)),
    )
    for proof, proof_now in failures:
        with pytest.raises(ValueError):
            validate_telegram_init_data(proof, bot_token=BOT_TOKEN, now=proof_now)

    base = {"auth_date": "1700000000", "user": '{"id":123456789}'}
    malformed = (
        b"",
        b"\xff",
        urlencode({**base, "hash": "short"}).encode(),
        urlencode({**base, "hash": "z" * 64}).encode(),
        _signed_fields({"auth_date": "not-an-int", "user": base["user"]}),
        _signed_fields({"auth_date": base["auth_date"], "user": "null"}),
        _signed_fields({"auth_date": base["auth_date"], "user": '{"id":true}'}),
        _signed_fields({"auth_date": base["auth_date"], "user": '{"id":0}'}),
        _signed_fields({"auth_date": base["auth_date"], "user": f'{{"id":{2**63}}}'}),
        _signed_fields(
            {"auth_date": base["auth_date"], "user": '{"id":123456789,"username":"bad-name"}'}
        ),
    )
    for proof in malformed:
        with pytest.raises(ValueError):
            validate_telegram_init_data(proof, bot_token=BOT_TOKEN, now=now)


def test_member_query_and_session_token_contract() -> None:
    assert _member_query(None) is None
    assert _member_query("") is None
    assert _member_query("  \t") is None
    assert _member_query("@@Na  Me") == "na me"
    assert _member_query(" a ") == "a"
    assert _member_query("ab") == "ab"
    assert _member_query("@") == ""
    for query in ("x" * 81,):
        with pytest.raises(Exception, match="422"):
            _member_query(query)

    raw = bytes(range(32))
    token = __import__("base64").urlsafe_b64encode(raw).rstrip(b"=").decode()
    assert _session_digest(token) == hashlib.sha256(raw).digest()
    assert _session_digest(f"{token}=") is None
    assert _session_digest("!" * 43) is None
    assert _session_digest("A" * 42 + "B") is None


def test_web_config_and_route_set_are_closed() -> None:
    database = FakeDatabase()
    app = _app(database)
    routes = {
        (
            cast("Route", route).path,
            tuple(sorted(cast("Route", route).methods or ())),
        )
        for route in app.routes
        if hasattr(route, "methods")
    }
    assert routes == {
        ("/openapi.json", ("GET", "HEAD")),
        ("/healthz", ("GET",)),
        ("/readyz", ("GET",)),
        ("/api/v1/auth/telegram", ("POST",)),
        ("/api/v1/session", ("DELETE",)),
        ("/api/v1/me", ("GET",)),
        ("/api/v1/wallet", ("GET",)),
        ("/api/v1/wallet/history", ("GET",)),
        ("/api/v1/wallet/operations/{transaction_id}", ("GET",)),
        ("/api/v1/wallet/recipients", ("GET",)),
        ("/api/v1/wallet/transfers/{transfer_id}", ("GET",)),
        ("/api/v1/wallet/transfers", ("POST",)),
        ("/api/v1/me/avatar", ("DELETE",)),
        ("/api/v1/me/avatar", ("GET",)),
        ("/api/v1/me/avatar", ("PUT",)),
        ("/api/v1/onboarding", ("GET",)),
        ("/api/v1/onboarding/answer", ("POST",)),
        ("/api/v1/onboarding/back", ("POST",)),
        ("/api/v1/onboarding/submit", ("POST",)),
        ("/api/v1/onboarding/reopen", ("POST",)),
        ("/api/v1/me/profile", ("PUT",)),
        ("/api/v1/members", ("GET",)),
        ("/api/v1/members/{member_id}", ("GET",)),
        ("/api/v1/members/{member_id}/avatar", ("GET",)),
        ("/api/v1/members/{member_id}/karma-vote", ("POST",)),
        ("/api/v1/administration", ("GET",)),
        ("/api/v1/administration/credits/self", ("GET",)),
        ("/api/v1/administration/credits/recipients", ("GET",)),
        ("/api/v1/administration/credits/recipients/{member_id}", ("GET",)),
        ("/api/v1/administration/credits/grants", ("POST",)),
        ("/api/v1/administration/credits/history", ("GET",)),
        ("/api/v1/administration/candidates", ("GET",)),
        ("/api/v1/administration/invitations", ("GET",)),
        ("/api/v1/administration/invitations", ("POST",)),
        ("/api/v1/administration/membership-resources", ("GET",)),
        ("/api/v1/administration/membership-resources", ("POST",)),
        (
            "/api/v1/administration/invitations/{invitation_id}/revoke",
            ("POST",),
        ),
        ("/api/v1/administration/{member_id}", ("GET",)),
        ("/api/v1/administration/{member_id}", ("POST",)),
        ("/api/v1/administration/{member_id}", ("PUT",)),
        ("/api/v1/administration/{member_id}/demote", ("POST",)),
        ("/api/v1/tasks", ("GET",)),
        ("/api/v1/task-home", ("GET",)),
        ("/api/v1/owned-tasks", ("GET",)),
        ("/api/v1/owned-tasks/{task_id}/cancellation", ("POST",)),
        ("/api/v1/task-cities", ("GET",)),
        ("/api/v1/task-creation", ("GET",)),
        ("/api/v1/task-creation", ("POST",)),
        ("/api/v1/tasks/{task_id}/assignments", ("POST",)),
        ("/api/v1/assignments", ("GET",)),
        ("/api/v1/assignments/{assignment_id}", ("GET",)),
        ("/api/v1/assignments/{assignment_id}/cancellation", ("POST",)),
        ("/api/v1/assignments/{assignment_id}/disputes", ("POST",)),
        ("/api/v1/assignment-reviews", ("GET",)),
        ("/api/v1/assignment-reviews/{assignment_id}", ("GET",)),
        ("/api/v1/assignment-reviews/{assignment_id}/decision", ("POST",)),
        ("/api/v1/moderation/community-reviews", ("GET",)),
        ("/api/v1/moderation/community-reviews/{assignment_id}", ("GET",)),
        ("/api/v1/assignments/{assignment_id}/submission-drafts", ("POST",)),
        ("/api/v1/submission-drafts/{draft_id}", ("PUT",)),
        ("/api/v1/submission-drafts/{draft_id}/confirm", ("POST",)),
        ("/api/v1/moderation/cases", ("GET",)),
        ("/api/v1/moderation/registrations", ("GET",)),
        ("/api/v1/moderation/registrations/{member_id}/decision", ("POST",)),
        ("/api/v1/moderation/cases/{case_id}", ("GET",)),
        ("/api/v1/moderation/cases/{case_id}/resolution", ("POST",)),
        ("/api/v1/leaderboard", ("GET",)),
        ("/api/v1/community-stats/pulse", ("GET",)),
        ("/api/v1/community-stats/leaderboard", ("GET",)),
        ("/", ("GET",)),
    }
    assert any(getattr(route, "path", None) == "/mini-assets" for route in app.routes)
    assert Settings(_env_file=None).mini_app_origin is None
    normalized_settings = Settings(telegram_bot_username="@Community_Bot", _env_file=None)
    assert normalized_settings.telegram_bot_username == "Community_Bot"
    with pytest.raises(ValueError):
        Settings(telegram_bot_username="bad-name", _env_file=None)
    for origin in (
        None,
        "http://mini.example",
        "https://mini.example/",
        "https://*.example",
        "https://mini.example:invalid",
    ):
        with pytest.raises(ValueError):
            create_web_app(
                settings=Settings(bot_token=BOT_TOKEN, mini_app_origin=origin),
                database=cast("Database", database),
            )

    create_web_app(
        settings=Settings(
            environment="development",
            bot_token=BOT_TOKEN,
            mini_app_origin="http://127.0.0.1:8000",
        ),
        database=cast("Database", database),
    )
    with pytest.raises(ValueError):
        create_web_app(
            settings=Settings(
                environment="production",
                release="a" * 40,
                bot_token=BOT_TOKEN,
                mini_app_origin="http://127.0.0.1:8000",
            ),
            database=cast("Database", database),
        )
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            release="a" * 40,
            local_review_telegram_user_id=1,
        )


@pytest.mark.asyncio
async def test_local_development_auth_uses_non_host_cookie_only_on_loopback() -> None:
    database = FakeDatabase()
    origin = "http://127.0.0.1:8000"
    app = create_web_app(
        settings=Settings(
            environment="development",
            bot_token=BOT_TOKEN,
            mini_app_origin=origin,
            local_review_telegram_user_id=1,
        ),
        database=cast("Database", database),
    )
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        response = await _authenticate(
            client,
            _proof(1, now=now),
            {"content-type": "text/plain; charset=utf-8", "origin": origin},
        )
        local_review = await client.get("/local-review", follow_redirects=False)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "community_session_local=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" not in cookie and "__Host-" not in cookie
    assert local_review.status_code == 303
    assert local_review.headers["location"] == "/"
    assert "community_session_local=" in local_review.headers["set-cookie"]


@pytest.mark.asyncio
async def test_task_creation_rejects_null_and_non_json_commands() -> None:
    database = FakeDatabase()
    database.resolve_member = True
    app = _app(database)
    headers = {"origin": ORIGIN, "idempotency-key": "70"}
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        non_json = await client.post(
            "/api/v1/task-creation", content=b'{"action":"start"}', headers=headers
        )
        null_save = await client.post(
            "/api/v1/task-creation",
            json={"action": "save", "draft_id": None, "expected_revision": None, "form": None},
            headers=headers,
        )
        null_publish = await client.post(
            "/api/v1/task-creation",
            json={"action": "publish", "draft_id": None, "expected_revision": None},
            headers=headers,
        )
    assert [non_json.status_code, null_save.status_code, null_publish.status_code] == [422] * 3


def test_task_form_normalizes_before_fingerprinting() -> None:
    source_deadline = datetime.datetime(
        2020, 1, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))
    )
    form = TaskFormRequest(
        category_id=uuid4(),
        task_kind=TaskKind.SOLO,
        time_size=TaskTimeSize.S,
        title="  title  ",
        description="  description  ",
        completion_criteria="  complete  ",
        credit_reward_per_performer=3,
        deadline_at=source_deadline,
        format=TaskFormat.ONLINE,
        city="  City  ",
        materials={"url": "  https://example.com/item  "},
        performer_slots=1,
    )
    assert form.title == "title"
    assert form.description == "description"
    assert form.completion_criteria == "complete"
    assert form.city == "City"
    assert form.materials == {"url": "https://example.com/item"}
    assert form.deadline_at == source_deadline.astimezone(datetime.UTC)


def test_submission_operation_identity_binds_resource_and_command() -> None:
    member_id = UUID("00000000-0000-0000-0000-000000000001")
    resource_id = UUID("00000000-0000-0000-0000-000000000002")
    assert _submission_update_id(member_id, resource_id, "save", "7") == _submission_update_id(
        member_id, resource_id, "save", "7"
    )
    assert _submission_update_id(member_id, resource_id, "save", "7") != _submission_update_id(
        member_id, resource_id, "confirm", "7"
    )
    first = _submission_fingerprint("save", 2, payload={"result": "one"})
    assert first == _submission_fingerprint("save", 2, payload={"result": "one"})
    assert first != _submission_fingerprint("save", 2, payload={"result": "two"})


def test_submission_draft_projection_is_allowlisted_and_revisions_are_strict() -> None:
    draft = SubmissionDraft(
        uuid4(), uuid4(), uuid4(), uuid4(), 3, {"result": "safe", "private": "NO"}, None
    )
    assert _submission_draft_dto(draft).model_dump() == {
        "id": draft.id,
        "revision": 3,
        "result": "safe",
    }
    for model in (SaveSubmissionDraftRequest, ConfirmSubmissionDraftRequest):
        with pytest.raises(ValueError):
            model.model_validate({"expected_revision": "3", "payload": {"result": "x"}})


@pytest.mark.asyncio
async def test_auth_issues_exact_cookie_without_exposing_raw_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase()
    raw_tokens = [b"x" * 32, b"y" * 32]
    monkeypatch.setattr(
        "community_bot.transport.web.secrets.token_bytes",
        lambda _size: raw_tokens.pop(0) if raw_tokens else b"z" * 32,
    )
    app = _app(database)
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/api/v1/me")).status_code == 401
        client.cookies.set("__Host-community_session", "!" * 43)
        invalid_cookie = await client.get("/api/v1/me")
        assert invalid_cookie.status_code == 401
        client.cookies.set("__Host-community_session", "A" * 43)
        unresolved = await client.get("/api/v1/me")
        assert unresolved.status_code == 401
        bad_content = await _authenticate(
            client, b"ignored", {"content-type": "application/json", "origin": ORIGIN}
        )
        assert bad_content.status_code == 422
        bad_proof = await _authenticate(client, b"invalid")
        assert bad_proof.status_code == 401
        for invalid_length in ("invalid", "-1"):
            malformed_length = await _authenticate(
                client, b"", AUTH_HEADERS | {"content-length": invalid_length}
            )
            assert malformed_length.status_code == 422
            assert malformed_length.json() == {"code": "invalid_request"}

        consumed = False

        async def should_not_be_read() -> AsyncIterator[bytes]:
            nonlocal consumed
            consumed = True
            yield b"unreachable"

        oversized = await _authenticate(
            client, should_not_be_read(), AUTH_HEADERS | {"content-length": "8193"}
        )
        assert oversized.status_code == 413
        assert oversized.json() == {"code": "payload_too_large"}
        assert not consumed

        async def chunked_oversized() -> AsyncIterator[bytes]:
            yield b"x" * 4096
            yield b"x" * 4097

        chunked = await _authenticate(client, chunked_oversized())
        assert chunked.status_code == 413
        assert chunked.json() == {"code": "payload_too_large"}
        exact_limit = await _authenticate(client, b"x" * 8192)
        assert exact_limit.status_code == 401
        denied = await _authenticate(
            client, _proof(1, now=now), {"content-type": "text/plain; charset=utf-8"}
        )
        assert denied.status_code == 403
        response = await _authenticate(client, _proof(1, now=now))
        repeated = await _authenticate(client, _proof(1, now=now))

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert "__Host-community_session=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Path=/" in cookie and "Max-Age=2592000" in cookie and "Domain=" not in cookie
    assert repeated.status_code == 401
    assert "set-cookie" not in repeated.headers
    assert [session["token_digest"] for session in database.created_sessions] == [
        hashlib.sha256(b"x" * 32).digest(),
    ]
    assert (
        database.created_sessions[0]["proof_digest"] == hashlib.sha256(_proof(1, now=now)).digest()
    )
    assert all(
        cast("datetime.datetime", session["expires_at"])
        - cast("datetime.datetime", session["authenticated_at"])
        == datetime.timedelta(days=30)
        for session in database.created_sessions
    )
    assert b"x" * 32 not in response.content

    database.return_member = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        unknown = await _authenticate(client, _proof(1, now=datetime.datetime.now(datetime.UTC)))
    assert unknown.status_code == 401
    database.return_member = True

    database.fail_create = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        failed = await _authenticate(client, _proof(1, now=datetime.datetime.now(datetime.UTC)))
    assert failed.status_code == 503
    assert "set-cookie" not in failed.headers


@pytest.mark.asyncio
async def test_closed_error_boundary_and_validation_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase()
    app = _app(database)

    async def structured_error() -> None:
        raise HTTPException(status_code=418, detail={"private": "detail"})

    app.add_api_route("/test-structured-error", structured_error)
    database.resolve_member = True
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        invalid = await client.get("/api/v1/members/not-a-uuid")
        structured = await client.get("/test-structured-error")
        missing = await client.get("/api/v1/missing")
        wrong_method = await client.post("/api/v1/me")
    assert invalid.status_code == 422
    assert invalid.json() == {"code": "invalid_request"}
    assert (structured.status_code, structured.json()) == (418, {"code": "request_failed"})
    assert "private" not in structured.text
    assert (missing.status_code, missing.json()) == (404, {"code": "not_found"})
    assert (wrong_method.status_code, wrong_method.json()) == (
        405,
        {"code": "method_not_allowed"},
    )
    assert all(
        response.headers["cache-control"] == "no-store"
        for response in (invalid, structured, missing, wrong_method)
    )

    monkeypatch.setattr(
        "community_bot.application.registration.RegistrationService.own_profile",
        AsyncMock(side_effect=RuntimeError("private owner detail")),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        failure = await client.get("/api/v1/me")
    assert failure.status_code == 500
    assert failure.json() == {"code": "internal_error"}
    assert failure.headers["cache-control"] == "no-store"
    assert "private owner detail" not in failure.text


@pytest.mark.asyncio
async def test_read_routes_map_application_denials_to_closed_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase()
    database.resolve_member = True
    app = _app(database)

    for owner, denial in (
        ("registration.RegistrationService.own_profile", PermissionError()),
        ("reputation.ReputationService.members", ProfileUnavailableError()),
        ("reputation.ReputationService.profile_detail", PermissionError()),
        ("tasks.TaskService.list_available", PermissionError()),
        ("reputation.ReputationService.leaderboard", ProfileUnavailableError()),
    ):
        monkeypatch.setattr(f"community_bot.application.{owner}", AsyncMock(side_effect=denial))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        responses = (
            await client.get("/api/v1/me"),
            await client.get("/api/v1/members"),
            await client.get(f"/api/v1/members/{uuid4()}"),
            await client.get("/api/v1/tasks"),
            await client.get("/api/v1/leaderboard"),
        )
    assert [response.status_code for response in responses] == [403, 403, 404, 403, 403]
    assert all(response.headers["cache-control"] == "no-store" for response in responses)

    empty = dict.fromkeys(["city", "short_bio", "current_goal", "availability"])
    base = dict(
        member_id=database.member_id,
        telegram_username=None,
        display_name="Alex",
        help_categories=(),
        skill_tags=(),
        profile_links=(),
        experience_total=0,
        **empty,
    )
    own_profile = SimpleNamespace(
        **base,
        timezone="UTC",
        credit_balance=0,
        level=SimpleNamespace(level_number=1, display_name="First"),
    )
    safe_profile = SimpleNamespace(
        **base,
        level_number=1,
        karma=SimpleNamespace(score=0, count=0),
        reliability=SimpleNamespace(accepted=0, approved_weight=Decimal(0), no_show=0, rate=None),
    )

    monkeypatch.setattr(
        "community_bot.application.registration.RegistrationService.own_profile",
        AsyncMock(return_value=own_profile),
    )
    monkeypatch.setattr(
        "community_bot.application.reputation.ReputationService.profile_detail",
        AsyncMock(return_value=(safe_profile, False)),
    )
    monkeypatch.setattr(
        "community_bot.application.reputation.ReputationService.own_statistics",
        AsyncMock(return_value=SimpleNamespace(completed=6, created=2)),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        me = await client.get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["statistics"] == {"completed_tasks": 6, "created_tasks": 2}
        assert (await client.get(f"/api/v1/members/{database.member_id}")).status_code == 200


def test_task_dto_preserves_only_public_projection() -> None:
    assert inspect.signature(TaskService.list_available).parameters["limit"].default == 10
    created_at = datetime.datetime.now(datetime.UTC)
    task = cast(
        "PublishedTask",
        SimpleNamespace(
            id=uuid4(),
            origin="member",
            author_display_name="Alex",
            category_name=None,
            category_icon=None,
            task_kind=TaskKind.SOLO,
            time_size=TaskTimeSize.S,
            title="Help",
            credit_reward_per_performer=1,
            performer_slots=1,
            minimum_level=1,
            format=TaskFormat.ONLINE,
            city=None,
            created_at=created_at,
            deadline_at=created_at + datetime.timedelta(days=1),
            status=TaskStatus.PUBLISHED,
            description="Public description",
            completion_criteria="Done",
            performer_instructions="Follow instructions",
            materials={"text": "Read me", "url": "https://example.test", "private": "x"},
            input_payload={"public": "shown", "private": "hidden"},
            public_input_keys=("public",),
        ),
    )
    payload = _task_dto(task).model_dump(mode="json")
    assert payload["task_kind"] == "solo"
    assert payload["time_size"] == "s"
    assert payload["created_at"] == created_at.isoformat().replace("+00:00", "Z")
    assert payload["description"] == "Public description"
    assert payload["materials"] == {
        "text": "Read me",
        "url": "https://example.test",
    }
    assert payload["public_input"] == {"public": "shown"}
    assert "input_payload" not in payload

    empty_task = SimpleNamespace(**(vars(task) | {"task_kind": None, "time_size": None}))
    empty_enums = _task_dto(cast("PublishedTask", empty_task))
    assert empty_enums.task_kind is None
    assert empty_enums.time_size is None


def test_accept_update_id_is_task_and_actor_bound() -> None:
    member_id = UUID("00000000-0000-0000-0000-000000000001")
    task_id = UUID("00000000-0000-0000-0000-000000000002")
    resolved = _accept_update_id(member_id, task_id, "42")

    assert resolved == _accept_update_id(member_id, task_id, "42")
    assert 1 <= resolved <= 2**63 - 1
    assert resolved != _accept_update_id(uuid4(), task_id, "42")
    assert resolved != _accept_update_id(member_id, uuid4(), "42")
    assert resolved != _accept_update_id(member_id, task_id, "43")


def test_assignment_cursor_is_canonical_and_strict() -> None:
    cursor = (
        datetime.datetime(2026, 8, 17, 20, 0, tzinfo=datetime.UTC),
        UUID("00000000-0000-0000-0000-000000000054"),
    )
    encoded = _assignment_cursor(cursor)
    assert _parse_assignment_cursor(encoded) == cursor
    assert _parse_assignment_cursor(None) is None
    for invalid in ("", "!", encoded + "=", encoded.lower(), "A" * 129):
        with pytest.raises(ValueError, match="Invalid assignment cursor"):
            _parse_assignment_cursor(invalid)


@pytest.mark.asyncio
async def test_accept_transport_precedence_is_origin_session_then_key() -> None:
    database = FakeDatabase()
    app = _app(database)
    task_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        invalid_origin = await client.post(
            f"/api/v1/tasks/{task_id}/assignments",
            headers=[("origin", "https://wrong.example"), ("idempotency-key", "00")],
        )
        assert invalid_origin.status_code == 403
        assert invalid_origin.json() == {"code": "invalid_origin"}
        duplicate_origin = await client.post(
            f"/api/v1/tasks/{task_id}/assignments",
            headers=[
                ("origin", ORIGIN),
                ("origin", ORIGIN),
                ("idempotency-key", "1"),
            ],
        )
        assert duplicate_origin.status_code == 403
        assert duplicate_origin.json() == {"code": "invalid_origin"}

        invalid_session = await client.post(
            f"/api/v1/tasks/{task_id}/assignments",
            headers={"origin": ORIGIN, "idempotency-key": "00"},
        )
        assert invalid_session.status_code == 401

        database.resolve_member = True
        client.cookies.set("__Host-community_session", SESSION_TOKEN)
        malformed = (None, "", "0", "00", "+1", "-1", " 1", str(2**63))
        for value in malformed:
            headers = {"origin": ORIGIN}
            if value is not None:
                headers["idempotency-key"] = value
            response = await client.post(
                f"/api/v1/tasks/{task_id}/assignments",
                headers=headers,
            )
            assert response.status_code == 422
            assert response.json() == {"code": "invalid_idempotency_key"}

        non_ascii = await client.post(
            f"/api/v1/tasks/{task_id}/assignments",
            headers=[
                (b"origin", ORIGIN.encode()),
                (b"idempotency-key", b"\xd9\xa1"),
            ],
        )
        assert non_ascii.status_code == 422
        assert non_ascii.json() == {"code": "invalid_idempotency_key"}

        duplicate_key = await client.post(
            f"/api/v1/tasks/{task_id}/assignments",
            headers=[
                ("origin", ORIGIN),
                ("idempotency-key", "1"),
                ("idempotency-key", "2"),
            ],
        )
        assert duplicate_key.status_code == 422
        assert duplicate_key.json() == {"code": "invalid_idempotency_key"}


@pytest.mark.asyncio
async def test_accept_request_shape_and_expected_owner_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase()
    database.resolve_member = True
    app = _app(database)
    task_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    owner = AsyncMock()
    monkeypatch.setattr(
        "community_bot.application.assignments.AssignmentService.accept_with_task",
        owner,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        cookies={"__Host-community_session": SESSION_TOKEN},
    ) as client:
        for path, content in (
            (str(task_id).upper(), b""),
            (str(task_id), b"not-empty"),
        ):
            response = await client.post(
                f"/api/v1/tasks/{path}/assignments",
                headers={"origin": ORIGIN, "idempotency-key": "1"},
                content=content,
            )
            assert response.status_code == 422
            assert response.json() == {"code": "invalid_request"}
            assert response.headers["cache-control"] == "no-store"
        owner.assert_not_awaited()

        for error in (
            AssignmentError("unavailable"),
            LookupError("unavailable"),
            PermissionError("unavailable"),
            TaskError("unavailable"),
        ):
            owner.side_effect = error
            response = await client.post(
                f"/api/v1/tasks/{task_id}/assignments",
                headers={"origin": ORIGIN, "idempotency-key": "1"},
            )
            assert response.status_code == 409
            assert response.json() == {"code": "assignment_unavailable"}
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_mini_app_assets_are_packaged_with_security_headers() -> None:
    app = _app(FakeDatabase())
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as client:
        index = await client.get("/")
        font = await client.get("/mini-assets/manrope.ttf")
        app_module = await client.get("/mini-assets/app.js")
        theme_bootstrap = await client.get("/mini-assets/theme-bootstrap.js")

    assert (
        index.status_code
        == font.status_code
        == app_module.status_code
        == theme_bootstrap.status_code
        == 200
    )
    assert "default-src 'self'" in index.headers["content-security-policy"]
    assert "script-src 'self' https://telegram.org" in index.headers["content-security-policy"]
    assert "img-src 'self' blob:" in index.headers["content-security-policy"]
    assert "script-src 'self' blob:" not in index.headers["content-security-policy"]
    assert "https://t.me" not in index.headers["content-security-policy"]
    bridge = b'<script src="https://telegram.org/js/telegram-web-app.js"></script>'
    assert index.content.index(bridge) < index.content.index(b"</head>")
    assert index.content.index(bridge) < index.content.index(b"/mini-assets/app.js")
    assert b"__RELEASE__" not in index.content
    assert b"/mini-assets/app.js?release=local" in index.content
    assert b"/mini-assets/styles.css?release=local" in index.content
    assert b'class="app-loader-dots"' in index.content
    assert b"onboarding-loader.png" not in index.content
    assert b'class="app-booting"' in index.content
    assert b'<h1 id="screen-title"></h1>' in index.content
    hidden_navigation = 'id="primary-navigation" aria-label="Основное меню" hidden'.encode()
    assert hidden_navigation in index.content
    assert b"platform.js?release=${encodeURIComponent(assetRelease)}" in app_module.content
    bootstrap_asset = b"/mini-assets/theme-bootstrap.js?release=local"
    assert bootstrap_asset in index.content
    assert index.content.index(bootstrap_asset) < index.content.index(b"/mini-assets/styles.css")
    assert index.headers["x-content-type-options"] == "nosniff"
    design_font = (
        Path(__file__).parents[2] / "docs/release-2/design/assets/Manrope[wght].ttf"
    ).read_bytes()
    assert hashlib.sha256(font.content).digest() == hashlib.sha256(design_font).digest()
