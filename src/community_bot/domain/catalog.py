"""Domain contracts for the safe versioned task catalog."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from community_bot.domain.members import Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
_MAX_SCHEMA_BYTES = 16_384
_MAX_SCHEMA_DEPTH = 12
_MAX_REWARD = 4
_MAX_MINUTES = 120
_MAX_PERFORMERS = 10


class CatalogError(ValueError):
    """Base catalog validation error."""


class PayloadValidationError(CatalogError):
    """Payload does not satisfy an immutable template schema."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        """Retain stable user-safe validation details."""
        super().__init__("Template payload validation failed.")
        self.errors = errors


class TaskFormat(StrEnum):
    """Supported task delivery formats."""

    ONLINE = "online"
    OFFLINE = "offline"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class CatalogCursor:
    """Stable logical key of the last template returned to a client."""

    category_sort_order: int
    template_code: str

    def encode(self) -> str:
        """Serialize a compact Telegram-safe cursor."""
        return f"{self.category_sort_order}:{self.template_code}"

    @classmethod
    def decode(cls, value: str) -> CatalogCursor:
        """Parse and validate an untrusted cursor."""
        raw_order, separator, code = value.partition(":")
        if not separator or not raw_order.isdigit() or not _CODE_PATTERN.fullmatch(code):
            message = "Catalog cursor is invalid."
            raise CatalogError(message)
        order = int(raw_order)
        if order < 0:
            message = "Catalog cursor order is invalid."
            raise CatalogError(message)
        return cls(order, code)


@dataclass(frozen=True, slots=True)
class TemplateDraft:
    """Complete candidate content for a new immutable template version."""

    category_code: str
    code: str
    name: str
    description: str
    creator_instructions: str
    performer_instructions: str
    completion_criteria: str
    input_schema: dict[str, object]
    result_schema: dict[str, object]
    credit_reward: int
    estimated_minutes: int
    format: TaskFormat
    minimum_level: int
    maximum_performers: int
    moderation_required: bool


def validate_template_draft(draft: TemplateDraft) -> TemplateDraft:
    """Validate a candidate before any catalog row is changed."""
    _validate_code(draft.category_code, "category")
    _validate_code(draft.code, "template")
    for label, value, minimum, maximum in (
        ("name", draft.name, 3, 120),
        ("description", draft.description, 10, 1000),
        ("creator instructions", draft.creator_instructions, 10, 2000),
        ("performer instructions", draft.performer_instructions, 10, 2000),
        ("completion criteria", draft.completion_criteria, 10, 2000),
    ):
        if not minimum <= len(" ".join(value.split())) <= maximum:
            message = f"Template {label} length is invalid."
            raise CatalogError(message)
    if not 1 <= draft.credit_reward <= _MAX_REWARD:
        message = "Template reward must be between 1 and 4 credits."
        raise CatalogError(message)
    if not 1 <= draft.estimated_minutes <= _MAX_MINUTES:
        message = "Template duration must be between 1 and 120 minutes."
        raise CatalogError(message)
    if draft.minimum_level < 1:
        message = "Template minimum level must be positive."
        raise CatalogError(message)
    if not 1 <= draft.maximum_performers <= _MAX_PERFORMERS:
        message = "Template performer count must be between 1 and 10."
        raise CatalogError(message)
    _validate_schema(draft.input_schema, "input")
    _validate_schema(draft.result_schema, "result")
    return draft


def validate_payload(
    schema: Mapping[str, object], payload: Mapping[str, object]
) -> dict[str, object]:
    """Validate untrusted task data against a local immutable schema."""
    validator = Draft202012Validator(dict(schema))
    errors = tuple(
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in sorted(validator.iter_errors(dict(payload)), key=lambda item: list(item.path))
    )
    if errors:
        raise PayloadValidationError(errors)
    return dict(payload)


def require_catalog_member(member: Member) -> None:
    """Require an active member for catalog browsing and selection."""
    if member.status is not MemberStatus.ACTIVE:
        message = "An active member is required to use the task catalog."
        raise PermissionError(message)


def require_catalog_admin(member: Member) -> None:
    """Require an active administrator for catalog mutations."""
    if member.status is not MemberStatus.ACTIVE or member.role is not MemberRole.ADMINISTRATOR:
        message = "An active administrator is required to manage the task catalog."
        raise PermissionError(message)


def _validate_code(value: str, label: str) -> None:
    if not _CODE_PATTERN.fullmatch(value):
        message = f"The {label} code is invalid."
        raise CatalogError(message)


def _validate_schema(schema: dict[str, object], label: str) -> None:
    if len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()) > (
        _MAX_SCHEMA_BYTES
    ):
        message = f"Template {label} schema is too large."
        raise CatalogError(message)
    if _schema_depth(schema) > _MAX_SCHEMA_DEPTH or _contains_remote_reference(schema):
        message = f"Template {label} schema contains an unsupported structure."
        raise CatalogError(message)
    if (
        schema.get("type") != "object"
        or not isinstance(schema.get("properties"), dict)
        or not isinstance(schema.get("required"), list)
        or schema.get("additionalProperties") is not False
    ):
        message = f"Template {label} schema must be a closed object schema."
        raise CatalogError(message)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        message = f"Template {label} schema is invalid."
        raise CatalogError(message) from error


def _contains_remote_reference(value: object) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_remote_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_remote_reference(item) for item in value)
    return False


def _schema_depth(value: object, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max((_schema_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_schema_depth(item, depth + 1) for item in value), default=depth)
    return depth
