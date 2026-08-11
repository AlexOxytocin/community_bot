"""Shared text-flow ownership for the composed Telegram dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler

from community_bot.transport.telegram.registration import handle_registration_text
from community_bot.transport.telegram.tasks import handle_task_text

if TYPE_CHECKING:
    from aiogram.types import Message, Update

    from community_bot.application.registration import RegistrationService
    from community_bot.application.tasks import TaskService


def build_conversation_router(
    task_service: TaskService,
    registration_service: RegistrationService,
) -> Router:
    """Route one free-form message to the durable flow that currently owns it."""
    router = Router(name="conversation_text")

    async def handle_text(message: Message, event_update: Update) -> None:
        if await handle_task_text(task_service, message, event_update):
            return
        if await handle_registration_text(registration_service, message, event_update):
            return
        raise SkipHandler

    router.message.register(handle_text, F.text & ~F.text.startswith("/"))
    return router
