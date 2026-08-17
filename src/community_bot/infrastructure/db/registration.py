"""PostgreSQL persistence for invitations, registration, and own profiles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, text

from community_bot.application.registration import (
    InvitationSnapshot,
    ProfileData,
    RegistrationContext,
)
from community_bot.domain.members import MemberStatus
from community_bot.domain.registration import (
    ModerationDecision,
    ProfileField,
    RegistrationApplicationStatus,
    RegistrationError,
    RegistrationStep,
)
from community_bot.infrastructure.db.models import (
    ConversationStateModel,
    InvitationModel,
    InvitationRedemptionModel,
    MemberModel,
    OutboxEventModel,
    RegistrationApplicationModel,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

_IDENTITY_GATE_NAMESPACE = "registration_identity"
_REQUIRED_PROFILE_FIELDS = {
    "consent",
    ProfileField.DISPLAY_NAME.value,
    ProfileField.CITY.value,
    ProfileField.TIMEZONE.value,
    ProfileField.SHORT_BIO.value,
    ProfileField.CURRENT_GOAL.value,
    ProfileField.HELP_CATEGORIES.value,
    ProfileField.SKILL_TAGS.value,
    ProfileField.AVAILABILITY.value,
}


async def acquire_registration_identity_gate(
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    """Serialize every registration/profile mutation for one Telegram identity."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:namespace, :identity))"),
        {"namespace": _IDENTITY_GATE_NAMESPACE, "identity": telegram_user_id},
    )


async def create_invitation(  # noqa: PLR0913 - persistence fields mirror the table.
    session: AsyncSession,
    *,
    code_hash: str,
    created_by_member_id: UUID,
    intended_telegram_user_id: int | None,
    max_uses: int,
    expires_at: datetime | None,
) -> UUID:
    """Insert one invitation without retaining its open token."""
    invitation = InvitationModel(
        id=uuid.uuid4(),
        code_hash=code_hash,
        created_by_member_id=created_by_member_id,
        intended_telegram_user_id=intended_telegram_user_id,
        max_uses=max_uses,
        uses_count=0,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.flush()
    return invitation.id


async def revoke_invitation(session: AsyncSession, invitation_id: UUID) -> bool:
    """Lock and revoke one invitation, returning whether state changed."""
    invitation = await session.scalar(
        select(InvitationModel).where(InvitationModel.id == invitation_id).with_for_update()
    )
    if invitation is None:
        message = "Invitation does not exist."
        raise LookupError(message)
    if invitation.revoked_at is not None:
        return False
    invitation.revoked_at = datetime.now(UTC)
    await session.flush()
    return True


async def lock_invitation_by_hash(
    session: AsyncSession,
    code_hash: str,
) -> InvitationSnapshot | None:
    """Lock one invitation by exact hash."""
    model = await session.scalar(
        select(InvitationModel).where(InvitationModel.code_hash == code_hash).with_for_update()
    )
    return None if model is None else _invitation_snapshot(model)


async def get_registration_context(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    for_update: bool,
) -> RegistrationContext | None:
    """Read member, application, and state as one registration context."""
    member_statement = select(MemberModel).where(MemberModel.telegram_user_id == telegram_user_id)
    if for_update:
        member_statement = member_statement.with_for_update()
    member = await session.scalar(member_statement)
    if member is None:
        return None
    return await _context_by_member(session, member, for_update=for_update)


async def create_pending_registration(
    session: AsyncSession,
    *,
    invitation: InvitationSnapshot,
    telegram_user_id: int,
    telegram_username: str | None,
    telegram_display_name: str,
) -> RegistrationContext:
    """Consume one locked invitation and create all registration records."""
    invitation_model = await session.get(InvitationModel, invitation.id)
    if invitation_model is None:
        message = "Invitation disappeared during registration."
        raise LookupError(message)
    invitation_model.uses_count += 1
    member = MemberModel(
        id=uuid.uuid4(),
        telegram_user_id=telegram_user_id,
        telegram_username=_optional_text(telegram_username, maximum=128),
        display_name=_fallback_display_name(telegram_display_name),
        timezone="UTC",
        role="member",
        status=MemberStatus.PENDING.value,
        level_number=1,
        invited_by_member_id=invitation.created_by_member_id,
    )
    session.add(member)
    await session.flush()
    session.add_all(
        [
            InvitationRedemptionModel(
                id=uuid.uuid4(),
                invitation_id=invitation.id,
                member_id=member.id,
            ),
            RegistrationApplicationModel(
                member_id=member.id,
                status=RegistrationApplicationStatus.DRAFT.value,
            ),
            ConversationStateModel(
                member_id=member.id,
                flow_type="registration",
                current_step=RegistrationStep.CONSENT.value,
                payload_json={},
            ),
        ]
    )
    await session.flush()
    return await _context_by_member(session, member, for_update=False)


async def update_registration_username(
    session: AsyncSession,
    *,
    member_id: UUID,
    telegram_username: str | None,
) -> None:
    """Update mutable username without changing member identity."""
    member = await session.get(MemberModel, member_id)
    if member is None:
        message = "Member does not exist."
        raise LookupError(message)
    member.telegram_username = _optional_text(telegram_username, maximum=128)
    member.last_activity_at = datetime.now(UTC)


async def save_registration_answer(
    session: AsyncSession,
    *,
    member_id: UUID,
    field: str,
    value: object,
    next_step: RegistrationStep,
) -> RegistrationContext:
    """Persist one normalized answer into the locked conversation."""
    member, application, state = await _locked_registration_rows(session, member_id)
    if application.status not in {
        RegistrationApplicationStatus.DRAFT.value,
        RegistrationApplicationStatus.REJECTED.value,
    }:
        message = "Registration answers are closed for this application."
        raise RegistrationError(message)
    payload = dict(state.payload_json)
    payload[field] = list(value) if isinstance(value, tuple) else value
    state.payload_json = payload
    state.current_step = next_step.value
    state.flow_type = "registration"
    state.updated_at = datetime.now(UTC)
    application.status = RegistrationApplicationStatus.DRAFT.value
    application.review_comment = None
    application.reviewed_at = None
    application.reviewed_by_member_id = None
    if field == "consent":
        application.consented_at = datetime.now(UTC)
    await session.flush()
    return _registration_context(member, application, state)


async def submit_registration(
    session: AsyncSession,
    member_id: UUID,
) -> RegistrationContext:
    """Copy a complete draft to the member profile and submit it."""
    member, application, state = await _locked_registration_rows(session, member_id)
    payload = dict(state.payload_json)
    missing = _REQUIRED_PROFILE_FIELDS - payload.keys()
    if missing:
        message = "Registration draft is incomplete."
        raise RegistrationError(message)
    _copy_payload_to_member(member, payload)
    application.status = RegistrationApplicationStatus.SUBMITTED.value
    application.submitted_at = datetime.now(UTC)
    application.reviewed_at = None
    application.reviewed_by_member_id = None
    application.review_comment = None
    state.current_step = RegistrationStep.SUBMITTED.value
    state.updated_at = datetime.now(UTC)
    await session.flush()
    return _registration_context(member, application, state)


async def reopen_rejected_registration(
    session: AsyncSession,
    member_id: UUID,
) -> RegistrationContext:
    """Move a rejected application back to editable preview."""
    member, application, state = await _locked_registration_rows(session, member_id)
    if application.status != RegistrationApplicationStatus.REJECTED.value:
        message = "Only a rejected registration can be reopened."
        raise RegistrationError(message)
    application.status = RegistrationApplicationStatus.DRAFT.value
    state.flow_type = "registration"
    state.current_step = RegistrationStep.PREVIEW.value
    state.updated_at = datetime.now(UTC)
    await session.flush()
    return _registration_context(member, application, state)


async def lock_registration_application(
    session: AsyncSession,
    member_id: UUID,
) -> RegistrationContext:
    """Lock one complete registration application."""
    member = await session.scalar(
        select(MemberModel).where(MemberModel.id == member_id).with_for_update()
    )
    if member is None:
        message = "Registration member does not exist."
        raise LookupError(message)
    return await _context_by_member(session, member, for_update=True)


async def decide_registration(
    session: AsyncSession,
    *,
    member_id: UUID,
    actor_member_id: UUID,
    decision: ModerationDecision,
    comment: str | None,
) -> RegistrationContext:
    """Persist one locked moderation decision."""
    member, application, state = await _locked_registration_rows(session, member_id)
    now = datetime.now(UTC)
    application.reviewed_at = now
    application.reviewed_by_member_id = actor_member_id
    application.review_comment = _optional_text(comment, maximum=500)
    if decision is ModerationDecision.APPROVE:
        member.status = MemberStatus.ACTIVE.value
        member.approved_at = now
        application.status = RegistrationApplicationStatus.APPROVED.value
        await session.delete(state)
    else:
        application.status = RegistrationApplicationStatus.REJECTED.value
        state.flow_type = "registration"
        state.current_step = RegistrationStep.PREVIEW.value
    await session.flush()
    return _registration_context(member, application, state)


async def list_submitted_registrations(
    session: AsyncSession,
    limit: int,
) -> tuple[RegistrationContext, ...]:
    """Return the oldest submitted applications first."""
    member_ids = (
        await session.scalars(
            select(RegistrationApplicationModel.member_id)
            .where(
                RegistrationApplicationModel.status == RegistrationApplicationStatus.SUBMITTED.value
            )
            .order_by(
                RegistrationApplicationModel.submitted_at,
                RegistrationApplicationModel.member_id,
            )
            .limit(max(1, min(limit, 100)))
        )
    ).all()
    contexts: list[RegistrationContext] = []
    for member_id in member_ids:
        member = await session.get(MemberModel, member_id)
        if member is not None:
            contexts.append(await _context_by_member(session, member, for_update=False))
    return tuple(contexts)


async def get_own_profile(
    session: AsyncSession,
    member_id: UUID,
) -> ProfileData | None:
    """Return an active member's own persisted profile."""
    member = await session.get(MemberModel, member_id)
    if member is None or member.status not in {
        MemberStatus.ACTIVE.value,
        MemberStatus.PAUSED.value,
    }:
        return None
    return ProfileData(
        member_id=member.id,
        display_name=member.display_name,
        city=member.city,
        timezone=member.timezone,
        short_bio=member.short_bio,
        current_goal=member.current_goal,
        help_categories=tuple(member.help_categories_json),
        skill_tags=tuple(member.skill_tags_json),
        availability=member.availability,
        credit_balance=member.credit_balance_cached,
        experience_total=member.experience_total_cached,
    )


async def add_registration_approved_outbox(session: AsyncSession, member_id: UUID) -> None:
    """Stage the one durable notification emitted by first approval."""
    session.add(
        OutboxEventModel(
            event_type="registration.approved",
            aggregate_type="member",
            aggregate_id=member_id,
            payload_json={"member_id": str(member_id)},
            business_key=f"registration.approved:{member_id}",
        )
    )
    await session.flush()


async def get_conversation_expectation(
    session: AsyncSession,
    telegram_user_id: int,
) -> tuple[str, str] | None:
    """Return the persisted flow and expected step for one member."""
    row = await session.execute(
        select(ConversationStateModel.flow_type, ConversationStateModel.current_step)
        .join(MemberModel, MemberModel.id == ConversationStateModel.member_id)
        .where(MemberModel.telegram_user_id == telegram_user_id)
        .where(ConversationStateModel.flow_type.in_(("registration", "profile_edit")))
    )
    result = row.one_or_none()
    return None if result is None else (result[0], result[1])


async def resume_registration_conversation(session: AsyncSession, member_id: UUID) -> None:
    """Resume a paused registration while preserving its exact step and payload."""
    state = await session.get(ConversationStateModel, member_id)
    if state is not None and state.flow_type == "registration_paused":
        state.flow_type = "registration"
        state.updated_at = datetime.now(UTC)
        await session.flush()


async def cancel_conversation(session: AsyncSession, member_id: UUID) -> bool:
    """Pause onboarding or discard only the unfinished profile-edit prompt."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if state is None or state.flow_type == "registration_paused":
        return False
    if state.flow_type == "profile_edit":
        await session.delete(state)
    else:
        state.flow_type = "registration_paused"
        state.updated_at = datetime.now(UTC)
    await session.flush()
    return True


async def begin_profile_edit(
    session: AsyncSession,
    member_id: UUID,
    field: ProfileField,
) -> None:
    """Upsert the profile field expected from the next update."""
    state = await session.get(ConversationStateModel, member_id)
    if state is None:
        state = ConversationStateModel(
            member_id=member_id,
            flow_type="profile_edit",
            current_step=field.value,
            payload_json={},
        )
        session.add(state)
    else:
        state.flow_type = "profile_edit"
        state.current_step = field.value
        state.payload_json = {}
        state.updated_at = datetime.now(UTC)
    await session.flush()


async def save_profile_edit(
    session: AsyncSession,
    *,
    member_id: UUID,
    expected_field: ProfileField,
    value: object,
) -> None:
    """Save one profile field only if the locked edit state matches."""
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if (
        state is None
        or state.flow_type != "profile_edit"
        or state.current_step != expected_field.value
    ):
        message = "Profile edit step is stale."
        raise RegistrationError(message)
    member = await session.get(MemberModel, member_id)
    if member is None:
        message = "Profile member does not exist."
        raise LookupError(message)
    _set_member_profile_field(member, expected_field, value)
    await session.execute(
        delete(ConversationStateModel).where(ConversationStateModel.member_id == member_id)
    )
    await session.flush()


async def _context_by_member(
    session: AsyncSession,
    member: MemberModel,
    *,
    for_update: bool,
) -> RegistrationContext:
    if member.status == MemberStatus.ACTIVE.value:
        return RegistrationContext(
            member_id=member.id,
            telegram_user_id=member.telegram_user_id,
            telegram_username=member.telegram_username,
            member_status=MemberStatus.ACTIVE,
            application_status=RegistrationApplicationStatus.APPROVED,
            current_step=RegistrationStep.SUBMITTED,
            payload={},
            review_comment=None,
        )
    application_statement = select(RegistrationApplicationModel).where(
        RegistrationApplicationModel.member_id == member.id
    )
    state_statement = select(ConversationStateModel).where(
        ConversationStateModel.member_id == member.id
    )
    if for_update:
        application_statement = application_statement.with_for_update()
        state_statement = state_statement.with_for_update()
    application = await session.scalar(application_statement)
    state = await session.scalar(state_statement)
    if (
        application is not None
        and application.status == RegistrationApplicationStatus.APPROVED.value
    ):
        return RegistrationContext(
            member_id=member.id,
            telegram_user_id=member.telegram_user_id,
            telegram_username=member.telegram_username,
            member_status=MemberStatus(member.status),
            application_status=RegistrationApplicationStatus.APPROVED,
            current_step=RegistrationStep.SUBMITTED,
            payload={},
            review_comment=application.review_comment,
        )
    if application is None or state is None:
        message = "Member registration records are incomplete."
        raise RegistrationError(message)
    return _registration_context(member, application, state)


async def _locked_registration_rows(
    session: AsyncSession,
    member_id: UUID,
) -> tuple[MemberModel, RegistrationApplicationModel, ConversationStateModel]:
    member = await session.scalar(
        select(MemberModel).where(MemberModel.id == member_id).with_for_update()
    )
    application = await session.scalar(
        select(RegistrationApplicationModel)
        .where(RegistrationApplicationModel.member_id == member_id)
        .with_for_update()
    )
    state = await session.scalar(
        select(ConversationStateModel)
        .where(ConversationStateModel.member_id == member_id)
        .with_for_update()
    )
    if member is None or application is None or state is None:
        message = "Registration records are incomplete."
        raise RegistrationError(message)
    return member, application, state


def _registration_context(
    member: MemberModel,
    application: RegistrationApplicationModel,
    state: ConversationStateModel,
) -> RegistrationContext:
    return RegistrationContext(
        member_id=member.id,
        telegram_user_id=member.telegram_user_id,
        telegram_username=member.telegram_username,
        member_status=MemberStatus(member.status),
        application_status=RegistrationApplicationStatus(application.status),
        current_step=RegistrationStep(state.current_step),
        payload=dict(state.payload_json),
        review_comment=application.review_comment,
    )


def _invitation_snapshot(model: InvitationModel) -> InvitationSnapshot:
    return InvitationSnapshot(
        id=model.id,
        created_by_member_id=model.created_by_member_id,
        intended_telegram_user_id=model.intended_telegram_user_id,
        max_uses=model.max_uses,
        uses_count=model.uses_count,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
    )


def _copy_payload_to_member(member: MemberModel, payload: dict[str, object]) -> None:
    member.display_name = str(payload[ProfileField.DISPLAY_NAME.value])
    member.city = str(payload[ProfileField.CITY.value])
    member.timezone = str(payload[ProfileField.TIMEZONE.value])
    member.short_bio = str(payload[ProfileField.SHORT_BIO.value])
    member.current_goal = str(payload[ProfileField.CURRENT_GOAL.value])
    member.help_categories_json = _string_list(payload[ProfileField.HELP_CATEGORIES.value])
    member.skill_tags_json = _string_list(payload[ProfileField.SKILL_TAGS.value])
    member.availability = str(payload[ProfileField.AVAILABILITY.value])


def _set_member_profile_field(
    member: MemberModel,
    field: ProfileField,
    value: object,
) -> None:
    if field is ProfileField.HELP_CATEGORIES:
        member.help_categories_json = _string_list(value)
    elif field is ProfileField.SKILL_TAGS:
        member.skill_tags_json = _string_list(value)
    else:
        setattr(member, field.value, value)


def _fallback_display_name(value: str) -> str:
    normalized = " ".join(value.split())[:80]
    return normalized or "New member"


def _optional_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())[:maximum]
    return normalized or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        message = "Profile list payload is invalid."
        raise RegistrationError(message)
    return list(value)
