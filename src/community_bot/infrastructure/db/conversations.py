"""Persistence for the one free-text owner per Telegram member."""

# ruff: noqa: EM101, PLR0913, TRY003

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from community_bot.application.conversations import TextFlow
from community_bot.infrastructure.db.models import ConversationStateModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_PROTECTED_FLOWS = {"registration", "registration_paused", "profile_edit"}


async def get_text_flow(
    session: AsyncSession, member_id: uuid.UUID, *, for_update: bool = False
) -> TextFlow | None:
    """Read or lock the current free-text owner."""
    statement = select(ConversationStateModel).where(ConversationStateModel.member_id == member_id)
    if for_update:
        statement = statement.with_for_update()
    state = await session.scalar(statement)
    if state is None:
        return None
    raw_reference = state.payload_json.get("reference_id")
    return TextFlow(
        member_id=member_id,
        flow_type=state.flow_type,
        step=state.current_step,
        reference_id=None if raw_reference is None else uuid.UUID(str(raw_reference)),
        revision=state.revision,
    )


async def claim_text_flow(
    session: AsyncSession,
    *,
    member_id: uuid.UUID,
    flow_type: str,
    step: str,
    reference_id: uuid.UUID | None,
    revision: int,
    payload: dict[str, object] | None = None,
) -> TextFlow:
    """Atomically select one owner while preserving protected registration flows."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is not None and state.flow_type in _PROTECTED_FLOWS and state.flow_type != flow_type:
        raise ValueError("Finish or cancel the registration/profile conversation first.")
    values = dict(payload or {})
    values["reference_id"] = None if reference_id is None else str(reference_id)
    if state is None:
        state = ConversationStateModel(
            member_id=member_id,
            flow_type=flow_type,
            current_step=step,
            payload_json=values,
            revision=revision,
        )
        session.add(state)
    else:
        state.flow_type = flow_type
        state.current_step = step
        state.payload_json = values
        state.revision = revision
    await session.flush()
    owner = await get_text_flow(session, member_id)
    if owner is None:
        raise RuntimeError("Text flow was not persisted.")
    return owner


async def clear_text_flow(
    session: AsyncSession,
    *,
    member_id: uuid.UUID,
    flow_type: str,
    reference_id: uuid.UUID | None = None,
) -> bool:
    """Delete only the exact selected owner."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is None or state.flow_type != flow_type:
        return False
    if reference_id is not None and str(state.payload_json.get("reference_id")) != str(
        reference_id
    ):
        return False
    await session.delete(state)
    await session.flush()
    return True
