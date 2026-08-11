"""Member roles, states, routing, and authorization rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class MemberRole(StrEnum):
    """Supported member authorization roles."""

    MEMBER = "member"
    MODERATOR = "moderator"
    ADMINISTRATOR = "administrator"


class MemberStatus(StrEnum):
    """Supported member lifecycle states."""

    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"
    LEFT = "left"
    BANNED = "banned"


class StartOutcome(StrEnum):
    """Persisted deterministic outcomes of the minimal start route."""

    REGISTRATION_REQUIRED = "registration_required"
    REGISTRATION_PENDING = "registration_pending"
    MAIN_MENU = "main_menu"
    ACCOUNT_UNAVAILABLE = "account_unavailable"


class ChangeKind(StrEnum):
    """Administrative member attributes supported by the foundation."""

    ROLE = "role"
    STATUS = "status"


class AuthorizationError(PermissionError):
    """Raised when a server-side member authorization rule denies an action."""


@dataclass(frozen=True, slots=True)
class Member:
    """Security-relevant member snapshot."""

    id: UUID
    telegram_user_id: int
    role: MemberRole
    status: MemberStatus
    permissions: frozenset[str] = frozenset()


def route_start(member: Member | None) -> StartOutcome:
    """Return the deterministic minimal-menu route for a Telegram user."""
    if member is None:
        return StartOutcome.REGISTRATION_REQUIRED
    if member.status is MemberStatus.PENDING:
        return StartOutcome.REGISTRATION_PENDING
    if member.status is MemberStatus.ACTIVE:
        return StartOutcome.MAIN_MENU
    return StartOutcome.ACCOUNT_UNAVAILABLE


def can_read_member(*, actor: Member, target: Member) -> bool:
    """Return whether an actor may read the target member record."""
    if actor.status is not MemberStatus.ACTIVE:
        return False
    if actor.role is MemberRole.ADMINISTRATOR:
        return True
    return actor.id == target.id


def change_member(
    *,
    actor: Member,
    target: Member,
    kind: ChangeKind,
    requested_value: str,
) -> Member:
    """Authorize and return a changed target snapshot."""
    if actor.status is not MemberStatus.ACTIVE or actor.role is not MemberRole.ADMINISTRATOR:
        message = "Active administrator role is required."
        raise AuthorizationError(message)
    if actor.id == target.id:
        message = "An administrator cannot change their own access state."
        raise AuthorizationError(message)
    if target.role is MemberRole.ADMINISTRATOR:
        message = "Administrator targets cannot be changed by this operation."
        raise AuthorizationError(message)

    if kind is ChangeKind.ROLE:
        return _change_role(target=target, requested_value=requested_value)
    return _change_status(target=target, requested_value=requested_value)


def _change_role(*, target: Member, requested_value: str) -> Member:
    if target.status not in {MemberStatus.ACTIVE, MemberStatus.PAUSED}:
        message = "Target status does not allow a role change."
        raise AuthorizationError(message)
    try:
        requested = MemberRole(requested_value)
    except ValueError as error:
        message = "Requested role is not supported."
        raise AuthorizationError(message) from error
    allowed = {
        (MemberRole.MEMBER, MemberRole.MODERATOR),
        (MemberRole.MODERATOR, MemberRole.MEMBER),
    }
    if (target.role, requested) not in allowed:
        message = "Requested role transition is not allowed."
        raise AuthorizationError(message)
    return replace(target, role=requested)


def _change_status(*, target: Member, requested_value: str) -> Member:
    if target.role not in {MemberRole.MEMBER, MemberRole.MODERATOR}:
        message = "Target role does not allow a status change."
        raise AuthorizationError(message)
    try:
        requested = MemberStatus(requested_value)
    except ValueError as error:
        message = "Requested status is not supported."
        raise AuthorizationError(message) from error
    allowed = {
        (MemberStatus.ACTIVE, MemberStatus.PAUSED),
        (MemberStatus.PAUSED, MemberStatus.ACTIVE),
    }
    if (target.status, requested) not in allowed:
        message = "Requested status transition is not allowed."
        raise AuthorizationError(message)
    return replace(target, status=requested)
