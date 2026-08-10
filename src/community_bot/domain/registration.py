"""Registration, invitation, and editable profile rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from community_bot.domain.members import Member, MemberRole, MemberStatus


class RegistrationError(ValueError):
    """Base error for deterministic registration rule violations."""


class InvitationError(RegistrationError):
    """Raised when an invitation cannot be accepted or changed."""


class StaleRegistrationStepError(RegistrationError):
    """Raised when a delayed answer targets an obsolete registration step."""


class RegistrationStep(StrEnum):
    """Ordered steps of the persistent registration conversation."""

    CONSENT = "consent"
    DISPLAY_NAME = "display_name"
    CITY = "city"
    TIMEZONE = "timezone"
    SHORT_BIO = "short_bio"
    CURRENT_GOAL = "current_goal"
    HELP_CATEGORIES = "help_categories"
    SKILL_TAGS = "skill_tags"
    AVAILABILITY = "availability"
    PREVIEW = "preview"
    SUBMITTED = "submitted"


class RegistrationApplicationStatus(StrEnum):
    """Moderation state of one member registration application."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class ModerationDecision(StrEnum):
    """Supported registration moderation decisions."""

    APPROVE = "approve"
    REJECT = "reject"


class ProfileField(StrEnum):
    """Member-owned profile fields that may be edited."""

    DISPLAY_NAME = "display_name"
    CITY = "city"
    TIMEZONE = "timezone"
    SHORT_BIO = "short_bio"
    CURRENT_GOAL = "current_goal"
    HELP_CATEGORIES = "help_categories"
    SKILL_TAGS = "skill_tags"
    AVAILABILITY = "availability"


@dataclass(frozen=True, slots=True)
class NormalizedAnswer:
    """One validated draft value and the next registration step."""

    field: str
    value: str | tuple[str, ...] | bool
    next_step: RegistrationStep


_STEP_FLOW: dict[RegistrationStep, tuple[ProfileField | str, RegistrationStep]] = {
    RegistrationStep.CONSENT: ("consent", RegistrationStep.DISPLAY_NAME),
    RegistrationStep.DISPLAY_NAME: (ProfileField.DISPLAY_NAME, RegistrationStep.CITY),
    RegistrationStep.CITY: (ProfileField.CITY, RegistrationStep.TIMEZONE),
    RegistrationStep.TIMEZONE: (ProfileField.TIMEZONE, RegistrationStep.SHORT_BIO),
    RegistrationStep.SHORT_BIO: (ProfileField.SHORT_BIO, RegistrationStep.CURRENT_GOAL),
    RegistrationStep.CURRENT_GOAL: (
        ProfileField.CURRENT_GOAL,
        RegistrationStep.HELP_CATEGORIES,
    ),
    RegistrationStep.HELP_CATEGORIES: (
        ProfileField.HELP_CATEGORIES,
        RegistrationStep.SKILL_TAGS,
    ),
    RegistrationStep.SKILL_TAGS: (ProfileField.SKILL_TAGS, RegistrationStep.AVAILABILITY),
    RegistrationStep.AVAILABILITY: (ProfileField.AVAILABILITY, RegistrationStep.PREVIEW),
}


def normalize_registration_answer(
    step: RegistrationStep,
    raw_value: str,
) -> NormalizedAnswer:
    """Validate one answer and return its canonical value and next step."""
    if step not in _STEP_FLOW:
        message = "The registration step does not accept a text answer."
        raise RegistrationError(message)
    field, next_step = _STEP_FLOW[step]
    if field == "consent":
        accepted = raw_value.strip().casefold() in {"yes", "да", "accept", "согласен"}
        if not accepted:
            message = "Registration requires explicit consent."
            raise RegistrationError(message)
        return NormalizedAnswer(field="consent", value=True, next_step=next_step)
    profile_field = ProfileField(field)
    return NormalizedAnswer(
        field=profile_field.value,
        value=normalize_profile_value(profile_field, raw_value),
        next_step=next_step,
    )


def normalize_profile_value(  # noqa: PLR0911 - explicit field rules stay readable.
    field: ProfileField,
    raw_value: str,
) -> str | tuple[str, ...]:
    """Validate and normalize one editable profile value."""
    if field is ProfileField.DISPLAY_NAME:
        return _bounded_text(raw_value, minimum=2, maximum=80, label="display name")
    if field is ProfileField.CITY:
        return _bounded_text(raw_value, minimum=2, maximum=80, label="city")
    if field is ProfileField.TIMEZONE:
        value = _bounded_text(raw_value, minimum=3, maximum=64, label="timezone")
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            message = "Timezone must be a valid IANA timezone."
            raise RegistrationError(message) from error
        return value
    if field is ProfileField.SHORT_BIO:
        return _bounded_text(raw_value, minimum=10, maximum=500, label="short bio")
    if field is ProfileField.CURRENT_GOAL:
        return _bounded_text(raw_value, minimum=3, maximum=300, label="current goal")
    if field is ProfileField.AVAILABILITY:
        return _bounded_text(raw_value, minimum=2, maximum=200, label="availability")
    if field is ProfileField.HELP_CATEGORIES:
        return _normalized_list(raw_value, maximum_items=10, maximum_item_length=50)
    return _normalized_list(raw_value, maximum_items=20, maximum_item_length=50)


def require_invitation_manager(actor: Member) -> None:
    """Require an active administrator for invitation management."""
    if actor.status is not MemberStatus.ACTIVE or actor.role is not MemberRole.ADMINISTRATOR:
        message = "An active administrator is required to manage invitations."
        raise PermissionError(message)


def require_registration_moderator(actor: Member) -> None:
    """Require an active moderator or administrator for registration review."""
    if actor.status is not MemberStatus.ACTIVE or actor.role not in {
        MemberRole.MODERATOR,
        MemberRole.ADMINISTRATOR,
    }:
        message = "An active moderator or administrator is required."
        raise PermissionError(message)


def require_profile_owner(actor: Member, target_member_id: object) -> None:
    """Require an active member to operate on their own profile."""
    if actor.status is not MemberStatus.ACTIVE or actor.id != target_member_id:
        message = "An active member may edit only their own profile."
        raise PermissionError(message)


def _bounded_text(raw_value: str, *, minimum: int, maximum: int, label: str) -> str:
    value = " ".join(raw_value.split())
    if not minimum <= len(value) <= maximum:
        message = f"The {label} length must be between {minimum} and {maximum} characters."
        raise RegistrationError(message)
    return value


def _normalized_list(
    raw_value: str,
    *,
    maximum_items: int,
    maximum_item_length: int,
) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_value.split(","):
        item = " ".join(raw_item.split())
        identity = item.casefold()
        if not item or identity in seen:
            continue
        if len(item) > maximum_item_length:
            message = "A profile list item is too long."
            raise RegistrationError(message)
        seen.add(identity)
        items.append(item)
    if not items or len(items) > maximum_items:
        message = f"The profile list must contain between 1 and {maximum_items} items."
        raise RegistrationError(message)
    return tuple(items)
