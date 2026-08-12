"""Application boundary for disputes, sanctions, alerts, and abuse signals."""

# ruff: noqa: D102, D105, D107, EM101, TRY003

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, cast

from community_bot.domain.members import Member, MemberRole, MemberStatus
from community_bot.domain.moderation import (
    AlertOutcome,
    ResolutionCode,
    RestrictedAction,
    SanctionType,
    validate_sanction,
)

if TYPE_CHECKING:
    from types import TracebackType
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModerationCase:
    """Privacy-safe current moderation case projection."""

    id: UUID
    assignment_id: UUID
    case_type: str
    status: str
    revision: int
    current_code: ResolutionCode | None
    opened_at: datetime.datetime
    resolved_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class Sanction:
    """Current sanction projection without private audit details."""

    id: UUID
    target_member_id: UUID
    sanction_type: SanctionType
    state: str
    restricted_actions: tuple[RestrictedAction, ...]
    starts_at: datetime.datetime
    ends_at: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class PaidAssignment:
    """Paid assignment available for an administrator fraud review."""

    assignment_id: UUID
    task_title: str
    performer_display_name: str
    status: str


@dataclass(frozen=True, slots=True)
class InteractionAlert:
    """Privacy-minimal open interaction alert."""

    id: UUID
    first_display_name: str
    second_display_name: str
    interaction_count: int
    threshold: int


@dataclass(frozen=True, slots=True)
class SanctionCard:
    """Active sanction with the target's display name."""

    sanction: Sanction
    target_display_name: str


@dataclass(frozen=True, slots=True)
class OpenFraudCaseCommand:
    """Open an administrator investigation for a paid assignment."""

    update_id: int
    actor_telegram_user_id: int
    assignment_id: UUID
    command_id: UUID
    reason: str
    evidence_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ResolveCaseCommand:
    """Apply one initial or appealed deterministic resolution."""

    update_id: int
    actor_telegram_user_id: int
    case_id: UUID
    command_id: UUID
    expected_revision: int
    code: ResolutionCode
    reason: str


@dataclass(frozen=True, slots=True)
class ResolutionPreview:
    """Durable Telegram resolution confirmation draft."""

    id: UUID
    case_id: UUID
    expected_revision: int
    code: ResolutionCode
    reason: str


@dataclass(frozen=True, slots=True)
class PreviewResolutionCommand:
    """Create a durable preview without applying effects."""

    update_id: int
    actor_telegram_user_id: int
    case_id: UUID
    expected_revision: int
    code: ResolutionCode
    reason: str


@dataclass(frozen=True, slots=True)
class ConfirmResolutionCommand:
    """Confirm one exact durable resolution preview."""

    update_id: int
    actor_telegram_user_id: int
    draft_id: UUID


@dataclass(frozen=True, slots=True)
class RequestAppealCommand:
    """Request the only appeal as a case party."""

    update_id: int
    actor_telegram_user_id: int
    case_id: UUID
    command_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class IssueSanctionCommand:
    """Issue one auditable sanction."""

    update_id: int
    actor_telegram_user_id: int
    target_member_id: UUID
    command_id: UUID
    sanction_type: SanctionType
    reason: str
    restricted_actions: tuple[RestrictedAction, ...] = ()
    ends_at: datetime.datetime | None = None


@dataclass(frozen=True, slots=True)
class RevokeSanctionCommand:
    """Revoke one sanction without deleting history."""

    update_id: int
    actor_telegram_user_id: int
    sanction_id: UUID
    command_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class ReviewAlertCommand:
    """Close an interaction alert and optionally apply a bounded penalty."""

    update_id: int
    actor_telegram_user_id: int
    alert_id: UUID
    command_id: UUID
    outcome: AlertOutcome
    notes: str
    penalties: tuple[tuple[UUID, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ModerateKarmaCommand:
    """Exclude or restore one exact karma vote revision."""

    update_id: int
    actor_telegram_user_id: int
    vote_id: UUID
    vote_revision: int
    command_id: UUID
    exclude: bool
    reason: str


ModerationCommand = (
    OpenFraudCaseCommand
    | ResolveCaseCommand
    | PreviewResolutionCommand
    | ConfirmResolutionCommand
    | RequestAppealCommand
    | IssueSanctionCommand
    | RevokeSanctionCommand
    | ReviewAlertCommand
    | ModerateKarmaCommand
)


class ModerationMutationPort(Protocol):
    """PostgreSQL-backed moderation operations within a caller-owned UoW."""

    async def list_cases(self, *, limit: int = 20) -> tuple[ModerationCase, ...]: ...

    async def list_paid_assignments(self, *, limit: int = 20) -> tuple[PaidAssignment, ...]: ...

    async def list_open_alerts(self, *, limit: int = 20) -> tuple[InteractionAlert, ...]: ...

    async def list_active_sanctions(self, *, limit: int = 20) -> tuple[SanctionCard, ...]: ...

    async def replay(self, outcome: str) -> object: ...

    async def open_fraud_case(
        self, command: OpenFraudCaseCommand, actor: Member
    ) -> ModerationCase: ...

    async def resolve_case(self, command: ResolveCaseCommand, actor: Member) -> ModerationCase: ...

    async def preview_resolution(
        self, command: PreviewResolutionCommand, actor: Member
    ) -> ResolutionPreview: ...

    async def confirm_resolution(
        self, command: ConfirmResolutionCommand, actor: Member
    ) -> ModerationCase: ...

    async def request_appeal(
        self, command: RequestAppealCommand, actor: Member
    ) -> ModerationCase: ...

    async def issue_sanction(self, command: IssueSanctionCommand, actor: Member) -> Sanction: ...

    async def revoke_sanction(self, command: RevokeSanctionCommand, actor: Member) -> Sanction: ...

    async def review_alert(self, command: ReviewAlertCommand, actor: Member) -> str: ...

    async def moderate_karma(self, command: ModerateKarmaCommand, actor: Member) -> str: ...


class ModerationUnitOfWork(Protocol):
    """Transaction contract shared with Telegram update receipts."""

    @property
    def moderation(self) -> ModerationMutationPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def acquire_update_gate(self, update_id: int) -> None: ...

    async def get_receipt_outcome(self, update_id: int) -> str | None: ...

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None: ...

    async def add_receipt(
        self, *, update_id: int, update_type: str, actor_id: UUID, outcome_code: str
    ) -> None: ...

    async def commit(self) -> None: ...


class ModerationUnitOfWorkFactory(Protocol):
    """Create isolated moderation transactions."""

    def __call__(self) -> ModerationUnitOfWork: ...


class ModerationService:
    """Authorize and execute Telegram moderation commands exactly once."""

    def __init__(self, unit_of_work_factory: ModerationUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def queue(self, actor_telegram_user_id: int) -> tuple[ModerationCase, ...]:
        """Return the current queue to active moderation staff."""
        async with self._unit_of_work_factory() as uow:
            actor = await _active_staff(uow, actor_telegram_user_id)
            cases = await uow.moderation.list_cases()
            return (
                cases
                if actor.role is MemberRole.ADMINISTRATOR
                else tuple(item for item in cases if item.case_type != "fraud_review")
            )

    async def is_administrator(self, actor_telegram_user_id: int) -> bool:
        """Return whether this Telegram identity is an active administrator."""
        async with self._unit_of_work_factory() as uow:
            actor = await uow.get_member_by_telegram_user_id(actor_telegram_user_id)
            return bool(
                actor is not None
                and actor.status is MemberStatus.ACTIVE
                and actor.role is MemberRole.ADMINISTRATOR
            )

    async def paid_assignments(self, actor_telegram_user_id: int) -> tuple[PaidAssignment, ...]:
        """Return paid assignments that an active administrator may investigate."""
        async with self._unit_of_work_factory() as uow:
            await _active_admin(uow, actor_telegram_user_id)
            return await uow.moderation.list_paid_assignments()

    async def alerts(self, actor_telegram_user_id: int) -> tuple[InteractionAlert, ...]:
        """Return open interaction alerts to an active administrator."""
        async with self._unit_of_work_factory() as uow:
            await _active_admin(uow, actor_telegram_user_id)
            return await uow.moderation.list_open_alerts()

    async def sanctions(self, actor_telegram_user_id: int) -> tuple[SanctionCard, ...]:
        """Return active sanctions to an active administrator."""
        async with self._unit_of_work_factory() as uow:
            await _active_admin(uow, actor_telegram_user_id)
            return await uow.moderation.list_active_sanctions()

    async def open_fraud_case(self, command: OpenFraudCaseCommand) -> ModerationCase:
        """Open a paid-assignment investigation as an administrator."""
        return cast(
            "ModerationCase",
            await self._mutate(command, administrator=True, operation="open_fraud_case"),
        )

    async def resolve(self, command: ResolveCaseCommand) -> ModerationCase:
        """Resolve an initial case or its accepted appeal."""
        return cast("ModerationCase", await self._mutate(command, operation="resolve_case"))

    async def preview_resolution(self, command: PreviewResolutionCommand) -> ResolutionPreview:
        """Persist a restart-safe moderation preview."""
        return cast(
            "ResolutionPreview", await self._mutate(command, operation="preview_resolution")
        )

    async def confirm_resolution(self, command: ConfirmResolutionCommand) -> ModerationCase:
        """Apply one exact moderation preview."""
        return cast("ModerationCase", await self._mutate(command, operation="confirm_resolution"))

    async def appeal(self, command: RequestAppealCommand) -> ModerationCase:
        """Request one appeal as a case party."""
        return cast(
            "ModerationCase",
            await self._mutate(command, member_allowed=True, operation="request_appeal"),
        )

    async def issue_sanction(self, command: IssueSanctionCommand) -> Sanction:
        """Validate and issue a sanction through the role matrix."""
        validate_sanction(
            sanction_type=command.sanction_type,
            actions=command.restricted_actions,
            ends_at=command.ends_at,
            now=datetime.datetime.now(datetime.UTC),
        )
        return cast("Sanction", await self._mutate(command, operation="issue_sanction"))

    async def revoke_sanction(self, command: RevokeSanctionCommand) -> Sanction:
        """Revoke a sanction; ban revocation remains administrator-only in storage."""
        return cast("Sanction", await self._mutate(command, operation="revoke_sanction"))

    async def review_alert(self, command: ReviewAlertCommand) -> str:
        """Review an interaction alert as a privileged administrator."""
        return cast(
            "str", await self._mutate(command, administrator=True, operation="review_alert")
        )

    async def moderate_karma(self, command: ModerateKarmaCommand) -> str:
        """Exclude or restore one exact vote revision."""
        return cast(
            "str", await self._mutate(command, administrator=True, operation="moderate_karma")
        )

    async def _mutate(self, command: ModerationCommand, **policy: object) -> object:
        update_id = int(command.update_id)
        telegram_user_id = int(command.actor_telegram_user_id)
        operation = str(policy.pop("operation"))
        async with self._unit_of_work_factory() as uow:
            await uow.acquire_update_gate(update_id)
            stored = await uow.get_receipt_outcome(update_id)
            if stored is not None:
                _stored_marker(stored)
                return await uow.moderation.replay(stored)
            if policy.get("member_allowed"):
                actor = await _active_member(uow, telegram_user_id)
            else:
                actor = await _active_staff(uow, telegram_user_id)
            if policy.get("administrator") and actor.role is not MemberRole.ADMINISTRATOR:
                raise PermissionError("Only an active administrator may perform this operation.")
            result = await getattr(uow.moderation, operation)(command, actor)
            entity_id = getattr(result, "id", result)
            marker = f"moderation:{operation}:{entity_id}"
            await uow.add_receipt(
                update_id=update_id,
                update_type="moderation",
                actor_id=actor.id,
                outcome_code=marker,
            )
            await uow.commit()
            return result


async def _active_member(uow: ModerationUnitOfWork, telegram_user_id: int) -> Member:
    actor = await uow.get_member_by_telegram_user_id(telegram_user_id)
    if actor is None or actor.status is not MemberStatus.ACTIVE:
        raise PermissionError("Only an active member may perform this operation.")
    return actor


async def _active_staff(uow: ModerationUnitOfWork, telegram_user_id: int) -> Member:
    actor = await _active_member(uow, telegram_user_id)
    if actor.role not in {MemberRole.MODERATOR, MemberRole.ADMINISTRATOR}:
        raise PermissionError("Only active moderation staff may perform this operation.")
    return actor


async def _active_admin(uow: ModerationUnitOfWork, telegram_user_id: int) -> Member:
    actor = await _active_member(uow, telegram_user_id)
    if actor.role is not MemberRole.ADMINISTRATOR:
        raise PermissionError("Only an active administrator may perform this operation.")
    return actor


def _stored_marker(value: str) -> str:
    if not value.startswith("moderation:"):
        raise ModerationApplicationError("Telegram update belongs to another operation.")
    return value


class ModerationApplicationError(ValueError):
    """Raised when a moderation workflow cannot safely continue."""
