"""PostgreSQL persistence for invitations, registration, and own profiles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import aliased

from community_bot.application.registration import (
    InvitationOverview,
    InvitationSnapshot,
    MembershipResource,
    ProfileAvatar,
    ProfileData,
    RegistrationContext,
)
from community_bot.domain.members import MemberStatus
from community_bot.domain.registration import (
    ModerationDecision,
    ProfileField,
    ProfileLink,
    ProfileLinkAction,
    ProfileLinkCommand,
    RegistrationApplicationStatus,
    RegistrationError,
    RegistrationStep,
)
from community_bot.infrastructure.db.models import (
    CommunityRegistrationPolicyModel,
    ConversationStateModel,
    InvitationMembershipResourceModel,
    InvitationModel,
    InvitationRedemptionModel,
    MemberAvatarModel,
    MemberModel,
    MemberNotificationPreferencesModel,
    MembershipResourceModel,
    OutboxEventModel,
    RegistrationApplicationModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_IDENTITY_GATE_NAMESPACE = "registration_identity"
_MAX_PROFILE_LINKS = 5
_REQUIRED_PROFILE_FIELDS = {
    "consent",
    ProfileField.DISPLAY_NAME.value,
    ProfileField.CITY.value,
    ProfileField.TIMEZONE.value,
}


async def get_profile_avatar(session: AsyncSession, member_id: UUID) -> ProfileAvatar | None:
    """Return one normalized member-owned avatar."""
    model = await session.get(MemberAvatarModel, member_id)
    if model is None:
        return None
    return ProfileAvatar(model.content, model.content_type, model.revision)


async def upsert_profile_avatar(
    session: AsyncSession,
    *,
    member_id: UUID,
    content: bytes,
    content_type: str,
) -> ProfileAvatar:
    """Insert or replace an avatar while preserving an idempotent revision."""
    model = await session.scalar(
        select(MemberAvatarModel).where(MemberAvatarModel.member_id == member_id).with_for_update()
    )
    if model is None:
        model = MemberAvatarModel(
            member_id=member_id,
            content=content,
            content_type=content_type,
            revision=1,
        )
        session.add(model)
    elif model.content != content or model.content_type != content_type:
        model.content = content
        model.content_type = content_type
        model.revision += 1
    await session.flush()
    return ProfileAvatar(model.content, model.content_type, model.revision)


async def delete_profile_avatar(session: AsyncSession, member_id: UUID) -> bool:
    """Delete a member-owned avatar if it exists."""
    model = await session.scalar(
        select(MemberAvatarModel).where(MemberAvatarModel.member_id == member_id).with_for_update()
    )
    if model is None:
        return False
    await session.delete(model)
    await session.flush()
    return True


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
    intended_telegram_username: str | None,
    max_uses: int,
    expires_at: datetime | None,
) -> UUID:
    """Insert one invitation without retaining its open token."""
    invitation = InvitationModel(
        id=uuid.uuid4(),
        code_hash=code_hash,
        created_by_member_id=created_by_member_id,
        intended_telegram_user_id=intended_telegram_user_id,
        intended_telegram_username=intended_telegram_username,
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
    if invitation.revoked_at is not None or invitation.uses_count > 0:
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


async def attach_invitation_resources(
    session: AsyncSession,
    invitation_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> None:
    """Attach only currently active resource rows to a new invitation."""
    if not resource_ids:
        return
    resources = tuple(
        await session.scalars(
            select(MembershipResourceModel).where(
                MembershipResourceModel.id.in_(resource_ids),
                MembershipResourceModel.is_active.is_(True),
            )
        )
    )
    if len(resources) != len(resource_ids):
        message = "A selected membership resource is unavailable."
        raise RegistrationError(message)
    session.add_all(
        InvitationMembershipResourceModel(invitation_id=invitation_id, resource_id=resource_id)
        for resource_id in resource_ids
    )
    await session.flush()


async def list_membership_resources(
    session: AsyncSession,
) -> tuple[MembershipResource, ...]:
    """Return active resources in deterministic creation order."""
    models = tuple(
        await session.scalars(
            select(MembershipResourceModel)
            .where(MembershipResourceModel.is_active.is_(True))
            .order_by(MembershipResourceModel.created_at, MembershipResourceModel.id)
        )
    )
    return tuple(_membership_resource(model) for model in models)


async def create_membership_resource(  # noqa: PLR0913 - mirrors persisted resource fields.
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_username: str | None,
    title: str,
    join_url: str,
    created_by_member_id: UUID,
) -> MembershipResource:
    """Persist one Telegram resource after external verification."""
    model = MembershipResourceModel(
        id=uuid.uuid4(),
        telegram_chat_id=telegram_chat_id,
        telegram_username=telegram_username,
        title=title,
        join_url=join_url,
        created_by_member_id=created_by_member_id,
    )
    session.add(model)
    await session.flush()
    return _membership_resource(model)


async def membership_resources_for_invitation(
    session: AsyncSession,
    invitation_id: UUID,
) -> tuple[MembershipResource, ...]:
    """Return active resources selected for one invitation."""
    models = tuple(
        await session.scalars(
            select(MembershipResourceModel)
            .join(
                InvitationMembershipResourceModel,
                InvitationMembershipResourceModel.resource_id == MembershipResourceModel.id,
            )
            .where(
                InvitationMembershipResourceModel.invitation_id == invitation_id,
                MembershipResourceModel.is_active.is_(True),
            )
            .order_by(MembershipResourceModel.created_at, MembershipResourceModel.id)
        )
    )
    return tuple(_membership_resource(model) for model in models)


async def list_personal_invitations(
    session: AsyncSession,
    limit: int,
) -> tuple[InvitationOverview, ...]:
    """Return newest username-bound invitations with creator and redemption details."""
    creator = aliased(MemberModel)
    redeemed_member = aliased(MemberModel)
    rows = (
        await session.execute(
            select(InvitationModel, creator, InvitationRedemptionModel, redeemed_member)
            .join(creator, creator.id == InvitationModel.created_by_member_id)
            .outerjoin(
                InvitationRedemptionModel,
                InvitationRedemptionModel.invitation_id == InvitationModel.id,
            )
            .outerjoin(
                redeemed_member,
                redeemed_member.id == InvitationRedemptionModel.member_id,
            )
            .where(InvitationModel.intended_telegram_username.is_not(None))
            .order_by(InvitationModel.created_at.desc(), InvitationModel.id.desc())
            .limit(max(1, min(limit, 100)))
        )
    ).all()
    return tuple(
        InvitationOverview(
            invitation_id=invitation.id,
            intended_telegram_username=cast("str", invitation.intended_telegram_username),
            created_by_member_id=creator_model.id,
            created_by_display_name=creator_model.display_name,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            revoked_at=invitation.revoked_at,
            redeemed_at=(None if redemption is None else redemption.redeemed_at),
            redeemed_member_id=(None if redeemed is None else redeemed.id),
            redeemed_display_name=(None if redeemed is None else redeemed.display_name),
        )
        for invitation, creator_model, redemption, redeemed in rows
    )


async def invitation_for_member(
    session: AsyncSession,
    member_id: UUID,
) -> InvitationSnapshot | None:
    """Return the invitation redeemed by one member registration."""
    invitation = await session.scalar(
        select(InvitationModel)
        .join(
            InvitationRedemptionModel,
            InvitationRedemptionModel.invitation_id == InvitationModel.id,
        )
        .where(InvitationRedemptionModel.member_id == member_id)
    )
    return None if invitation is None else _invitation_snapshot(invitation)


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


async def registration_mode(session: AsyncSession) -> str:
    """Fail closed if the singleton is absent; share-lock against concurrent changes."""
    policy = await session.scalar(
        select(CommunityRegistrationPolicyModel)
        .where(CommunityRegistrationPolicyModel.id == 1)
        .with_for_update(read=True)
    )
    if policy is None:
        message = "Registration policy missing"
        raise RuntimeError(message)
    return policy.mode


def _new_member_preferences(member_id: UUID, now: datetime) -> MemberNotificationPreferencesModel:
    """Initialize new profiles only; never overwrite a returning member's choices."""
    return MemberNotificationPreferencesModel(
        member_id=member_id,
        nomad=True,
        nomad_since=now,
        important=True,
        important_since=now,
    )


async def create_simplified_registration(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    telegram_username: str | None,
    telegram_display_name: str,
) -> RegistrationContext:
    """Caller holds the identity lock and applies the ledger grant before commit."""
    now = datetime.now(UTC)
    member = MemberModel(
        id=uuid.uuid4(),
        telegram_user_id=telegram_user_id,
        telegram_username=_optional_text(telegram_username, maximum=128),
        display_name=_fallback_display_name(telegram_display_name),
        city=None,
        timezone="UTC",
        role="member",
        status="active",
        level_number=1,
        approved_at=now,
    )
    session.add(member)
    await session.flush()
    session.add(_new_member_preferences(member.id, now))
    session.add(
        RegistrationApplicationModel(
            member_id=member.id,
            status="approved",
            reviewed_at=now,
            review_comment="Simplified registration; verified community membership",
        )
    )
    await session.flush()
    return await _context_by_member(session, member, for_update=False)


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
            _new_member_preferences(member.id, datetime.now(UTC)),
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
                payload_json={
                    "_personal_invitation": invitation.intended_telegram_username is not None
                },
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


async def rewind_registration_step(
    session: AsyncSession,
    *,
    member_id: UUID,
    previous_step: RegistrationStep,
) -> RegistrationContext:
    """Move one editable registration draft back without discarding its answers."""
    member, application, state = await _locked_registration_rows(session, member_id)
    if application.status != RegistrationApplicationStatus.DRAFT.value:
        message = "Only a registration draft can move to a previous step."
        raise RegistrationError(message)
    state.current_step = previous_step.value
    state.flow_type = "registration"
    state.updated_at = datetime.now(UTC)
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


async def restart_rejected_registration(
    session: AsyncSession,
    member_id: UUID,
) -> RegistrationContext:
    """Move a rejected application back to the first editable profile field."""
    member, application, state = await _locked_registration_rows(session, member_id)
    if application.status != RegistrationApplicationStatus.REJECTED.value:
        message = "Only a rejected registration can be restarted."
        raise RegistrationError(message)
    application.status = RegistrationApplicationStatus.DRAFT.value
    state.flow_type = "registration"
    state.current_step = RegistrationStep.DISPLAY_NAME.value
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
        telegram_username=member.telegram_username,
        display_name=member.display_name,
        city=member.city,
        timezone=member.timezone,
        short_bio=member.short_bio,
        current_goal=member.current_goal,
        help_categories=tuple(member.help_categories_json),
        skill_tags=tuple(member.skill_tags_json),
        profile_links=tuple(
            ProfileLink(UUID(item["id"]), item["label"], item["url"])
            for item in member.profile_links_json
        ),
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


async def add_registration_submitted_outbox(session: AsyncSession, member_id: UUID) -> None:
    """Stage one durable notification for active registration moderators."""
    application = await session.get(RegistrationApplicationModel, member_id)
    if application is None or application.submitted_at is None:
        message = "Submitted registration does not exist."
        raise LookupError(message)
    session.add(
        OutboxEventModel(
            event_type="registration.submitted",
            aggregate_type="member",
            aggregate_id=member_id,
            payload_json={"member_id": str(member_id)},
            business_key=(
                f"registration.submitted:{member_id}:{application.submitted_at.isoformat()}"
            ),
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


async def update_profile_field(
    session: AsyncSession,
    *,
    member_id: UUID,
    field: ProfileField,
    value: object,
) -> None:
    """Set one already-authorized member field without touching conversation state."""
    member = await session.get(MemberModel, member_id)
    if member is None:
        message = "Profile member does not exist."
        raise LookupError(message)
    _set_member_profile_field(member, field, value)
    await session.flush()


async def update_profile_links(
    session: AsyncSession, *, member_id: UUID, command: ProfileLinkCommand
) -> tuple[ProfileLink, ...]:
    """Mutate an ordered JSONB link list on an already locked owner row."""
    member = await session.get(MemberModel, member_id)
    if member is None:
        message = "Profile member does not exist."
        raise LookupError(message)
    links = [dict(item) for item in member.profile_links_json]
    if command.action is ProfileLinkAction.CREATE:
        if len(links) >= _MAX_PROFILE_LINKS:
            message = "Profile cannot contain more than five links."
            raise RegistrationError(message)
        links.append(
            {
                "id": str(uuid.uuid4()),
                "label": cast("str", command.label),
                "url": cast("str", command.url),
            }
        )
    else:
        index = next(
            (index for index, item in enumerate(links) if item["id"] == str(command.link_id)),
            None,
        )
        if index is None:
            message = "Profile link does not exist."
            raise RegistrationError(message)
        if command.action is ProfileLinkAction.UPDATE:
            links[index] = {
                "id": links[index]["id"],
                "label": cast("str", command.label),
                "url": cast("str", command.url),
            }
        else:
            links.pop(index)
    member.profile_links_json = links
    await session.flush()
    return tuple(ProfileLink(UUID(item["id"]), item["label"], item["url"]) for item in links)


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
        personal_invitation=bool(state.payload_json.get("_personal_invitation", False)),
    )


def _invitation_snapshot(model: InvitationModel) -> InvitationSnapshot:
    return InvitationSnapshot(
        id=model.id,
        created_by_member_id=model.created_by_member_id,
        intended_telegram_user_id=model.intended_telegram_user_id,
        intended_telegram_username=model.intended_telegram_username,
        max_uses=model.max_uses,
        uses_count=model.uses_count,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
    )


def _membership_resource(model: MembershipResourceModel) -> MembershipResource:
    return MembershipResource(
        id=model.id,
        telegram_chat_id=model.telegram_chat_id,
        telegram_username=model.telegram_username,
        title=model.title,
        join_url=model.join_url,
    )


def _copy_payload_to_member(member: MemberModel, payload: dict[str, object]) -> None:
    member.display_name = str(payload[ProfileField.DISPLAY_NAME.value])
    member.city = str(payload[ProfileField.CITY.value])
    member.timezone = str(payload[ProfileField.TIMEZONE.value])
    short_bio = str(payload.get(ProfileField.SHORT_BIO.value, "")).strip()
    member.short_bio = short_bio or None
    member.current_goal = None
    member.help_categories_json = []
    member.skill_tags_json = _string_list(payload.get(ProfileField.SKILL_TAGS.value, ()))
    member.availability = None


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
