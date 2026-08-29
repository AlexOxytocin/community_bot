"""Member roles, states, routing, and authorization rules."""

# ruff: noqa: EM101, TRY003

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime
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


SUPERADMINISTRATOR_PERMISSION = "superadministrator"
DISPUTE_MODERATION_PERMISSION = "interaction_review"
MEMBER_INVITATION_PERMISSION = "member_invitation"
MEMBER_BLOCKING_PERMISSION = "member_blocking"
ADMINISTRATOR_MANAGEMENT_PERMISSION = "administrator_management"
COMMUNITY_TASK_CREATE_PERMISSION = "community_task_create"
COMMUNITY_TASK_REVIEW_PERMISSION = "community_task_review"
PUBLIC_ADMINISTRATOR_PERMISSIONS = frozenset(
    {
        DISPUTE_MODERATION_PERMISSION,
        MEMBER_INVITATION_PERMISSION,
        MEMBER_BLOCKING_PERMISSION,
        ADMINISTRATOR_MANAGEMENT_PERMISSION,
        COMMUNITY_TASK_CREATE_PERMISSION,
        COMMUNITY_TASK_REVIEW_PERMISSION,
    }
)
ADMINISTRATOR_PERMISSIONS = frozenset(
    {
        DISPUTE_MODERATION_PERMISSION,
        MEMBER_INVITATION_PERMISSION,
        MEMBER_BLOCKING_PERMISSION,
        ADMINISTRATOR_MANAGEMENT_PERMISSION,
        "karma_review",
        "member_read",
    }
)


@dataclass(frozen=True, slots=True)
class Member:
    """Security-relevant member snapshot."""

    id: UUID
    telegram_user_id: int
    role: MemberRole
    status: MemberStatus
    permissions: frozenset[str] = frozenset()
    administrator_appointed_by_member_id: UUID | None = None
    administrator_appointed_at: datetime.datetime | None = None


def is_superadministrator(member: Member) -> bool:
    """Return whether the administrator has the single top-level system permission."""
    return (
        member.role is MemberRole.ADMINISTRATOR
        and SUPERADMINISTRATOR_PERMISSION in member.permissions
    )


def effective_administrator_permissions(member: Member) -> frozenset[str]:
    """Return the product permissions displayed by administrator management."""
    if is_superadministrator(member):
        return PUBLIC_ADMINISTRATOR_PERMISSIONS
    return frozenset(member.permissions & PUBLIC_ADMINISTRATOR_PERMISSIONS)


def can_create_community_task(member: Member) -> bool:
    """Return whether an active administrator may publish as the community."""
    return bool(
        member.status is MemberStatus.ACTIVE
        and member.role is MemberRole.ADMINISTRATOR
        and (
            is_superadministrator(member) or COMMUNITY_TASK_CREATE_PERMISSION in member.permissions
        )
    )


def can_review_community_task(member: Member) -> bool:
    """Return whether an active administrator may review community work results."""
    return bool(
        member.status is MemberStatus.ACTIVE
        and member.role is MemberRole.ADMINISTRATOR
        and (
            is_superadministrator(member) or COMMUNITY_TASK_REVIEW_PERMISSION in member.permissions
        )
    )


def assign_administrator(
    *,
    actor: Member,
    target: Member,
    permissions: frozenset[str],
    appointed_at: datetime.datetime,
) -> Member:
    """Authorize one administrator appointment with an exact permission subset."""
    _require_administrator_manager(actor)
    if actor.id == target.id:
        raise AuthorizationError("An administrator cannot appoint themselves.")
    if target.status is not MemberStatus.ACTIVE:
        raise AuthorizationError("Only an active member may become an administrator.")
    if target.role is MemberRole.ADMINISTRATOR:
        raise AuthorizationError("Target member is already an administrator.")
    normalized = _validated_administrator_permissions(actor, permissions)
    return replace(
        target,
        role=MemberRole.ADMINISTRATOR,
        permissions=frozenset({"member_read"} | normalized),
        administrator_appointed_by_member_id=actor.id,
        administrator_appointed_at=appointed_at,
    )


def update_administrator_permissions(
    *, actor: Member, target: Member, permissions: frozenset[str]
) -> Member:
    """Authorize an exact update to one editable administrator's product permissions."""
    _require_editable_administrator(actor=actor, target=target)
    normalized = _validated_administrator_permissions(actor, permissions)
    preserved = target.permissions - PUBLIC_ADMINISTRATOR_PERMISSIONS
    return replace(target, permissions=frozenset(preserved | normalized))


def demote_administrator(*, actor: Member, target: Member) -> Member:
    """Authorize demotion to member while keeping the immutable audit history external."""
    _require_editable_administrator(actor=actor, target=target)
    return replace(
        target,
        role=MemberRole.MEMBER,
        permissions=frozenset(),
        administrator_appointed_by_member_id=None,
        administrator_appointed_at=None,
    )


def can_manage_administrators(member: Member) -> bool:
    """Return whether an active administrator may appoint delegated administrators."""
    return bool(
        member.status is MemberStatus.ACTIVE
        and member.role is MemberRole.ADMINISTRATOR
        and (
            is_superadministrator(member)
            or ADMINISTRATOR_MANAGEMENT_PERMISSION in member.permissions
        )
    )


def can_edit_administrator(*, actor: Member, target: Member) -> bool:
    """Return whether the current actor may edit or demote the target administrator."""
    if not can_manage_administrators(actor) or actor.id == target.id:
        return False
    if target.role is not MemberRole.ADMINISTRATOR or is_superadministrator(target):
        return False
    return bool(
        is_superadministrator(actor) or target.administrator_appointed_by_member_id == actor.id
    )


def _require_administrator_manager(actor: Member) -> None:
    if not can_manage_administrators(actor):
        raise AuthorizationError("Administrator management permission is required.")


def _require_editable_administrator(*, actor: Member, target: Member) -> None:
    if not can_edit_administrator(actor=actor, target=target):
        raise AuthorizationError("This administrator cannot be changed by the current actor.")


def _validated_administrator_permissions(
    actor: Member, permissions: frozenset[str]
) -> frozenset[str]:
    if not permissions or not permissions <= PUBLIC_ADMINISTRATOR_PERMISSIONS:
        raise AuthorizationError("At least one supported administrator permission is required.")
    if not is_superadministrator(actor):
        allowed = effective_administrator_permissions(actor) - {ADMINISTRATOR_MANAGEMENT_PERMISSION}
        if ADMINISTRATOR_MANAGEMENT_PERMISSION in permissions or not permissions <= allowed:
            raise AuthorizationError("An administrator may delegate only their ordinary rights.")
    return permissions


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

    if kind is ChangeKind.ROLE:
        return _change_role(
            actor=actor,
            target=target,
            requested_value=requested_value,
        )
    return _change_status(actor=actor, target=target, requested_value=requested_value)


def _change_role(*, actor: Member, target: Member, requested_value: str) -> Member:
    if target.status not in {MemberStatus.ACTIVE, MemberStatus.PAUSED}:
        message = "Target status does not allow a role change."
        raise AuthorizationError(message)
    try:
        requested = MemberRole(requested_value)
    except ValueError as error:
        message = "Requested role is not supported."
        raise AuthorizationError(message) from error
    superadministrator = is_superadministrator(actor)
    if (
        target.role is MemberRole.ADMINISTRATOR or requested is MemberRole.ADMINISTRATOR
    ) and not superadministrator:
        message = "Only a superadministrator may change administrator access."
        raise AuthorizationError(message)
    if SUPERADMINISTRATOR_PERMISSION in target.permissions:
        message = "Superadministrator access cannot be changed by this operation."
        raise AuthorizationError(message)
    allowed = {
        (MemberRole.MEMBER, MemberRole.MODERATOR),
        (MemberRole.MODERATOR, MemberRole.MEMBER),
    }
    if superadministrator:
        allowed |= {
            (MemberRole.MEMBER, MemberRole.ADMINISTRATOR),
            (MemberRole.MODERATOR, MemberRole.ADMINISTRATOR),
            (MemberRole.ADMINISTRATOR, MemberRole.MEMBER),
            (MemberRole.ADMINISTRATOR, MemberRole.MODERATOR),
        }
    if (target.role, requested) not in allowed:
        message = "Requested role transition is not allowed."
        raise AuthorizationError(message)
    permissions = target.permissions
    if requested is MemberRole.ADMINISTRATOR:
        permissions = permissions | ADMINISTRATOR_PERMISSIONS
    elif target.role is MemberRole.ADMINISTRATOR:
        permissions = permissions - ADMINISTRATOR_PERMISSIONS - {SUPERADMINISTRATOR_PERMISSION}
    return replace(
        target,
        role=requested,
        permissions=frozenset(permissions),
        administrator_appointed_by_member_id=(
            actor.id if requested is MemberRole.ADMINISTRATOR else None
        ),
        administrator_appointed_at=(
            target.administrator_appointed_at if requested is MemberRole.ADMINISTRATOR else None
        ),
    )


def _change_status(*, actor: Member, target: Member, requested_value: str) -> Member:
    if target.role is MemberRole.ADMINISTRATOR and not is_superadministrator(actor):
        message = "Only a superadministrator may change administrator status."
        raise AuthorizationError(message)
    if SUPERADMINISTRATOR_PERMISSION in target.permissions:
        message = "Superadministrator access cannot be changed by this operation."
        raise AuthorizationError(message)
    if target.role not in {MemberRole.MEMBER, MemberRole.MODERATOR, MemberRole.ADMINISTRATOR}:
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
