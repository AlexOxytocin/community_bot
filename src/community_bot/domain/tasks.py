"""Task creation states and deterministic validation rules."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError

from community_bot.domain.assignments import ACTIVE_ASSIGNMENT_STATUSES, AssignmentStatus
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.members import Member, MemberStatus

if TYPE_CHECKING:
    from uuid import UUID

    from community_bot.domain.economy import ResolvedLevel


class TaskError(ValueError):
    """Base error for task creation and cancellation."""


_MAX_MATERIAL_LENGTH = 2000
_MAX_URL_LENGTH = 700
_MIN_FREEFORM_RESULT_LENGTH = 10
_XL_MIN_REWARD_EXCLUSIVE = 10
_HTTP_URL = TypeAdapter(HttpUrl)
_URI_SCHEME = re.compile(r"\b([a-z][a-z0-9+.-]*):\/\/", re.IGNORECASE)
_HTTP_URI = re.compile(r"https?:\/\/[^\s]+", re.IGNORECASE)
_EXECUTABLE_URI = re.compile(r"\b(?:tg|file|intent|javascript|data|vbscript):", re.IGNORECASE)


class StaleTaskDraftError(TaskError):
    """Raised when a callback targets an outdated draft revision or step."""


class TaskDraftStep(StrEnum):
    """Persistent creation flow steps."""

    TASK_KIND = "task_kind"
    CATEGORY = "category"
    TIME_SIZE = "time_size"
    REWARD = "reward"
    TITLE = "title"
    DESCRIPTION = "description"
    COMPLETION_CRITERIA = "completion_criteria"
    INPUT = "input"
    DEADLINE = "deadline"
    FORMAT = "format"
    MATERIALS = "materials"
    SLOTS = "slots"
    PREVIEW = "preview"
    PUBLISHED = "published"


class TaskStatus(StrEnum):
    """Task states owned by the creation workflow."""

    PUBLISHED = "published"
    CLOSED_FOR_NEW_PERFORMERS = "closed_for_new_performers"
    SETTLING = "settling"
    EXPIRED = "expired"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def derive_task_status(
    *,
    current_status: TaskStatus,
    performer_slots: int,
    deadline_at: datetime.datetime,
    now: datetime.datetime,
    assignment_states: tuple[tuple[int, AssignmentStatus], ...],
) -> TaskStatus:
    """Derive one task status from canonical oldest-to-newest slot history."""
    latest_by_slot = dict(assignment_states)
    latest = tuple(latest_by_slot.values())
    has_active = any(status in ACTIVE_ASSIGNMENT_STATUSES for status in latest)
    has_open_slots = (
        current_status is TaskStatus.PUBLISHED
        and now < deadline_at
        and len(latest_by_slot) < performer_slots
    )
    if has_active or has_open_slots:
        if current_status is TaskStatus.CLOSED_FOR_NEW_PERFORMERS and now < deadline_at:
            return current_status
        return TaskStatus.PUBLISHED if now < deadline_at else TaskStatus.SETTLING
    paid = sum(
        status in {AssignmentStatus.APPROVED, AssignmentStatus.PARTIALLY_APPROVED}
        for status in latest
    )
    if paid == performer_slots:
        return TaskStatus.COMPLETED
    if paid:
        return TaskStatus.PARTIALLY_COMPLETED
    return TaskStatus.EXPIRED


@dataclass(frozen=True, slots=True)
class AcceptanceTaskSnapshot:
    """Minimal locked task snapshot used by future assignment composition."""

    creator_id: UUID | None
    status: TaskStatus
    minimum_level: int


class TaskKind(StrEnum):
    """Free-form task audience shape selected by the creator."""

    SOLO = "solo"
    GROUP = "group"


class TaskTimeSize(StrEnum):
    """Creator-facing approximate duration bucket."""

    XS = "xs"
    S = "s"
    M = "m"
    L = "l"
    XL = "xl"


@dataclass(frozen=True, slots=True)
class TaskTimeSizeSpec:
    """Display and validation rules for one free-form task size."""

    icon: str
    code: str
    label: str
    estimated_minutes: int
    reward_options: tuple[int, ...] | None
    minimum_reward: int


TITLE_LIMIT = 80
DESCRIPTION_LIMIT = 1200
COMPLETION_CRITERIA_LIMIT = 700
FREEFORM_MATERIALS_TEXT_LIMIT = 1000
FREEFORM_RESULT_LIMIT = 2000

TASK_TIME_SIZE_SPECS: dict[TaskTimeSize, TaskTimeSizeSpec] = {
    TaskTimeSize.XS: TaskTimeSizeSpec("⚡", "XS", "до 15 минут", 15, (1, 2), 1),
    TaskTimeSize.S: TaskTimeSizeSpec("⭐", "S", "15-40 минут", 40, (2, 3, 4), 2),
    TaskTimeSize.M: TaskTimeSizeSpec("💎", "M", "40-75 минут", 75, (4, 5, 6, 7), 4),
    TaskTimeSize.L: TaskTimeSizeSpec("🏆", "L", "75-120 минут", 120, (6, 7, 8, 9, 10), 6),
    TaskTimeSize.XL: TaskTimeSizeSpec("👑", "XL", "больше 120 минут", 121, None, 11),
}


def validate_deadline(value: datetime.datetime, *, now: datetime.datetime) -> datetime.datetime:
    """Return a future aware UTC deadline."""
    if value.tzinfo is None or value.utcoffset() is None:
        message = "Task deadline must include a timezone."
        raise TaskError(message)
    normalized = value.astimezone(datetime.UTC)
    if normalized <= now.astimezone(datetime.UTC):
        message = "Task deadline must be in the future."
        raise TaskError(message)
    return normalized


def validate_task_format(
    value: TaskFormat,
    *,
    template_format: TaskFormat,
    city: str | None,
) -> tuple[TaskFormat, str | None]:
    """Validate a concrete format against the selected template."""
    if value is TaskFormat.ANY:
        message = "Published task format must be online or offline."
        raise TaskError(message)
    if template_format is not TaskFormat.ANY and value is not template_format:
        message = "Task format is incompatible with the selected template."
        raise TaskError(message)
    normalized_city = None if city is None else city.strip()
    if value is TaskFormat.OFFLINE and not normalized_city:
        message = "Offline task format requires a city."
        raise TaskError(message)
    return value, normalized_city or None


def validate_slots(value: int, *, maximum: int) -> int:
    """Validate requested performer slots against the immutable template."""
    if not 1 <= value <= maximum:
        message = "Task performer slots exceed the template limit."
        raise TaskError(message)
    return value


def validate_task_kind(value: object) -> TaskKind:
    """Normalize the free-form task kind chosen by the creator."""
    try:
        kind = value if isinstance(value, TaskKind) else TaskKind(str(value))
    except ValueError as error:
        message = "Task kind must be solo or group."
        raise TaskError(message) from error
    return kind


def validate_time_size(value: object) -> TaskTimeSize:
    """Normalize the free-form task duration bucket."""
    try:
        return value if isinstance(value, TaskTimeSize) else TaskTimeSize(str(value).lower())
    except ValueError as error:
        message = "Task time size is invalid."
        raise TaskError(message) from error


def validate_freeform_slots(value: int, *, kind: TaskKind) -> int:
    """Validate unconstrained performer slots for a free-form task."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        message = "Task performer slots must be a positive integer."
        raise TaskError(message)
    if kind is TaskKind.SOLO and value != 1:
        message = "Solo task must have exactly one performer."
        raise TaskError(message)
    if kind is TaskKind.GROUP and value <= 1:
        message = "Group task must have at least two performers."
        raise TaskError(message)
    return value


def validate_freeform_reward(size: TaskTimeSize, value: int) -> int:
    """Validate one creator-selected reward against the selected size bucket."""
    if isinstance(value, bool) or not isinstance(value, int):
        message = "Task reward must be an integer."
        raise TaskError(message)
    spec = TASK_TIME_SIZE_SPECS[size]
    if spec.reward_options is not None:
        if value not in spec.reward_options:
            message = "Task reward is outside the selected size options."
            raise TaskError(message)
    elif value <= _XL_MIN_REWARD_EXCLUSIVE:
        message = "XL task reward must be greater than 10."
        raise TaskError(message)
    return value


def validate_freeform_text(value: object, *, field: str) -> str:
    """Validate creator-authored text fields with field-specific limits."""
    limits = {
        "title": TITLE_LIMIT,
        "description": DESCRIPTION_LIMIT,
        "completion_criteria": COMPLETION_CRITERIA_LIMIT,
    }
    if field not in limits:
        message = "Task text field is invalid."
        raise TaskError(message)
    if not isinstance(value, str):
        message = "Task text must be a string."
        raise TaskError(message)
    normalized = value.strip()
    if not normalized:
        message = "Task text cannot be empty."
        raise TaskError(message)
    if len(normalized) > limits[field]:
        message = "Task text exceeds the configured character limit."
        raise TaskError(message)
    validate_public_text_uris(normalized)
    return normalized


def validate_freeform_materials(value: Mapping[str, object]) -> dict[str, object]:
    """Validate optional creator-supplied materials for a free-form task."""
    if not value:
        return {}
    normalized = validate_materials(value)
    text_value = normalized.get("text")
    if isinstance(text_value, str) and len(text_value) > FREEFORM_MATERIALS_TEXT_LIMIT:
        message = "Task material text exceeds the configured character limit."
        raise TaskError(message)
    return normalized


def validate_freeform_result_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate the standard result payload used by free-form tasks."""
    if set(payload) != {"result"}:
        message = "Free-form task result must contain only result."
        raise TaskError(message)
    result = payload.get("result")
    if not isinstance(result, str):
        message = "Free-form task result must be text."
        raise TaskError(message)
    normalized = result.strip()
    if len(normalized) < _MIN_FREEFORM_RESULT_LENGTH or len(normalized) > FREEFORM_RESULT_LIMIT:
        message = "Free-form task result length is invalid."
        raise TaskError(message)
    validate_public_text_uris(normalized)
    return {"result": normalized}


def task_time_size_label(size: TaskTimeSize) -> str:
    """Return the compact creator-facing duration label."""
    spec = TASK_TIME_SIZE_SPECS[size]
    return f"{spec.icon} {spec.code} · {spec.label}"


def validate_materials(value: Mapping[str, object]) -> dict[str, object]:
    """Validate a small closed transport-neutral materials object."""
    allowed = {"text", "url"}
    if not value or set(value) - allowed:
        message = "Task materials must contain only text or url."
        raise TaskError(message)
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_MATERIAL_LENGTH:
            message = "Task material values must be non-empty strings up to 2000 characters."
            raise TaskError(message)
        clean = item.strip()
        validate_public_text_uris(clean)
        if key == "url" and not _is_safe_http_url(clean):
            message = "Task material URL must use http or https without credentials."
            raise TaskError(message)
        normalized[key] = clean
    return normalized


def validate_public_text_uris(value: object) -> None:
    """Reject executable URI schemes nested in public task input."""
    if isinstance(value, str):
        if _EXECUTABLE_URI.search(value) or any(
            scheme.casefold() not in {"http", "https"} for scheme in _URI_SCHEME.findall(value)
        ):
            message = "Task text contains an unsupported URI scheme."
            raise TaskError(message)
        if any(not _is_safe_http_url(item.rstrip(".,;!?)")) for item in _HTTP_URI.findall(value)):
            message = "Task text contains an invalid HTTP URL."
            raise TaskError(message)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            validate_public_text_uris(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_public_text_uris(item)


def _is_safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _HTTP_URL.validate_python(value)
        return (
            len(value) <= _MAX_URL_LENGTH
            and parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
        )
    except (ValidationError, ValueError):
        return False


def validate_acceptance_actor(
    task: AcceptanceTaskSnapshot,
    actor: Member,
    *,
    resolved_level: ResolvedLevel,
) -> None:
    """Validate static acceptance rules before CB-11 checks slot occupancy."""
    if actor.status is not MemberStatus.ACTIVE:
        message = "Only an active member can accept a task."
        raise PermissionError(message)
    if task.status is not TaskStatus.PUBLISHED:
        message = "Only a published task can be accepted."
        raise TaskError(message)
    if task.creator_id == actor.id:
        message = "A task creator cannot accept their own task."
        raise PermissionError(message)
    if resolved_level.level_number < task.minimum_level:
        message = "Member level is below the task requirement."
        raise PermissionError(message)
