"""Registration, invitation, and editable profile rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from community_bot.domain.members import Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    from uuid import UUID

_MAX_PROFILE_LINK_URL_LENGTH = 2048


class RegistrationError(ValueError):
    """Base error for deterministic registration rule violations."""


class InvitationError(RegistrationError):
    """Raised when an invitation cannot be accepted or changed."""


class StaleRegistrationStepError(RegistrationError):
    """Raised when a delayed answer targets an obsolete registration step."""


class TimezoneResolutionError(RegistrationError):
    """Raised when a human location cannot be resolved without guessing."""


class ProfileTextLengthError(RegistrationError):
    """Raised when one profile text field misses its length bounds."""

    def __init__(self, *, label: str, minimum: int, maximum: int) -> None:
        """Store bounds for user-facing transport messages."""
        self.label = label
        self.minimum = minimum
        self.maximum = maximum
        message = f"The {label} length must be between {minimum} and {maximum} characters."
        super().__init__(message)


class ProfileListSizeError(RegistrationError):
    """Raised when a profile list is empty or has too many items."""

    def __init__(self, *, maximum_items: int) -> None:
        """Store the item count limit for user-facing transport messages."""
        self.maximum_items = maximum_items
        message = f"Profile list must contain between 1 and {maximum_items} items."
        super().__init__(message)


class ProfileListItemLengthError(RegistrationError):
    """Raised when one profile list item exceeds the configured limit."""

    def __init__(self, *, maximum_item_length: int) -> None:
        """Store the item length limit for user-facing transport messages."""
        self.maximum_item_length = maximum_item_length
        message = f"Profile list items must be at most {maximum_item_length} characters."
        super().__init__(message)


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


class ProfileLinkAction(StrEnum):
    """Supported mutations of one ordered public profile link."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ProfileLink:
    """Validated public profile link."""

    id: UUID
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ProfileLinkCommand:
    """Strict command for one profile-link mutation."""

    action: ProfileLinkAction
    link_id: UUID | None = None
    label: str | None = None
    url: str | None = None


def normalize_profile_link_command(command: ProfileLinkCommand) -> ProfileLinkCommand:
    """Validate action shape and normalize untrusted link text."""
    if command.action is ProfileLinkAction.CREATE:
        valid_shape = (
            command.link_id is None and command.label is not None and command.url is not None
        )
    elif command.action is ProfileLinkAction.UPDATE:
        valid_shape = (
            command.link_id is not None and command.label is not None and command.url is not None
        )
    else:
        valid_shape = command.link_id is not None and command.label is None and command.url is None
    if not valid_shape:
        message = "Invalid profile link command."
        raise RegistrationError(message)
    if command.action is ProfileLinkAction.DELETE:
        return command
    label = _bounded_text(command.label or "", minimum=1, maximum=32, label="link label")
    url = command.url or ""
    invalid_url = "Invalid profile link URL."
    if len(url) > _MAX_PROFILE_LINK_URL_LENGTH or any(
        unicodedata.category(char) == "Cc" for char in url
    ):
        raise RegistrationError(invalid_url)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RegistrationError(invalid_url)
    try:
        _ = parsed.port
    except ValueError as error:
        raise RegistrationError(invalid_url) from error
    return ProfileLinkCommand(command.action, command.link_id, label, url)


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

_PILOT_CITY_TIMEZONES: dict[str, str] = {
    "Buenos Aires": "America/Argentina/Buenos_Aires",
    "буэнос айрес": "America/Argentina/Buenos_Aires",
    "екатеринбург": "Asia/Yekaterinburg",
    "казань": "Europe/Moscow",
    "москва": "Europe/Moscow",
    "санкт петербург": "Europe/Moscow",
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
        timezone_name = resolve_timezone(value)
        if timezone_name is None:
            message = "Timezone cannot be resolved from this location without guessing."
            raise TimezoneResolutionError(message)
        return timezone_name
    if field is ProfileField.SHORT_BIO:
        return _bounded_text(raw_value, minimum=10, maximum=500, label="short bio")
    if field is ProfileField.CURRENT_GOAL:
        return _bounded_text(raw_value, minimum=3, maximum=300, label="current goal")
    if field is ProfileField.AVAILABILITY:
        return _bounded_text(raw_value, minimum=2, maximum=200, label="availability")
    if field is ProfileField.HELP_CATEGORIES:
        return _normalized_list(raw_value, maximum_items=10, maximum_item_length=80)
    return _normalized_list(raw_value, maximum_items=20, maximum_item_length=50)


def resolve_timezone(raw_location: str) -> str | None:
    """Resolve an exact IANA name or an unambiguous human city name."""
    value = " ".join(raw_location.split())
    try:
        return ZoneInfo(value).key
    except (ValueError, ZoneInfoNotFoundError):
        pass

    location_key = _location_key(value)
    explicit = _pilot_city_timezone_index().get(location_key)
    if explicit is not None:
        return explicit
    candidates = _timezone_city_index().get(location_key, ())
    if len(candidates) != 1:
        return None
    return candidates[0]


def _location_key(raw_location: str) -> str:
    city = raw_location.rsplit("/", maxsplit=1)[-1].split(",", maxsplit=1)[0]
    decomposed = unicodedata.normalize("NFKD", city)
    characters = (character for character in decomposed if not unicodedata.combining(character))
    normalized = "".join(
        character.casefold() if character.isalnum() else " " for character in characters
    )
    return " ".join(normalized.split())


@lru_cache(maxsize=1)
def _timezone_city_index() -> dict[str, tuple[str, ...]]:
    indexed: dict[str, list[str]] = {}
    for timezone_name in available_timezones():
        key = _location_key(timezone_name)
        indexed.setdefault(key, []).append(timezone_name)
    return {key: tuple(sorted(values)) for key, values in indexed.items()}


@lru_cache(maxsize=1)
def _pilot_city_timezone_index() -> dict[str, str]:
    return {_location_key(city): timezone for city, timezone in _PILOT_CITY_TIMEZONES.items()}


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
        raise ProfileTextLengthError(label=label, minimum=minimum, maximum=maximum)
    return value


def _normalized_list(
    raw_value: str,
    *,
    maximum_items: int,
    maximum_item_length: int,
) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in re.split(r"[,\n]+", raw_value):
        item = " ".join(raw_item.split())
        identity = item.casefold()
        if not item or identity in seen:
            continue
        if len(item) > maximum_item_length:
            raise ProfileListItemLengthError(maximum_item_length=maximum_item_length)
        seen.add(identity)
        items.append(item)
    if not items or len(items) > maximum_items:
        raise ProfileListSizeError(maximum_items=maximum_items)
    return tuple(items)
