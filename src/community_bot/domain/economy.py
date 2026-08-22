# ruff: noqa: PLR0913
"""Economic ledger and product-level domain rules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from uuid import UUID

_STARTING_GRANT_AMOUNT = 5
_MAX_IDEMPOTENCY_KEY_LENGTH = 255


class EconomyError(ValueError):
    """Base error for deterministic economy rule violations."""


class IdempotencyConflictError(EconomyError):
    """Raised when an idempotency identity is reused with another payload."""


class InsufficientBalanceError(EconomyError):
    """Raised when an operation would make a cached total negative."""


class ProductConfigError(EconomyError):
    """Raised when product configuration cannot be used safely."""


class TransactionType(StrEnum):
    """Supported immutable account transaction types."""

    STARTING_GRANT = "starting_grant"
    TASK_REWARD_RESERVED = "task_reward_reserved"
    TASK_REWARD_EARNED = "task_reward_earned"
    TASK_REWARD_REFUNDED = "task_reward_refunded"
    PARTIAL_TASK_REWARD = "partial_task_reward"
    COMMUNITY_TASK_REWARD = "community_task_reward"
    PENALTY = "penalty"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    FRAUD_REVERSAL = "fraud_reversal"
    RESOLUTION_REVERSAL = "resolution_reversal"


@dataclass(frozen=True, slots=True)
class EconomyCommand:
    """One named ledger mutation before persistence."""

    transaction_type: TransactionType
    member_id: UUID
    idempotency_key: str
    credit_delta: int
    experience_delta: int
    actor_member_id: UUID | None = None
    reason: str | None = None
    comment: str | None = None
    reversed_transaction_id: UUID | None = None
    task_id: UUID | None = None
    assignment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReversalCommand:
    """Request an exact inverse of one immutable ledger transaction."""

    reversed_transaction_id: UUID
    idempotency_key: str
    actor_member_id: UUID
    reason: str
    comment: str | None = None
    transaction_type: TransactionType = TransactionType.FRAUD_REVERSAL


EconomyMutationCommand = EconomyCommand | ReversalCommand


@dataclass(frozen=True, slots=True)
class EconomyMutationResult:
    """Stable persisted identity returned by a ledger mutation."""

    transaction_id: UUID
    member_id: UUID
    transaction_type: TransactionType
    credit_delta: int
    experience_delta: int
    replayed: bool
    task_id: UUID | None = None
    assignment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AdministrativeContext:
    """Required identity and explanation for an administrative mutation."""

    actor_member_id: UUID
    reason: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class CachedLevel:
    """Versioned derived level cache supplied to the resolver."""

    level_number: int
    config_id: UUID


@dataclass(frozen=True, slots=True)
class _AmountCommandSpec:
    transaction_type: TransactionType
    credit_sign: int
    gives_experience: bool


@dataclass(frozen=True, slots=True)
class _CommandMetadata:
    actor_member_id: UUID | None = None
    reason: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class LevelDefinition:
    """One level in an immutable product configuration version."""

    level_number: int
    experience_required: int
    display_name: str
    description: str | None = None
    level_up_message: str | None = None
    permissions: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProductConfigCandidate:
    """Validated non-secret candidate before PostgreSQL ingestion."""

    schema_version: int
    config_version: int
    levels: tuple[LevelDefinition, ...]
    interaction_alert_threshold: int
    interaction_alert_window_days: int
    maximum_active_assignments: int = 3
    assignment_policy_in_payload: bool = False

    @property
    def content_hash(self) -> str:
        """Return a hash of product fields, excluding identity metadata."""
        projection = {
            "schema_version": self.schema_version,
            "levels": [
                {
                    "level_number": level.level_number,
                    "experience_required": level.experience_required,
                    "display_name": level.display_name,
                    "description": level.description,
                    "level_up_message": level.level_up_message,
                    "permissions": dict(level.permissions or {}),
                }
                for level in sorted(self.levels, key=lambda item: item.level_number)
            ],
            "interaction_alert_threshold": self.interaction_alert_threshold,
            "interaction_alert_window_days": self.interaction_alert_window_days,
        }
        if self.assignment_policy_in_payload:
            projection["assignment_policy"] = {
                "maximum_active_assignments": self.maximum_active_assignments
            }
        return _sha256_json(projection)

    def payload(self) -> dict[str, Any]:
        """Return the complete immutable payload stored in PostgreSQL."""
        payload = {
            "schema_version": self.schema_version,
            "config_version": self.config_version,
            "levels": [
                {
                    "level_number": level.level_number,
                    "experience_required": level.experience_required,
                    "display_name": level.display_name,
                    "description": level.description,
                    "level_up_message": level.level_up_message,
                    "permissions": dict(level.permissions or {}),
                }
                for level in sorted(self.levels, key=lambda item: item.level_number)
            ],
            "interaction_alert_threshold": self.interaction_alert_threshold,
            "interaction_alert_window_days": self.interaction_alert_window_days,
        }
        if self.assignment_policy_in_payload:
            payload["assignment_policy"] = {
                "maximum_active_assignments": self.maximum_active_assignments
            }
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedLevel:
    """Level resolved against one exact active product version."""

    config_id: UUID
    config_version: int
    level_number: int
    display_name: str


def starting_grant(member_id: UUID) -> EconomyCommand:
    """Build the only valid starting grant and its stable identity."""
    return EconomyCommand(
        transaction_type=TransactionType.STARTING_GRANT,
        member_id=member_id,
        idempotency_key=f"starting_grant:{member_id}",
        credit_delta=_STARTING_GRANT_AMOUNT,
        experience_delta=0,
    )


def reserve_reward(
    *, member_id: UUID, amount: int, idempotency_key: str, comment: str | None = None
) -> EconomyCommand:
    """Build a task reward reservation."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.TASK_REWARD_RESERVED,
            credit_sign=-1,
            gives_experience=False,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(comment=comment),
    )


def earn_reward(
    *,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    comment: str | None = None,
    task_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> EconomyCommand:
    """Build a full task reward."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.TASK_REWARD_EARNED,
            credit_sign=1,
            gives_experience=True,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(comment=comment),
        task_id=task_id,
        assignment_id=assignment_id,
    )


def refund_reward(
    *,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    comment: str | None = None,
    task_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> EconomyCommand:
    """Build a task reward refund."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.TASK_REWARD_REFUNDED,
            credit_sign=1,
            gives_experience=False,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(comment=comment),
        task_id=task_id,
        assignment_id=assignment_id,
    )


def earn_partial_reward(
    *,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    comment: str | None = None,
    task_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> EconomyCommand:
    """Build the actual partial payout selected by a task workflow."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.PARTIAL_TASK_REWARD,
            credit_sign=1,
            gives_experience=True,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(comment=comment),
        task_id=task_id,
        assignment_id=assignment_id,
    )


def earn_community_reward(
    *,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    comment: str | None = None,
    task_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> EconomyCommand:
    """Build a system-issued community task payout."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.COMMUNITY_TASK_REWARD,
            credit_sign=1,
            gives_experience=True,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(comment=comment),
        task_id=task_id,
        assignment_id=assignment_id,
    )


def apply_penalty(
    *,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    context: AdministrativeContext,
) -> EconomyCommand:
    """Build an authorized credit-only penalty request."""
    return _amount_command(
        spec=_AmountCommandSpec(
            transaction_type=TransactionType.PENALTY,
            credit_sign=-1,
            gives_experience=False,
        ),
        member_id=member_id,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=_command_metadata(context=context),
    )


def admin_adjustment(
    *,
    member_id: UUID,
    credit_delta: int,
    experience_delta: int,
    idempotency_key: str,
    context: AdministrativeContext,
) -> EconomyCommand:
    """Build an auditable correction of credits, experience, or both."""
    command = EconomyCommand(
        transaction_type=TransactionType.ADMIN_ADJUSTMENT,
        member_id=member_id,
        idempotency_key=idempotency_key,
        credit_delta=credit_delta,
        experience_delta=experience_delta,
        actor_member_id=context.actor_member_id,
        reason=context.reason,
        comment=context.comment,
    )
    validate_economy_command(command)
    return normalize_economy_command(command)


def validate_economy_command(command: EconomyCommand) -> None:
    """Validate one fully resolved command without reading state."""
    if not command.idempotency_key.strip():
        message = "Idempotency key must not be empty."
        raise EconomyError(message)
    if len(command.idempotency_key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        message = "Idempotency key must not exceed 255 characters."
        raise EconomyError(message)
    if command.reason is not None and not command.reason.strip():
        message = "Reason must not be blank when provided."
        raise EconomyError(message)
    if command.comment is not None and not command.comment.strip():
        message = "Comment must not be blank when provided."
        raise EconomyError(message)

    _DELTA_VALIDATORS[command.transaction_type](command)

    if command.transaction_type not in {
        TransactionType.FRAUD_REVERSAL,
        TransactionType.RESOLUTION_REVERSAL,
    }:
        _require(
            condition=command.reversed_transaction_id is None,
            message="Only a reversal may reference a source.",
        )


def normalize_economy_command(command: EconomyCommand) -> EconomyCommand:
    """Normalize significant text before hashing and persistence."""
    return EconomyCommand(
        transaction_type=command.transaction_type,
        member_id=command.member_id,
        idempotency_key=command.idempotency_key.strip(),
        credit_delta=command.credit_delta,
        experience_delta=command.experience_delta,
        actor_member_id=command.actor_member_id,
        reason=None if command.reason is None else command.reason.strip(),
        comment=None if command.comment is None else command.comment.strip(),
        reversed_transaction_id=command.reversed_transaction_id,
        task_id=command.task_id,
        assignment_id=command.assignment_id,
    )


def economy_payload_hash(command: EconomyCommand) -> str:
    """Hash the exact schema-v1 semantic projection of a ledger command."""
    normalized = normalize_economy_command(command)
    projection = {
        "schema_version": 1,
        "transaction_type": normalized.transaction_type.value,
        "member_id": str(normalized.member_id),
        "credit_delta": normalized.credit_delta,
        "experience_delta": normalized.experience_delta,
        "actor_member_id": (
            None if normalized.actor_member_id is None else str(normalized.actor_member_id)
        ),
        "reason": normalized.reason,
        "comment": normalized.comment,
        "reversed_transaction_id": (
            None
            if normalized.reversed_transaction_id is None
            else str(normalized.reversed_transaction_id)
        ),
    }
    if normalized.task_id is not None or normalized.assignment_id is not None:
        projection["task_id"] = None if normalized.task_id is None else str(normalized.task_id)
        projection["assignment_id"] = (
            None if normalized.assignment_id is None else str(normalized.assignment_id)
        )
    return _sha256_json(projection)


def resolve_level(
    *,
    experience_total: int,
    config_id: UUID,
    config_version: int,
    levels: Sequence[LevelDefinition],
    cache: CachedLevel | None = None,
) -> ResolvedLevel:
    """Resolve a level without trusting a cache from another config version."""
    if experience_total < 0:
        message = "Experience total cannot be negative."
        raise EconomyError(message)
    ordered = sorted(levels, key=lambda level: level.level_number)
    if not ordered:
        message = "An active product configuration must contain levels."
        raise ProductConfigError(message)
    by_number = {level.level_number: level for level in ordered}
    if cache is not None and cache.config_id == config_id and cache.level_number in by_number:
        cached = by_number[cache.level_number]
        if cached.experience_required <= experience_total:
            next_level = by_number.get(cached.level_number + 1)
            if next_level is None or experience_total < next_level.experience_required:
                return ResolvedLevel(
                    config_id=config_id,
                    config_version=config_version,
                    level_number=cached.level_number,
                    display_name=cached.display_name,
                )

    selected = ordered[0]
    for level in ordered:
        if level.experience_required > experience_total:
            break
        selected = level
    return ResolvedLevel(
        config_id=config_id,
        config_version=config_version,
        level_number=selected.level_number,
        display_name=selected.display_name,
    )


def _amount_command(
    *,
    spec: _AmountCommandSpec,
    member_id: UUID,
    amount: int,
    idempotency_key: str,
    metadata: _CommandMetadata,
    task_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> EconomyCommand:
    if amount < 0:
        message = "Operation amount cannot be negative."
        raise EconomyError(message)
    credit_delta = amount * spec.credit_sign
    command = EconomyCommand(
        transaction_type=spec.transaction_type,
        member_id=member_id,
        idempotency_key=idempotency_key,
        credit_delta=credit_delta,
        experience_delta=amount if spec.gives_experience else 0,
        actor_member_id=metadata.actor_member_id,
        reason=metadata.reason,
        comment=metadata.comment,
        task_id=task_id,
        assignment_id=assignment_id,
    )
    validate_economy_command(command)
    return normalize_economy_command(command)


def _require_admin_metadata(command: EconomyCommand) -> None:
    _require(
        condition=command.actor_member_id is not None, message="Administrative actor is required."
    )
    _require(
        condition=command.reason is not None and bool(command.reason.strip()),
        message="Reason is required.",
    )


def _require(*, condition: bool, message: str) -> None:
    if not condition:
        raise EconomyError(message)


def _command_metadata(
    *,
    context: AdministrativeContext | None = None,
    comment: str | None = None,
) -> _CommandMetadata:
    if context is not None:
        return _CommandMetadata(
            actor_member_id=context.actor_member_id,
            reason=context.reason,
            comment=context.comment,
        )
    return _CommandMetadata(comment=comment)


def _validate_starting_grant(command: EconomyCommand) -> None:
    _require(
        condition=(
            command.credit_delta == _STARTING_GRANT_AMOUNT
            and command.experience_delta == 0
            and command.idempotency_key == f"starting_grant:{command.member_id}"
        ),
        message="Invalid starting grant.",
    )


def _validate_reservation(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta <= 0 and command.experience_delta == 0,
        message="Invalid reward reservation.",
    )


def _validate_reward(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta >= 0 and command.experience_delta == command.credit_delta,
        message="Invalid experience-bearing reward.",
    )


def _validate_refund(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta >= 0 and command.experience_delta == 0,
        message="Invalid reward refund.",
    )


def _validate_penalty(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta < 0 and command.experience_delta == 0,
        message="Invalid penalty.",
    )
    _require_admin_metadata(command)


def _validate_adjustment(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta != 0 or command.experience_delta != 0,
        message="Adjustment must change a total.",
    )
    _require_admin_metadata(command)


def _validate_reversal(command: EconomyCommand) -> None:
    _require(
        condition=command.credit_delta != 0 or command.experience_delta != 0,
        message="Reversal must change a total.",
    )
    _require(
        condition=command.reversed_transaction_id is not None,
        message="Reversal source is required.",
    )
    _require_admin_metadata(command)


_DELTA_VALIDATORS: dict[TransactionType, Callable[[EconomyCommand], None]] = {
    TransactionType.STARTING_GRANT: _validate_starting_grant,
    TransactionType.TASK_REWARD_RESERVED: _validate_reservation,
    TransactionType.TASK_REWARD_EARNED: _validate_reward,
    TransactionType.TASK_REWARD_REFUNDED: _validate_refund,
    TransactionType.PARTIAL_TASK_REWARD: _validate_reward,
    TransactionType.COMMUNITY_TASK_REWARD: _validate_reward,
    TransactionType.PENALTY: _validate_penalty,
    TransactionType.ADMIN_ADJUSTMENT: _validate_adjustment,
    TransactionType.FRAUD_REVERSAL: _validate_reversal,
    TransactionType.RESOLUTION_REVERSAL: _validate_reversal,
}


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
