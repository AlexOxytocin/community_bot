"""Application services for karma, safe profiles, statistics, and leaderboard."""

# ruff: noqa: D102 - protocol method names form the storage contract.

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from community_bot.domain.members import MemberStatus
from community_bot.domain.moderation import RestrictedAction
from community_bot.domain.reputation import (
    KarmaStep,
    ProfileUnavailableError,
    normalize_karma_vote,
    require_karma_actor,
    require_profile_visible,
    require_raw_karma_read,
)

if TYPE_CHECKING:
    import datetime
    from contextlib import AbstractAsyncContextManager
    from decimal import Decimal

    from community_bot.application.identity import ActorContext
    from community_bot.application.member_foundation import UpdateReceipt
    from community_bot.domain.economy import ResolvedLevel
    from community_bot.domain.members import Member

_PROFILE_UNAVAILABLE = "Profile unavailable."
MEMBER_SEARCH_MIN_LENGTH = 3


@dataclass(frozen=True, slots=True)
class KarmaDraft:
    """One locked resumable karma conversation."""

    member_id: UUID
    target_id: UUID
    value: int | None
    comment: str | None
    step: KarmaStep
    revision: int


@dataclass(frozen=True, slots=True)
class KarmaVoteResult:
    """Persisted outcome of one karma vote revision."""

    vote_id: UUID
    revision: int
    aggregate_score: int
    aggregate_count: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class KarmaAggregate:
    """Anonymous current karma projection."""

    score: int
    count: int


@dataclass(frozen=True, slots=True)
class RawKarmaVote:
    """Administrative raw karma projection."""

    vote_id: UUID
    rater_id: UUID
    value: int
    comment: str
    revision: int
    history: tuple[RawKarmaRevision, ...]


@dataclass(frozen=True, slots=True)
class RawKarmaRevision:
    """One immutable administrative karma revision."""

    revision: int
    old_value: int | None
    new_value: int
    old_comment: str | None
    new_comment: str
    actor_member_id: UUID
    created_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class ReliabilityView:
    """Public reliability projection."""

    accepted: int
    approved_weight: Decimal
    no_show: int
    rate: Decimal | None


@dataclass(frozen=True, slots=True)
class SafeProfile:
    """Profile projection that never contains raw karma authors or comments."""

    member_id: UUID
    telegram_username: str | None
    display_name: str
    city: str | None
    short_bio: str | None
    current_goal: str | None
    help_categories: tuple[str, ...]
    skill_tags: tuple[str, ...]
    availability: str | None
    experience_total: int
    level_number: int
    karma: KarmaAggregate
    reliability: ReliabilityView


@dataclass(frozen=True, slots=True)
class MemberCatalogCursor:
    """Stable keyset position in the public member catalog."""

    normalized_display_name: str
    member_id: UUID


@dataclass(frozen=True, slots=True)
class MemberCatalogPage:
    """One privacy-safe page of active member profiles."""

    items: tuple[SafeProfile, ...]
    next_cursor: MemberCatalogCursor | None


@dataclass(frozen=True, slots=True)
class PersonalStatistics:
    """Aggregated contribution facts visible to their owner."""

    completed: int
    partially_completed: int
    experience_earned: int
    unique_recipients: int
    categories: tuple[str, ...]
    no_show: int
    reliability: ReliabilityView


@dataclass(frozen=True, slots=True)
class LeaderboardCursor:
    """Complete stable keyset cursor for the main leaderboard."""

    experience: int
    recipients: int
    sufficient_sample: bool
    reliability: Decimal
    no_show: int
    reached_at: datetime.datetime
    member_id: UUID


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One privacy-safe leaderboard row."""

    rank: int
    member_id: UUID
    display_name: str
    experience: int
    unique_recipients: int
    reliability: Decimal | None
    no_show: int
    reached_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class LeaderboardPage:
    """One keyset page of leaderboard rows."""

    items: tuple[LeaderboardEntry, ...]
    next_cursor: LeaderboardCursor | None


class ReputationUnitOfWork(Protocol):  # pragma: no cover - structural typing contract.
    """Transactional persistence required by reputation workflows."""

    async def acquire_update_gate(self, update_id: int) -> None: ...
    async def acquire_registration_identity_gate(self, telegram_user_id: int) -> None: ...
    async def acquire_reputation_pair_gate(self, first_id: UUID, second_id: UUID) -> None: ...
    async def get_receipt(self, update_id: int) -> UpdateReceipt | None: ...
    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...
    async def get_member(self, member_id: UUID) -> Member | None: ...
    async def ensure_moderation_action_allowed(
        self, member_id: UUID, action: RestrictedAction
    ) -> None: ...
    async def lock_members(self, member_ids: tuple[UUID, ...]) -> dict[UUID, Member]: ...
    async def karma_eligible(self, first_id: UUID, second_id: UUID) -> bool: ...
    async def get_karma_draft(self, member_id: UUID, *, for_update: bool) -> KarmaDraft | None: ...
    async def begin_karma_draft(self, member_id: UUID, target_id: UUID) -> KarmaDraft: ...
    async def save_karma_draft(
        self,
        *,
        member_id: UUID,
        expected_revision: int,
        value: int | None,
        comment: str | None,
        step: KarmaStep,
    ) -> KarmaDraft: ...
    async def delete_karma_draft(self, member_id: UUID, expected_revision: int) -> None: ...
    async def upsert_karma_vote(
        self,
        *,
        rater_id: UUID,
        target_id: UUID,
        value: int,
        comment: str,
        command_id: UUID,
    ) -> KarmaVoteResult: ...

    async def generate_karma_signals(self, vote_id: UUID) -> None: ...
    async def karma_vote_by_command(self, command_id: UUID) -> KarmaVoteResult | None: ...
    async def karma_aggregate(self, target_id: UUID) -> KarmaAggregate: ...
    async def safe_profile(self, member_id: UUID) -> SafeProfile | None: ...
    async def member_catalog_cursor(
        self, member_id: UUID, *, query: str | None
    ) -> MemberCatalogCursor | None: ...
    async def safe_profiles(
        self, *, limit: int, cursor: MemberCatalogCursor | None, query: str | None
    ) -> MemberCatalogPage: ...
    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel: ...
    async def personal_statistics(self, member_id: UUID) -> PersonalStatistics: ...
    async def raw_karma(self, target_id: UUID) -> tuple[RawKarmaVote, ...]: ...
    async def leaderboard(
        self, *, limit: int, cursor: LeaderboardCursor | None
    ) -> LeaderboardPage: ...
    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None: ...
    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None: ...
    async def commit(self) -> None: ...


class ReputationUnitOfWorkFactory(Protocol):  # pragma: no cover - structural typing contract.
    """Create isolated reputation transactions."""

    def __call__(self) -> AbstractAsyncContextManager[ReputationUnitOfWork]: ...


class ReputationService:
    """Orchestrate server-authorized reputation and profile operations."""

    def __init__(self, unit_of_work_factory: ReputationUnitOfWorkFactory) -> None:
        """Configure the transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def begin_vote(
        self,
        *,
        update_id: int,
        telegram_user_id: int | None = None,
        target_id: UUID,
        actor_member_id: UUID | None = None,
        replay_fingerprint: str | None = None,
    ) -> KarmaDraft:
        """Create or resume a karma draft without overwriting another flow."""
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            actor = await self._locked_active_actor(
                uow,
                telegram_user_id=telegram_user_id,
                actor_member_id=actor_member_id,
            )
            await uow.acquire_reputation_pair_gate(actor.id, target_id)
            await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.KARMA_VOTE)
            receipt = await uow.get_receipt(update_id)
            if receipt is not None:
                if actor_member_id is not None:
                    return _web_draft_replay(
                        receipt.outcome_code,
                        action="begin",
                        actor_id=actor.id,
                        target_id=target_id,
                        fingerprint=_required_web_fingerprint(replay_fingerprint),
                    )
                draft = await uow.get_karma_draft(actor.id, for_update=False)
                if draft is None:
                    message = "Stored karma draft is no longer current."
                    raise ReputationError(message)
                return draft
            members = await uow.lock_members((actor.id, target_id))
            actor, target = members[actor.id], members[target_id]
            require_karma_actor(
                actor, target, eligible=await uow.karma_eligible(actor.id, target.id)
            )
            draft = await uow.begin_karma_draft(actor.id, target.id)
            outcome = (
                _web_draft_outcome("begin", actor.id, draft, replay_fingerprint)
                if actor_member_id is not None
                else f"karma_draft:{draft.target_id}:{draft.revision}"
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="karma_web" if actor_member_id is not None else "karma_begin",
                actor_id=actor.id,
                outcome_code=outcome,
            )
            await uow.commit()
            return draft

    async def save_value(  # noqa: PLR0913 - legacy and actor-native identities share one use case.
        self,
        *,
        update_id: int,
        telegram_user_id: int | None = None,
        expected_revision: int,
        value: int,
        target_id: UUID | None = None,
        actor_member_id: UUID | None = None,
        replay_fingerprint: str | None = None,
    ) -> KarmaDraft:
        """Persist a draft value through the exact state revision."""
        if value not in {-1, 0, 1}:
            normalize_karma_vote(value, "0123456789")
        return await self._save_draft(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            expected_revision=expected_revision,
            value=value,
            comment=None,
            step=KarmaStep.COMMENT,
            target_id=target_id,
            actor_member_id=actor_member_id,
            replay_fingerprint=replay_fingerprint,
            action="save_value",
        )

    async def save_comment(  # noqa: PLR0913 - legacy and actor-native identities share one use case.
        self,
        *,
        update_id: int,
        telegram_user_id: int | None = None,
        expected_revision: int,
        comment: str,
        target_id: UUID | None = None,
        actor_member_id: UUID | None = None,
        replay_fingerprint: str | None = None,
    ) -> KarmaDraft:
        """Persist a normalized draft comment and advance to preview."""
        _, normalized = normalize_karma_vote(0, comment)
        return await self._save_draft(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            expected_revision=expected_revision,
            value=None,
            comment=normalized,
            step=KarmaStep.PREVIEW,
            target_id=target_id,
            actor_member_id=actor_member_id,
            replay_fingerprint=replay_fingerprint,
            action="save_comment",
        )

    async def confirm_vote(  # noqa: PLR0913 - exact Web replay extends the legacy command.
        self,
        *,
        update_id: int,
        telegram_user_id: int | None = None,
        expected_revision: int,
        command_id: UUID | None = None,
        target_id: UUID | None = None,
        actor_member_id: UUID | None = None,
        replay_fingerprint: str | None = None,
    ) -> KarmaVoteResult:
        """Atomically apply one complete draft and delete its conversation state."""
        command_id = command_id or uuid5(NAMESPACE_URL, f"karma:{update_id}")
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            if actor_member_id is None:
                receipt = await uow.get_receipt(update_id)
                if receipt is not None:
                    stored = await uow.karma_vote_by_command(command_id)
                    if stored is None:
                        message = "Stored karma receipt does not match the command."
                        raise ReputationError(message)
                    return replace(stored, replayed=True)
            actor = await self._locked_active_actor(
                uow,
                telegram_user_id=telegram_user_id,
                actor_member_id=actor_member_id,
            )
            receipt = await uow.get_receipt(update_id)
            if receipt is not None:
                return _web_vote_replay(
                    receipt.outcome_code,
                    actor_id=actor.id,
                    target_id=_required_web_target(target_id),
                    fingerprint=_required_web_fingerprint(replay_fingerprint),
                )
            draft = await uow.get_karma_draft(actor.id, for_update=True)
            if (
                draft is None
                or draft.step is not KarmaStep.PREVIEW
                or draft.revision != expected_revision
                or draft.value is None
                or draft.comment is None
                or (target_id is not None and draft.target_id != target_id)
            ):
                message = "Karma draft is stale or incomplete."
                raise ReputationError(message)
            await uow.acquire_reputation_pair_gate(actor.id, draft.target_id)
            if actor_member_id is not None:
                await uow.ensure_moderation_action_allowed(actor.id, RestrictedAction.KARMA_VOTE)
            members = await uow.lock_members((actor.id, draft.target_id))
            actor, target = members[actor.id], members[draft.target_id]
            require_karma_actor(
                actor, target, eligible=await uow.karma_eligible(actor.id, target.id)
            )
            value, comment = normalize_karma_vote(draft.value, draft.comment)
            result = await uow.upsert_karma_vote(
                rater_id=actor.id,
                target_id=target.id,
                value=value,
                comment=comment,
                command_id=command_id,
            )
            await uow.generate_karma_signals(result.vote_id)
            await uow.delete_karma_draft(actor.id, expected_revision)
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="karma_vote_saved",
                entity_type="member",
                entity_id=str(target.id),
                reason=None,
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="karma_web" if actor_member_id is not None else "karma_confirm",
                actor_id=actor.id,
                outcome_code=(
                    _web_vote_outcome(actor.id, target.id, result, replay_fingerprint)
                    if actor_member_id is not None
                    else f"karma_vote:{command_id}"
                ),
            )
            await uow.commit()
            return result

    async def cancel_vote(self, *, update_id: int, telegram_user_id: int) -> bool:
        """Idempotently cancel only a karma flow and delegate every other flow."""
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            await uow.acquire_registration_identity_gate(telegram_user_id)
            actor = await self._active_actor(uow, telegram_user_id)
            receipt = await uow.get_receipt(update_id)
            expected_outcome = f"karma_cancelled:{actor.id}"
            if receipt is not None:
                if receipt.outcome_code != expected_outcome:
                    message = "Stored update outcome does not match karma cancellation."
                    raise ReputationError(message)
                return True
            draft = await uow.get_karma_draft(actor.id, for_update=True)
            if draft is None:
                return False
            await uow.delete_karma_draft(actor.id, draft.revision)
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="karma_cancelled",
                entity_type="member",
                entity_id=str(actor.id),
                reason=None,
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="karma_cancel",
                actor_id=actor.id,
                outcome_code=expected_outcome,
            )
            await uow.commit()
            return True

    async def profile(self, *, actor: ActorContext, target_id: UUID | None = None) -> SafeProfile:
        """Return one server-authorized safe profile projection."""
        async with self._unit_of_work_factory() as uow:
            member = await self._context_actor(uow, actor)
            target_id = member.id if target_id is None else target_id
            target = await uow.get_member(target_id)
            require_profile_visible(member, target)
            profile = await uow.safe_profile(target_id)
            if profile is None:
                raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
            level = await uow.resolve_member_level(target_id)
            return replace(profile, level_number=level.level_number)

    async def statistics(self, telegram_user_id: int) -> PersonalStatistics:
        """Return personal contribution statistics for active or paused owner."""
        async with self._unit_of_work_factory() as uow:
            actor = await self._actor(uow, telegram_user_id)
            require_profile_visible(actor, actor)
            return await uow.personal_statistics(actor.id)

    async def members(
        self,
        *,
        actor: ActorContext,
        limit: int = 50,
        cursor: MemberCatalogCursor | None = None,
        cursor_member_id: UUID | None = None,
        query: str | None = None,
    ) -> MemberCatalogPage:
        """Return the safe active-member catalog to an active actor."""
        normalized_query = normalize_member_search_query(query)
        async with self._unit_of_work_factory() as uow:
            await self._active_context_actor(uow, actor)
            if cursor is None and cursor_member_id is not None:
                cursor = await uow.member_catalog_cursor(cursor_member_id, query=normalized_query)
            page = await uow.safe_profiles(
                limit=max(1, min(limit, 100)),
                cursor=cursor,
                query=normalized_query,
            )
            profiles = []
            for profile in page.items:
                level = await uow.resolve_member_level(profile.member_id)
                profiles.append(replace(profile, level_number=level.level_number))
            return replace(page, items=tuple(profiles))

    async def raw_karma(
        self, *, update_id: int, telegram_user_id: int, target_id: UUID
    ) -> tuple[RawKarmaVote, ...]:
        """Return administrative raw karma and append an audit event atomically."""
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            actor = await self._actor(uow, telegram_user_id)
            target = await uow.get_member(target_id)
            if target is None:
                raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
            require_raw_karma_read(actor, target)
            receipt = await uow.get_receipt(update_id)
            expected_outcome = f"karma_raw_viewed:{target_id}"
            if receipt is not None:
                if receipt.outcome_code != expected_outcome:
                    message = "Stored update outcome does not match raw karma view."
                    raise ReputationError(message)
                return await uow.raw_karma(target_id)
            rows = await uow.raw_karma(target_id)
            await uow.append_audit_event(
                actor_member_id=actor.id,
                action="karma_raw_viewed",
                entity_type="member",
                entity_id=str(target_id),
                reason=None,
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="karma_raw_view",
                actor_id=actor.id,
                outcome_code=expected_outcome,
            )
            await uow.commit()
            return rows

    async def leaderboard(
        self,
        *,
        actor: ActorContext,
        limit: int = 20,
        cursor: LeaderboardCursor | None = None,
    ) -> LeaderboardPage:
        """Return the main contribution leaderboard to an active member."""
        async with self._unit_of_work_factory() as uow:
            await self._active_context_actor(uow, actor)
            return await uow.leaderboard(limit=max(1, min(limit, 100)), cursor=cursor)

    async def _save_draft(  # noqa: PLR0913 - explicit state fields form the revision gate.
        self,
        *,
        update_id: int,
        telegram_user_id: int | None,
        expected_revision: int,
        value: int | None,
        comment: str | None,
        step: KarmaStep,
        target_id: UUID | None,
        actor_member_id: UUID | None,
        replay_fingerprint: str | None,
        action: str,
    ) -> KarmaDraft:
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            actor = await self._locked_active_actor(
                uow,
                telegram_user_id=telegram_user_id,
                actor_member_id=actor_member_id,
            )
            receipt = await uow.get_receipt(update_id)
            if receipt is not None:
                if actor_member_id is not None:
                    return _web_draft_replay(
                        receipt.outcome_code,
                        action=action,
                        actor_id=actor.id,
                        target_id=_required_web_target(target_id),
                        fingerprint=_required_web_fingerprint(replay_fingerprint),
                    )
                draft = await uow.get_karma_draft(actor.id, for_update=False)
                if draft is None:
                    message = "Stored karma draft is no longer current."
                    raise ReputationError(message)
                return draft
            draft = await uow.get_karma_draft(actor.id, for_update=True)
            if draft is None or (target_id is not None and draft.target_id != target_id):
                message = "Karma draft does not exist."
                raise ReputationError(message)
            saved = await uow.save_karma_draft(
                member_id=actor.id,
                expected_revision=expected_revision,
                value=draft.value if value is None else value,
                comment=draft.comment if comment is None else comment,
                step=step,
            )
            await uow.add_receipt(
                update_id=update_id,
                update_type="karma_web" if actor_member_id is not None else "karma_draft",
                actor_id=actor.id,
                outcome_code=(
                    _web_draft_outcome(action, actor.id, saved, replay_fingerprint)
                    if actor_member_id is not None
                    else f"karma_draft:{saved.target_id}:{saved.revision}"
                ),
            )
            await uow.commit()
            return saved

    async def _actor(self, uow: ReputationUnitOfWork, telegram_user_id: int) -> Member:
        actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
        if actor is None:
            raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
        return actor

    async def _active_actor(self, uow: ReputationUnitOfWork, telegram_user_id: int) -> Member:
        actor = await self._actor(uow, telegram_user_id)
        if actor.status is not MemberStatus.ACTIVE:
            raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
        return actor

    async def _locked_active_actor(
        self,
        uow: ReputationUnitOfWork,
        *,
        telegram_user_id: int | None,
        actor_member_id: UUID | None,
    ) -> Member:
        """Resolve one legacy or Web actor under the shared identity gate."""
        if actor_member_id is not None:
            if telegram_user_id is not None:
                message = "Karma actor identity is ambiguous."
                raise PermissionError(message)
            actor = await uow.get_member(actor_member_id)
            if actor is None:
                raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
            await uow.acquire_registration_identity_gate(actor.telegram_user_id)
            actor = await uow.get_member(actor_member_id)
            if actor is None or actor.status is not MemberStatus.ACTIVE:
                raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
            return actor
        if telegram_user_id is None:
            message = "Karma actor identity is missing."
            raise PermissionError(message)
        await uow.acquire_registration_identity_gate(telegram_user_id)
        return await self._active_actor(uow, telegram_user_id)

    async def _context_actor(self, uow: ReputationUnitOfWork, context: ActorContext) -> Member:
        actor = await uow.get_member(context.member_id)
        if actor is None:
            raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
        return actor

    async def _active_context_actor(
        self, uow: ReputationUnitOfWork, context: ActorContext
    ) -> Member:
        actor = await self._context_actor(uow, context)
        if actor.status is not MemberStatus.ACTIVE:
            raise ProfileUnavailableError(_PROFILE_UNAVAILABLE)
        return actor


class ReputationError(ValueError):
    """Application-level malformed or stale reputation command."""


def _required_web_target(target_id: UUID | None) -> UUID:
    if target_id is None:
        message = "Web karma target is missing."
        raise ReputationError(message)
    return target_id


def _required_web_fingerprint(fingerprint: str | None) -> str:
    if fingerprint is None or ":" in fingerprint:
        message = "Web karma fingerprint is invalid."
        raise ReputationError(message)
    return fingerprint


def _web_draft_outcome(
    action: str,
    actor_id: UUID,
    draft: KarmaDraft,
    fingerprint: str | None,
) -> str:
    return ":".join(
        (
            "karma_web_v1",
            "draft",
            action,
            str(actor_id),
            str(draft.target_id),
            draft.step.value,
            str(draft.revision),
            _required_web_fingerprint(fingerprint),
        )
    )


def _web_draft_replay(
    outcome: str,
    *,
    action: str,
    actor_id: UUID,
    target_id: UUID,
    fingerprint: str,
) -> KarmaDraft:
    try:
        marker, kind, stored_action, raw_actor, raw_target, raw_step, raw_revision, stored = (
            outcome.split(":", 7)
        )
        stored_actor = UUID(raw_actor)
        stored_target = UUID(raw_target)
        step = KarmaStep(raw_step)
        revision = int(raw_revision)
    except (TypeError, ValueError) as error:
        message = "Stored karma outcome does not match command."
        raise ReputationError(message) from error
    if (
        marker != "karma_web_v1"
        or kind != "draft"
        or stored_action != action
        or stored_actor != actor_id
        or stored_target != target_id
        or stored != fingerprint
    ):
        message = "Stored karma outcome does not match command."
        raise ReputationError(message)
    return KarmaDraft(actor_id, target_id, None, None, step, revision)


def _web_vote_outcome(
    actor_id: UUID,
    target_id: UUID,
    result: KarmaVoteResult,
    fingerprint: str | None,
) -> str:
    return ":".join(
        (
            "karma_web_v1",
            "confirm",
            str(actor_id),
            str(target_id),
            str(result.vote_id),
            str(result.revision),
            str(result.aggregate_score),
            str(result.aggregate_count),
            _required_web_fingerprint(fingerprint),
        )
    )


def _web_vote_replay(
    outcome: str,
    *,
    actor_id: UUID,
    target_id: UUID,
    fingerprint: str,
) -> KarmaVoteResult:
    try:
        (
            marker,
            kind,
            raw_actor,
            raw_target,
            raw_vote,
            raw_revision,
            raw_score,
            raw_count,
            stored,
        ) = outcome.split(":", 8)
        parsed = (
            UUID(raw_actor),
            UUID(raw_target),
            UUID(raw_vote),
            int(raw_revision),
            int(raw_score),
            int(raw_count),
        )
    except (TypeError, ValueError) as error:
        message = "Stored karma outcome does not match command."
        raise ReputationError(message) from error
    stored_actor, stored_target, vote_id, revision, score, count = parsed
    if (
        marker != "karma_web_v1"
        or kind != "confirm"
        or stored_actor != actor_id
        or stored_target != target_id
        or stored != fingerprint
    ):
        message = "Stored karma outcome does not match command."
        raise ReputationError(message)
    return KarmaVoteResult(vote_id, revision, score, count, replayed=True)


def normalize_member_search_query(query: str | None) -> str | None:
    """Normalize an optional member search string for public catalog lookup."""
    raw_query = (query or "").strip()
    if not raw_query:
        return None
    normalized = " ".join(raw_query.lstrip("@").split()).casefold()
    if len(normalized) < MEMBER_SEARCH_MIN_LENGTH:
        message = "Member search query must contain at least 3 characters."
        raise ValueError(message)
    return normalized
