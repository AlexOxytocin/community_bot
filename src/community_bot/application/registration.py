"""Application services for invitations, registration moderation, and profiles."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from community_bot.application.economy import EconomyUnitOfWork
from community_bot.domain.economy import ResolvedLevel, starting_grant
from community_bot.domain.members import MemberStatus
from community_bot.domain.registration import (
    InvitationError,
    ModerationDecision,
    ProfileField,
    RegistrationApplicationStatus,
    RegistrationError,
    RegistrationStep,
    normalize_profile_value,
    normalize_registration_answer,
    require_invitation_manager,
    require_profile_owner,
    require_registration_moderator,
    resolve_timezone,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

_MIN_TOKEN_SECRET_BYTES = 32
_MAX_INVITATION_USES = 100


@dataclass(frozen=True, slots=True)
class InvitationSnapshot:
    """Locked invitation state used for deterministic validation."""

    id: UUID
    created_by_member_id: UUID
    intended_telegram_user_id: int | None
    max_uses: int
    uses_count: int
    expires_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class RegistrationContext:
    """Current persistent state of one member registration."""

    member_id: UUID
    telegram_user_id: int
    telegram_username: str | None
    member_status: MemberStatus
    application_status: RegistrationApplicationStatus
    current_step: RegistrationStep
    payload: dict[str, object]
    review_comment: str | None


@dataclass(frozen=True, slots=True)
class RegistrationView:
    """Stable application result presented by the Telegram adapter."""

    outcome_code: str
    context: RegistrationContext | None


@dataclass(frozen=True, slots=True)
class InvitationCreateCommand:
    """Create one invitation through an idempotent Telegram update."""

    update_id: int
    actor_telegram_user_id: int
    max_uses: int = 1
    expires_at: datetime | None = None
    intended_telegram_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class InvitationCreateResult:
    """Invitation identity and the open token shown only to its creator."""

    invitation_id: UUID
    token: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class RegistrationStartCommand:
    """Start or resume registration using immutable Telegram identity."""

    update_id: int
    telegram_user_id: int
    telegram_username: str | None
    telegram_display_name: str
    invitation_token: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationAnswerCommand:
    """Apply one answer only to the step for which it was collected."""

    update_id: int
    telegram_user_id: int
    expected_step: RegistrationStep
    raw_value: str


@dataclass(frozen=True, slots=True)
class ModerationCommand:
    """Approve or reject one submitted registration."""

    update_id: int
    actor_telegram_user_id: int
    target_member_id: UUID
    decision: ModerationDecision
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileData:
    """Persisted fields of an active member's own profile."""

    member_id: UUID
    display_name: str
    city: str | None
    timezone: str
    short_bio: str | None
    current_goal: str | None
    help_categories: tuple[str, ...]
    skill_tags: tuple[str, ...]
    availability: str | None
    credit_balance: int
    experience_total: int


@dataclass(frozen=True, slots=True)
class ProfileSnapshot(ProfileData):
    """Own profile card with the current resolved level."""

    level: ResolvedLevel


class RegistrationUnitOfWork(EconomyUnitOfWork, Protocol):
    """Transactional persistence required by registration workflows."""

    async def acquire_update_gate(self, update_id: int) -> None:
        """Serialize one exact Telegram update."""
        ...

    async def acquire_registration_identity_gate(self, telegram_user_id: int) -> None:
        """Serialize all registration mutations for one Telegram identity."""
        ...

    async def get_receipt_outcome(self, update_id: int) -> str | None:
        """Read an exact committed update outcome."""
        ...

    async def add_registration_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None:
        """Stage a complete Telegram receipt."""
        ...

    async def create_invitation(
        self,
        *,
        code_hash: str,
        created_by_member_id: UUID,
        intended_telegram_user_id: int | None,
        max_uses: int,
        expires_at: datetime | None,
    ) -> UUID:
        """Insert one hashed invitation."""
        ...

    async def revoke_invitation(self, invitation_id: UUID) -> bool:
        """Mark an existing invitation revoked and report whether it changed."""
        ...

    async def lock_invitation_by_hash(self, code_hash: str) -> InvitationSnapshot | None:
        """Lock one invitation by exact token hash."""
        ...

    async def get_registration_context(
        self,
        telegram_user_id: int,
        *,
        for_update: bool,
    ) -> RegistrationContext | None:
        """Read the complete registration context for a Telegram identity."""
        ...

    async def create_pending_registration(
        self,
        *,
        invitation: InvitationSnapshot,
        telegram_user_id: int,
        telegram_username: str | None,
        telegram_display_name: str,
    ) -> RegistrationContext:
        """Consume one invitation and create member, application, and state."""
        ...

    async def update_registration_username(
        self,
        *,
        member_id: UUID,
        telegram_username: str | None,
    ) -> None:
        """Update the mutable Telegram username of the same member."""
        ...

    async def resume_registration_conversation(self, member_id: UUID) -> None:
        """Resume a registration draft previously paused with `/cancel`."""
        ...

    async def cancel_conversation(self, member_id: UUID) -> bool:
        """Pause a registration draft or discard an unfinished profile edit."""
        ...

    async def save_registration_answer(
        self,
        *,
        member_id: UUID,
        field: str,
        value: object,
        next_step: RegistrationStep,
    ) -> RegistrationContext:
        """Persist one draft answer and advance the state."""
        ...

    async def submit_registration(self, member_id: UUID) -> RegistrationContext:
        """Copy the completed draft to the profile and submit it."""
        ...

    async def reopen_rejected_registration(self, member_id: UUID) -> RegistrationContext:
        """Move a rejected application back to editable preview."""
        ...

    async def lock_registration_application(self, member_id: UUID) -> RegistrationContext:
        """Lock the target application after member locks are held."""
        ...

    async def decide_registration(
        self,
        *,
        member_id: UUID,
        actor_member_id: UUID,
        decision: ModerationDecision,
        comment: str | None,
    ) -> RegistrationContext:
        """Persist the approved or rejected registration state."""
        ...

    async def list_submitted_registrations(self, limit: int) -> tuple[RegistrationContext, ...]:
        """Return oldest submitted applications first."""
        ...

    async def get_own_profile(self, telegram_user_id: int) -> ProfileData | None:
        """Return the active member profile before level resolution."""
        ...

    async def get_conversation_expectation(self, telegram_user_id: int) -> tuple[str, str] | None:
        """Return the flow and step expected from the next text update."""
        ...

    async def begin_profile_edit(self, member_id: UUID, field: ProfileField) -> None:
        """Persist the profile edit field expected from the next message."""
        ...

    async def save_profile_edit(
        self,
        *,
        member_id: UUID,
        expected_field: ProfileField,
        value: object,
    ) -> None:
        """Save one owned profile field if the locked edit state matches."""
        ...


class RegistrationUnitOfWorkFactory(Protocol):
    """Create isolated registration transactions."""

    def __call__(self) -> AbstractAsyncContextManager[RegistrationUnitOfWork]:
        """Return a fresh unit of work."""
        ...


class InviteTokenCodec:
    """Derive replayable high-entropy invite tokens and irreversible hashes."""

    def __init__(self, secret: str) -> None:
        """Validate and retain a process secret outside persistence."""
        encoded = secret.encode()
        if len(encoded) < _MIN_TOKEN_SECRET_BYTES:
            message = "Invite token secret must contain at least 32 bytes."
            raise ValueError(message)
        self._secret = encoded

    def token_for_update(self, update_id: int) -> str:
        """Return a stable opaque token for one idempotent create update."""
        digest = hmac.digest(self._secret, f"invite:{update_id}".encode(), "sha256")
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    @staticmethod
    def hash_token(token: str) -> str:
        """Return the only invitation token representation allowed in storage."""
        return hashlib.sha256(token.encode()).hexdigest()


class RegistrationService:
    """Orchestrate invitations, resumable onboarding, moderation, and profiles."""

    def __init__(
        self,
        unit_of_work_factory: RegistrationUnitOfWorkFactory,
        token_codec: InviteTokenCodec,
    ) -> None:
        """Configure persistence and token derivation."""
        self._unit_of_work_factory = unit_of_work_factory
        self._token_codec = token_codec

    async def create_invitation(
        self,
        command: InvitationCreateCommand,
    ) -> InvitationCreateResult:
        """Create one hashed invitation as an active administrator."""
        if command.max_uses < 1 or command.max_uses > _MAX_INVITATION_USES:
            message = "Invitation max uses must be between 1 and 100."
            raise InvitationError(message)
        expires_at = _utc_datetime(command.expires_at)
        if expires_at is not None and expires_at <= datetime.now(UTC):
            message = "Invitation expiry must be in the future."
            raise InvitationError(message)
        token = self._token_codec.token_for_update(command.update_id)
        code_hash = self._token_codec.hash_token(token)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            stored = await unit_of_work.get_receipt_outcome(command.update_id)
            if stored is not None:
                return InvitationCreateResult(
                    invitation_id=_outcome_uuid(stored, "invitation_created"),
                    token=token,
                    replayed=True,
                )
            actor = await unit_of_work.get_member_by_telegram_user_id(
                command.actor_telegram_user_id
            )
            if actor is None:
                message = "Invitation actor is not a registered member."
                raise PermissionError(message)
            actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
            require_invitation_manager(actor)
            invitation_id = await unit_of_work.create_invitation(
                code_hash=code_hash,
                created_by_member_id=actor.id,
                intended_telegram_user_id=command.intended_telegram_user_id,
                max_uses=command.max_uses,
                expires_at=expires_at,
            )
            outcome = f"invitation_created:{invitation_id}"
            await unit_of_work.append_audit_event(
                actor_member_id=actor.id,
                action="invitation_created",
                entity_type="invitation",
                entity_id=str(invitation_id),
                reason=None,
            )
            await unit_of_work.add_registration_receipt(
                update_id=command.update_id,
                update_type="invitation_create",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return InvitationCreateResult(invitation_id=invitation_id, token=token, replayed=False)

    async def revoke_invitation(
        self,
        *,
        update_id: int,
        actor_telegram_user_id: int,
        invitation_id: UUID,
    ) -> str:
        """Revoke an invitation idempotently as an active administrator."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                return stored
            actor = await unit_of_work.get_member_by_telegram_user_id(actor_telegram_user_id)
            if actor is None:
                message = "Invitation actor is not a registered member."
                raise PermissionError(message)
            actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
            require_invitation_manager(actor)
            changed = await unit_of_work.revoke_invitation(invitation_id)
            outcome = "invitation_revoked" if changed else "invitation_already_revoked"
            await unit_of_work.append_audit_event(
                actor_member_id=actor.id,
                action=outcome,
                entity_type="invitation",
                entity_id=str(invitation_id),
                reason=None,
            )
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="invitation_revoke",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return outcome

    async def start(self, command: RegistrationStartCommand) -> RegistrationView:
        """Start or resume registration for one immutable Telegram identity."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            stored = await unit_of_work.get_receipt_outcome(command.update_id)
            if stored is not None:
                context = await unit_of_work.get_registration_context(
                    command.telegram_user_id,
                    for_update=False,
                )
                return RegistrationView(stored, context)
            await unit_of_work.acquire_registration_identity_gate(command.telegram_user_id)
            context = await unit_of_work.get_registration_context(
                command.telegram_user_id,
                for_update=True,
            )
            if context is None:
                if not command.invitation_token:
                    outcome = "invitation_required"
                    await unit_of_work.add_registration_receipt(
                        update_id=command.update_id,
                        update_type="registration_start",
                        actor_id=None,
                        outcome_code=outcome,
                    )
                    await unit_of_work.commit()
                    return RegistrationView(outcome, None)
                invitation = await unit_of_work.lock_invitation_by_hash(
                    self._token_codec.hash_token(command.invitation_token)
                )
                invitation = _validated_invitation(invitation, command.telegram_user_id)
                context = await unit_of_work.create_pending_registration(
                    invitation=invitation,
                    telegram_user_id=command.telegram_user_id,
                    telegram_username=command.telegram_username,
                    telegram_display_name=command.telegram_display_name,
                )
            else:
                await unit_of_work.update_registration_username(
                    member_id=context.member_id,
                    telegram_username=command.telegram_username,
                )
                await unit_of_work.resume_registration_conversation(context.member_id)
                context = replace(context, telegram_username=command.telegram_username)
            outcome = _registration_outcome(context)
            await unit_of_work.add_registration_receipt(
                update_id=command.update_id,
                update_type="registration_start",
                actor_id=context.member_id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def cancel(self, *, update_id: int, telegram_user_id: int) -> str:
        """Cancel the current dialog without deleting a registration draft."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                return stored
            await unit_of_work.acquire_registration_identity_gate(telegram_user_id)
            actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            if actor is None:
                outcome = "conversation_absent"
                actor_id = None
            else:
                actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
                changed = await unit_of_work.cancel_conversation(actor.id)
                outcome = "conversation_cancelled" if changed else "conversation_absent"
                actor_id = actor.id
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="conversation_cancel",
                actor_id=actor_id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return outcome

    async def answer(self, command: RegistrationAnswerCommand) -> RegistrationView:
        """Persist one answer if the expected registration step is still current."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            stored = await unit_of_work.get_receipt_outcome(command.update_id)
            if stored is not None:
                context = await unit_of_work.get_registration_context(
                    command.telegram_user_id,
                    for_update=False,
                )
                return RegistrationView(stored, context)
            await unit_of_work.acquire_registration_identity_gate(command.telegram_user_id)
            context = await unit_of_work.get_registration_context(
                command.telegram_user_id,
                for_update=True,
            )
            if context is None:
                message = "Registration context does not exist."
                raise RegistrationError(message)
            expectation = await unit_of_work.get_conversation_expectation(command.telegram_user_id)
            if expectation is None:
                outcome = "conversation_paused"
            elif context.current_step is not command.expected_step:
                outcome = f"stale_step:{context.current_step.value}"
            else:
                answer = normalize_registration_answer(
                    command.expected_step,
                    command.raw_value,
                )
                context = await unit_of_work.save_registration_answer(
                    member_id=context.member_id,
                    field=answer.field,
                    value=answer.value,
                    next_step=answer.next_step,
                )
                next_step = answer.next_step
                if command.expected_step is RegistrationStep.CITY:
                    inferred_timezone = resolve_timezone(str(answer.value))
                    if inferred_timezone is not None:
                        next_step = RegistrationStep.SHORT_BIO
                        context = await unit_of_work.save_registration_answer(
                            member_id=context.member_id,
                            field=ProfileField.TIMEZONE.value,
                            value=inferred_timezone,
                            next_step=next_step,
                        )
                outcome = f"registration_step:{next_step.value}"
            await unit_of_work.add_registration_receipt(
                update_id=command.update_id,
                update_type="registration_answer",
                actor_id=context.member_id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def submit(
        self,
        *,
        update_id: int,
        telegram_user_id: int,
        expected_step: RegistrationStep = RegistrationStep.PREVIEW,
    ) -> RegistrationView:
        """Submit a completed registration draft for moderation."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                context = await unit_of_work.get_registration_context(
                    telegram_user_id,
                    for_update=False,
                )
                return RegistrationView(stored, context)
            await unit_of_work.acquire_registration_identity_gate(telegram_user_id)
            context = await unit_of_work.get_registration_context(
                telegram_user_id,
                for_update=True,
            )
            if context is None:
                message = "Registration context does not exist."
                raise RegistrationError(message)
            expectation = await unit_of_work.get_conversation_expectation(telegram_user_id)
            if expectation is None:
                outcome = "conversation_paused"
            elif context.current_step is not expected_step:
                outcome = f"stale_step:{context.current_step.value}"
            else:
                context = await unit_of_work.submit_registration(context.member_id)
                outcome = "registration_submitted"
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="registration_submit",
                actor_id=context.member_id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def reopen_rejected(
        self,
        *,
        update_id: int,
        telegram_user_id: int,
    ) -> RegistrationView:
        """Reopen a rejected registration at its preview step."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                context = await unit_of_work.get_registration_context(
                    telegram_user_id,
                    for_update=False,
                )
                return RegistrationView(stored, context)
            await unit_of_work.acquire_registration_identity_gate(telegram_user_id)
            context = await unit_of_work.get_registration_context(
                telegram_user_id,
                for_update=True,
            )
            if context is None:
                message = "Registration context does not exist."
                raise RegistrationError(message)
            expectation = await unit_of_work.get_conversation_expectation(telegram_user_id)
            if expectation is None:
                outcome = "conversation_paused"
            else:
                context = await unit_of_work.reopen_rejected_registration(context.member_id)
                outcome = "registration_step:preview"
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="registration_reopen",
                actor_id=context.member_id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def submitted_registrations(
        self,
        *,
        actor_telegram_user_id: int,
        limit: int = 20,
    ) -> tuple[RegistrationContext, ...]:
        """Return the moderation queue to an authorized actor."""
        async with self._unit_of_work_factory() as unit_of_work:
            actor = await unit_of_work.get_member_by_telegram_user_id(actor_telegram_user_id)
            if actor is None:
                message = "Moderation actor is not a registered member."
                raise PermissionError(message)
            actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
            require_registration_moderator(actor)
            return await unit_of_work.list_submitted_registrations(limit)

    async def moderate(self, command: ModerationCommand) -> RegistrationView:
        """Approve or reject one registration atomically and idempotently."""
        if command.decision is ModerationDecision.APPROVE:
            return await self._approve(command)
        return await self._reject(command)

    async def _approve(self, command: ModerationCommand) -> RegistrationView:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            stored = await unit_of_work.get_receipt_outcome(command.update_id)
            if stored is not None:
                context = await unit_of_work.lock_registration_application(command.target_member_id)
                return RegistrationView(stored, context)
            unresolved_actor = await unit_of_work.get_member_by_telegram_user_id(
                command.actor_telegram_user_id
            )
            if unresolved_actor is None:
                message = "Moderation actor is not a registered member."
                raise PermissionError(message)
            prepared = await unit_of_work.economy.prepare_batch(
                (starting_grant(command.target_member_id),),
                additional_member_ids=(unresolved_actor.id,),
            )
            actor = prepared.members[unresolved_actor.id]
            target = prepared.members[command.target_member_id]
            require_registration_moderator(actor)
            context = await unit_of_work.lock_registration_application(target.id)
            if context.application_status is RegistrationApplicationStatus.APPROVED:
                await prepared.apply()
            else:
                if (
                    target.status is not MemberStatus.PENDING
                    or context.application_status is not RegistrationApplicationStatus.SUBMITTED
                ):
                    message = "Only a submitted pending registration can be approved."
                    raise RegistrationError(message)
                await prepared.apply()
                context = await unit_of_work.decide_registration(
                    member_id=target.id,
                    actor_member_id=actor.id,
                    decision=ModerationDecision.APPROVE,
                    comment=command.comment,
                )
                await unit_of_work.append_audit_event(
                    actor_member_id=actor.id,
                    action="registration_approved",
                    entity_type="member",
                    entity_id=str(target.id),
                    reason=command.comment,
                )
            outcome = "registration_approved"
            await unit_of_work.add_registration_receipt(
                update_id=command.update_id,
                update_type="registration_approve",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def _reject(self, command: ModerationCommand) -> RegistrationView:
        comment = (command.comment or "").strip()
        if not comment:
            message = "Registration rejection requires a comment."
            raise RegistrationError(message)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            stored = await unit_of_work.get_receipt_outcome(command.update_id)
            if stored is not None:
                context = await unit_of_work.lock_registration_application(command.target_member_id)
                return RegistrationView(stored, context)
            actor = await unit_of_work.get_member_by_telegram_user_id(
                command.actor_telegram_user_id
            )
            if actor is None:
                message = "Moderation actor is not a registered member."
                raise PermissionError(message)
            members = await unit_of_work.lock_members((actor.id, command.target_member_id))
            actor = members[actor.id]
            require_registration_moderator(actor)
            context = await unit_of_work.lock_registration_application(command.target_member_id)
            if context.application_status is RegistrationApplicationStatus.REJECTED:
                outcome = "registration_rejected"
            else:
                if context.application_status is not RegistrationApplicationStatus.SUBMITTED:
                    message = "Only a submitted registration can be rejected."
                    raise RegistrationError(message)
                context = await unit_of_work.decide_registration(
                    member_id=command.target_member_id,
                    actor_member_id=actor.id,
                    decision=ModerationDecision.REJECT,
                    comment=comment,
                )
                outcome = "registration_rejected"
                await unit_of_work.append_audit_event(
                    actor_member_id=actor.id,
                    action=outcome,
                    entity_type="member",
                    entity_id=str(command.target_member_id),
                    reason=comment,
                )
            await unit_of_work.add_registration_receipt(
                update_id=command.update_id,
                update_type="registration_reject",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return RegistrationView(outcome, context)

    async def own_profile(self, telegram_user_id: int) -> ProfileSnapshot:
        """Return an active or paused member's own profile with the resolved level."""
        async with self._unit_of_work_factory() as unit_of_work:
            profile = await unit_of_work.get_own_profile(telegram_user_id)
            if profile is None:
                message = "An available own profile does not exist."
                raise PermissionError(message)
            level = await unit_of_work.resolve_member_level(profile.member_id)
            return ProfileSnapshot(
                member_id=profile.member_id,
                display_name=profile.display_name,
                city=profile.city,
                timezone=profile.timezone,
                short_bio=profile.short_bio,
                current_goal=profile.current_goal,
                help_categories=profile.help_categories,
                skill_tags=profile.skill_tags,
                availability=profile.availability,
                credit_balance=profile.credit_balance,
                experience_total=profile.experience_total,
                level=level,
            )

    async def expected_input(self, telegram_user_id: int) -> tuple[str, str] | None:
        """Return the persisted input expectation for the Telegram adapter."""
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.get_conversation_expectation(telegram_user_id)

    async def begin_profile_field_edit(
        self,
        *,
        update_id: int,
        telegram_user_id: int,
        field: ProfileField,
    ) -> str:
        """Persist the profile field expected from the next message."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                return stored
            await unit_of_work.acquire_registration_identity_gate(telegram_user_id)
            actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            if actor is None:
                message = "Profile actor is not a registered member."
                raise PermissionError(message)
            actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
            require_profile_owner(actor, actor.id)
            await unit_of_work.begin_profile_edit(actor.id, field)
            outcome = f"profile_edit:{field.value}"
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="profile_edit_begin",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return outcome

    async def save_profile_field(
        self,
        *,
        update_id: int,
        telegram_user_id: int,
        expected_field: ProfileField,
        raw_value: str,
    ) -> str:
        """Save one owned profile field through the identity/expected-step protocol."""
        value = normalize_profile_value(expected_field, raw_value)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            stored = await unit_of_work.get_receipt_outcome(update_id)
            if stored is not None:
                return stored
            await unit_of_work.acquire_registration_identity_gate(telegram_user_id)
            actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            if actor is None:
                message = "Profile actor is not a registered member."
                raise PermissionError(message)
            actor = (await unit_of_work.lock_members((actor.id,)))[actor.id]
            require_profile_owner(actor, actor.id)
            await unit_of_work.save_profile_edit(
                member_id=actor.id,
                expected_field=expected_field,
                value=value,
            )
            outcome = "profile_updated"
            await unit_of_work.append_audit_event(
                actor_member_id=actor.id,
                action=outcome,
                entity_type="member",
                entity_id=str(actor.id),
                reason=expected_field.value,
            )
            await unit_of_work.add_registration_receipt(
                update_id=update_id,
                update_type="profile_edit_save",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await unit_of_work.commit()
        return outcome


def _registration_outcome(context: RegistrationContext) -> str:
    if context.member_status is MemberStatus.ACTIVE:
        return "main_menu"
    if context.application_status is RegistrationApplicationStatus.SUBMITTED:
        return "registration_pending"
    if context.application_status is RegistrationApplicationStatus.REJECTED:
        return "registration_rejected"
    return f"registration_step:{context.current_step.value}"


def _validated_invitation(
    invitation: InvitationSnapshot | None,
    telegram_user_id: int,
) -> InvitationSnapshot:
    if invitation is None:
        message = "Invitation is invalid."
        raise InvitationError(message)
    now = datetime.now(UTC)
    if invitation.revoked_at is not None:
        message = "Invitation is revoked."
        raise InvitationError(message)
    if invitation.expires_at is not None and invitation.expires_at <= now:
        message = "Invitation is expired."
        raise InvitationError(message)
    if invitation.uses_count >= invitation.max_uses:
        message = "Invitation usage limit is exhausted."
        raise InvitationError(message)
    if (
        invitation.intended_telegram_user_id is not None
        and invitation.intended_telegram_user_id != telegram_user_id
    ):
        message = "Invitation is intended for another Telegram user."
        raise InvitationError(message)
    return invitation


def _outcome_uuid(outcome: str, prefix: str) -> UUID:
    actual_prefix, separator, raw_id = outcome.partition(":")
    if actual_prefix != prefix or not separator:
        message = "Stored update outcome does not match the requested operation."
        raise RegistrationError(message)
    return UUID(raw_id)


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        message = "Datetime values must be timezone-aware."
        raise ValueError(message)
    return value.astimezone(UTC)
