"""Shared text-flow ownership for the composed Telegram dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command

from community_bot.transport.telegram.assignments import handle_assignment_text
from community_bot.transport.telegram.registration import handle_registration_text
from community_bot.transport.telegram.reputation import handle_karma_text
from community_bot.transport.telegram.tasks import handle_task_text

if TYPE_CHECKING:
    from aiogram.types import Message, Update

    from community_bot.application.assignments import AssignmentService
    from community_bot.application.conversations import ConversationService
    from community_bot.application.registration import RegistrationService
    from community_bot.application.reputation import ReputationService
    from community_bot.application.tasks import TaskService


def build_conversation_router(  # noqa: C901
    task_service: TaskService,
    registration_service: RegistrationService,
    assignment_service: AssignmentService,
    reputation_service: ReputationService,
    conversation_service: ConversationService,
) -> Router:
    """Route one free-form message to the durable flow that currently owns it."""
    router = Router(name="conversation_text")

    async def handle_text(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            raise SkipHandler
        owner = await conversation_service.current(message.from_user.id)
        if owner is None:
            raise SkipHandler
        if owner.flow_type in {"registration", "registration_paused", "profile_edit"}:
            if await handle_registration_text(registration_service, message, event_update):
                return
        elif owner.flow_type == "karma":
            if await handle_karma_text(reputation_service, owner, message, event_update):
                return
        elif owner.flow_type in {"assignment_result", "assignment_dispute"}:
            if await handle_assignment_text(assignment_service, owner, message, event_update):
                return
        elif owner.flow_type == "task" and await handle_task_text(
            task_service, message, event_update
        ):
            return
        raise SkipHandler

    async def cancel(message: Message, event_update: Update) -> None:
        if message.from_user is None:
            return
        owner = await conversation_service.current(message.from_user.id)
        if owner is None:
            await message.answer("Активного диалога нет.")
            return
        if owner.flow_type == "task" and owner.reference_id is not None:
            await task_service.cancel_draft(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                draft_id=owner.reference_id,
            )
        elif owner.flow_type in {"assignment_result", "assignment_dispute"} and owner.reference_id:
            await assignment_service.cancel_text_flow(
                update_id=event_update.update_id,
                actor_telegram_user_id=message.from_user.id,
                flow_type=owner.flow_type,
                reference_id=owner.reference_id,
            )
        elif owner.flow_type == "karma":
            await reputation_service.cancel_vote(
                update_id=event_update.update_id,
                telegram_user_id=message.from_user.id,
            )
        else:
            await registration_service.cancel(
                update_id=event_update.update_id,
                telegram_user_id=message.from_user.id,
            )
        await message.answer("Текущий диалог отменён.")

    router.message.register(cancel, Command("cancel"))
    router.message.register(handle_text, F.text & ~F.text.startswith("/"))
    return router
