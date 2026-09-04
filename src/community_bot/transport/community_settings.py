"""Authenticated settings routes shared by the Mini App and Telegram adapter."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from community_bot.domain.community_preferences import PreferencesConflictError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI

    from community_bot.application.identity import ActorContext
    from community_bot.infrastructure.db.community_preferences import CommunityPreferencesStore
    from community_bot.transport.telegram_updates import TelegramUpdates


class PreferenceRequest(BaseModel):
    """One absolute selection with optimistic concurrency, never a blind toggle."""

    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["tasks", "nomad"]
    enabled: bool
    expected_revision: int = Field(ge=0)


class RegistrationPolicyRequest(BaseModel):
    """Only the explicit confirmation action can change the global policy."""

    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["standard", "simplified"]
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]


async def bounded_json(request: Request, limit: int = 4096) -> bytes:
    """Bound bytes before JSON parsing, including streamed/chunked requests."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(422, "invalid_request")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "request_too_large")
    return bytes(body)


def install_community_settings_routes(  # noqa: C901, PLR0913 - small route closures and explicit dependencies.
    app: FastAPI,
    *,
    store: CommunityPreferencesStore,
    current_actor: Callable[[Request], Awaitable[ActorContext]],
    require_origin: Callable[[Request], None],
    telegram: TelegramUpdates | None,
    webhook_secret: str | None,
) -> None:
    """Install routes without changing cookie or Telegram proof authentication."""

    async def read(request: Request, *, policy: bool) -> JSONResponse:
        actor = await current_actor(request)
        try:
            data = (
                await store.policy(actor.member_id)
                if policy
                else await store.preferences(actor.member_id)
            )
            return JSONResponse(data, headers={"Cache-Control": "no-store"})
        except PermissionError:
            raise HTTPException(403, "forbidden") from None

    async def write(request: Request, *, policy: bool) -> JSONResponse:
        require_origin(request)
        actor = await current_actor(request)
        try:
            body = await bounded_json(request)
            if policy:
                change = RegistrationPolicyRequest.model_validate_json(body)
                data = await store.set_policy(
                    actor.member_id, change.mode, change.expected_revision
                )
            else:
                preference = PreferenceRequest.model_validate_json(body)
                data = await store.set_preference(
                    actor.member_id,
                    preference.category,
                    preference.enabled,
                    preference.expected_revision,
                )
            return JSONResponse(data, headers={"Cache-Control": "no-store"})
        except PreferencesConflictError:
            raise HTTPException(409, "settings_changed") from None
        except (ValidationError, ValueError):
            raise HTTPException(422, "invalid_request") from None
        except PermissionError:
            raise HTTPException(403, "forbidden") from None

    @app.get("/api/v1/notification-preferences")
    async def preferences(request: Request) -> JSONResponse:
        return await read(request, policy=False)

    @app.patch("/api/v1/notification-preferences")
    async def update_preferences(request: Request) -> JSONResponse:
        return await write(request, policy=False)

    @app.get("/api/v1/administration/registration-policy")
    async def policy(request: Request) -> JSONResponse:
        return await read(request, policy=True)

    @app.patch("/api/v1/administration/registration-policy")
    async def update_policy(request: Request) -> JSONResponse:
        return await write(request, policy=True)

    @app.post("/api/telegram/webhook")
    async def telegram_webhook(request: Request) -> JSONResponse:
        if telegram is None or not webhook_secret:
            raise HTTPException(404, "not_found")
        supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(supplied.encode(), webhook_secret.encode()):
            raise HTTPException(403, "forbidden")
        body = await bounded_json(request, limit=262144)
        try:
            await telegram.handle(body)
        except ValidationError:
            raise HTTPException(422, "invalid_update") from None
        return JSONResponse({"ok": True})
