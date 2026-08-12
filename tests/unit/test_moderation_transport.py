"""Focused safety coverage for every Telegram moderation route."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Never, cast
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.transport.telegram.moderation import build_moderation_router
from tests.integration.test_task_creation import CapturingSession

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from community_bot.application.moderation import ModerationService


async def _deny_moderation(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise PermissionError


class _DeniedModerationService:
    """Expose every service method as a deterministic permission denial."""

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Never]]:
        del name
        return _deny_moderation


@pytest.mark.asyncio
async def test_moderation_router_safely_denies_every_route() -> None:
    """All commands and callbacks convert denied mutations into safe responses."""
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_moderation_router(cast("ModerationService", _DeniedModerationService()))
    )
    capture = CapturingSession()
    bot = Bot(token=f"{123456}:{'M' * 35}", session=capture)
    actor = User(id=9201, is_bot=False, first_name="Administrator")
    entity_id = uuid4()

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
                id=f"moderation-{update_id}",
                from_user=actor,
                chat_instance="moderation",
                data=data,
                message=Message(
                    message_id=update_id,
                    date=datetime.datetime.now(datetime.UTC),
                    chat=Chat(id=actor.id, type="private"),
                    text="moderation",
                ),
            ),
        )

    updates = [
        message_update(92_001, "/moderation"),
        message_update(92_002, f"/mod_fraud {entity_id} safe reason"),
        message_update(
            92_003,
            f"/mod_resolve {entity_id} 1 full_payment safe reason",
        ),
        message_update(92_004, f"/mod_appeal {entity_id} safe reason"),
        message_update(
            92_005,
            f"/mod_sanction {entity_id} restriction 24 create_task safe reason",
        ),
        message_update(92_006, f"/mod_revoke {entity_id} safe reason"),
        callback_update(92_007, f"mod:res:{entity_id.hex}"),
        callback_update(92_008, f"mod:case:{entity_id.hex}:1:pay"),
        callback_update(92_009, f"mod:fraud:{entity_id.hex}"),
        callback_update(92_010, f"mod:appeal:{entity_id.hex}"),
        callback_update(92_011, f"mod:warn:{entity_id.hex}"),
        callback_update(92_012, f"mod:restrict:{entity_id.hex}"),
        callback_update(92_013, f"mod:revoke:{entity_id.hex}"),
        callback_update(92_014, f"mod:alert:{entity_id.hex}:ok"),
        callback_update(92_015, "mod:list:fraud"),
        callback_update(92_016, "mod:list:alerts"),
        callback_update(92_017, "mod:list:sanctions"),
        callback_update(92_018, "mod:list:unknown"),
    ]
    for update in updates:
        await dispatcher.feed_update(bot, update)

    assert len(capture.texts) == len(updates)
    assert all("не" in value.lower() for value in capture.texts)
    await bot.session.close()
