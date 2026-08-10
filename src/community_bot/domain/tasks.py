"""Task creation states and deterministic validation rules."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from community_bot.domain.catalog import TaskFormat
from community_bot.domain.members import Member, MemberStatus

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from community_bot.domain.economy import ResolvedLevel


class TaskError(ValueError):
    """Base error for task creation and cancellation."""


_MAX_MATERIAL_LENGTH = 2000


class StaleTaskDraftError(TaskError):
    """Raised when a callback targets an outdated draft revision or step."""


class TaskDraftStep(StrEnum):
    """Persistent creation flow steps."""

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
    SETTLING = "settling"
    EXPIRED = "expired"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AcceptanceTaskSnapshot:
    """Minimal locked task snapshot used by future assignment composition."""

    creator_id: UUID | None
    status: TaskStatus
    minimum_level: int


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
        normalized[key] = item.strip()
    return normalized


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
