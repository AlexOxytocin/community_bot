"""Application services for the economic ledger and product levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from community_bot.domain.economy import (
    EconomyMutationCommand,
    EconomyMutationResult,
    LevelDefinition,
    ProductConfigCandidate,
    ProductConfigError,
    ResolvedLevel,
)
from community_bot.domain.members import AuthorizationError, Member, MemberRole, MemberStatus

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from decimal import Decimal
    from pathlib import Path
    from uuid import UUID

_MAX_HISTORY_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ProductConfigVersion:
    """Persisted immutable product configuration identity."""

    id: UUID
    version: int
    content_hash: str
    levels: tuple[LevelDefinition, ...]
    maximum_active_assignments: int = 3


@dataclass(frozen=True, slots=True)
class ActiveProductConfig:
    """One active product configuration and its complete level scale."""

    id: UUID
    version: int
    content_hash: str
    levels: tuple[LevelDefinition, ...]
    maximum_active_assignments: int = 3


@dataclass(frozen=True, slots=True)
class ProductConfigActivationCommand:
    """Activate one previously ingested product configuration."""

    activation_command_id: UUID
    target_config_version: int
    actor_member_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class ProductConfigActivationResult:
    """Stored deterministic product configuration activation result."""

    activation_id: UUID
    target_config_id: UUID
    outcome_code: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class LedgerHistoryCursor:
    """Stable descending ledger history cursor."""

    created_at: datetime.datetime
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class LedgerHistoryItem:
    """One immutable ledger row exposed by an authorized history query."""

    transaction_id: UUID
    member_id: UUID
    transaction_type: str
    credit_delta: Decimal
    experience_delta: Decimal
    comment: str | None
    created_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class LedgerHistoryPage:
    """One stable page of ledger history."""

    items: tuple[LedgerHistoryItem, ...]
    next_cursor: LedgerHistoryCursor | None


@dataclass(frozen=True, slots=True)
class ReconciliationMismatch:
    """One member whose caches differ from immutable ledger sums."""

    member_id: UUID
    expected_credit_balance: Decimal
    actual_credit_balance: Decimal
    expected_experience_total: Decimal
    actual_experience_total: Decimal


class EconomyMutationPort(Protocol):
    """Apply named mutations inside an already active transaction."""

    async def apply_batch(
        self, commands: Sequence[EconomyMutationCommand]
    ) -> tuple[EconomyMutationResult, ...]:
        """Apply one all-new batch or replay one all-stored batch."""
        ...

    async def apply_one(self, command: EconomyMutationCommand) -> EconomyMutationResult:
        """Apply a single command through the same batch protocol."""
        ...

    async def prepare_batch(
        self,
        commands: Sequence[EconomyMutationCommand],
        *,
        additional_member_ids: Sequence[UUID] = (),
    ) -> PreparedEconomyBatch:
        """Acquire economy gates and member locks without applying effects."""
        ...


class PreparedEconomyBatch(Protocol):
    """Economy batch whose gates and complete member lock scope are held."""

    @property
    def members(self) -> Mapping[UUID, Member]:
        """Return immutable snapshots of every locked member."""
        ...

    async def apply(self) -> tuple[EconomyMutationResult, ...]:
        """Apply or replay the batch inside the caller-owned transaction."""
        ...


class EconomyUnitOfWork(Protocol):
    """Public transaction boundary shared by economy and future workflows."""

    @property
    def economy(self) -> EconomyMutationPort:
        """Return the economy adapter bound to this transaction."""
        ...

    async def acquire_product_config_mutation_gate(self) -> None:
        """Acquire the common gate before any product config actor row."""
        ...

    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]:
        """Lock members in canonical UUID order."""
        ...

    async def lock_all_members(self) -> dict[UUID, Member]:
        """Lock every member in canonical UUID order."""
        ...

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        """Resolve an actor without making an access decision."""
        ...

    async def get_active_product_config(self) -> ActiveProductConfig | None:
        """Read the complete active product configuration."""
        ...

    async def ingest_product_config_locked(
        self, *, candidate: ProductConfigCandidate, actor_id: UUID
    ) -> ProductConfigVersion:
        """Ingest after the common gate and actor authorization."""
        ...

    async def activate_product_config_locked(
        self, command: ProductConfigActivationCommand
    ) -> ProductConfigActivationResult:
        """Activate after the common gate and actor authorization."""
        ...

    async def read_ledger_history(
        self,
        *,
        member_id: UUID,
        limit: int,
        cursor: LedgerHistoryCursor | None,
    ) -> LedgerHistoryPage:
        """Read a deterministic ledger page."""
        ...

    async def set_repeatable_read(self) -> None:
        """Set the current transaction isolation before its first query."""
        ...

    async def reconcile_economy(self) -> tuple[ReconciliationMismatch, ...]:
        """Compare all member caches with ledger sums without repairing them."""
        ...

    async def resolve_member_level(self, member_id: UUID) -> ResolvedLevel:
        """Resolve one member against the exact active product version."""
        ...

    async def append_audit_event(
        self,
        *,
        actor_member_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
    ) -> None:
        """Append a generic workflow marker inside the same transaction."""
        ...

    async def commit(self) -> None:
        """Commit all effects once."""
        ...


class EconomyUnitOfWorkFactory(Protocol):
    """Create an isolated transaction context."""

    def __call__(self) -> AbstractAsyncContextManager[EconomyUnitOfWork]:
        """Return a fresh unit of work."""
        ...


class ProductConfigLoader(Protocol):
    """Load and fully validate one non-secret candidate file."""

    def __call__(self, path: Path) -> ProductConfigCandidate:
        """Return a validated candidate or raise a configuration error."""
        ...


class EconomyService:
    """Standalone owner of one economy transaction."""

    def __init__(self, unit_of_work_factory: EconomyUnitOfWorkFactory) -> None:
        """Configure the transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def apply_batch(
        self, commands: Sequence[EconomyMutationCommand]
    ) -> tuple[EconomyMutationResult, ...]:
        """Apply an atomic batch and commit exactly once."""
        async with self._unit_of_work_factory() as unit_of_work:
            results = await unit_of_work.economy.apply_batch(commands)
            await unit_of_work.commit()
        return results

    async def apply_one(self, command: EconomyMutationCommand) -> EconomyMutationResult:
        """Apply one command and commit exactly once."""
        results = await self.apply_batch((command,))
        return results[0]


class ProductConfigService:
    """Authorize and orchestrate standalone product config mutations."""

    def __init__(self, unit_of_work_factory: EconomyUnitOfWorkFactory) -> None:
        """Configure the transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def ingest(
        self, *, candidate: ProductConfigCandidate, actor_member_id: UUID
    ) -> ProductConfigVersion:
        """Ingest one immutable candidate as an active administrator."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_product_config_mutation_gate()
            actor = await _lock_active_administrator(unit_of_work, actor_member_id)
            version = await unit_of_work.ingest_product_config_locked(
                candidate=candidate,
                actor_id=actor.id,
            )
            await unit_of_work.commit()
        return version

    async def activate(
        self, command: ProductConfigActivationCommand
    ) -> ProductConfigActivationResult:
        """Activate one stored version as an active administrator."""
        _require_reason(command.reason)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_product_config_mutation_gate()
            members = await unit_of_work.lock_all_members()
            _require_active_administrator(members, command.actor_member_id)
            result = await unit_of_work.activate_product_config_locked(command)
            await unit_of_work.commit()
        return result


class ProductConfigBootstrapCoordinator:
    """Prepare one active product configuration without hidden role grants."""

    def __init__(
        self,
        unit_of_work_factory: EconomyUnitOfWorkFactory,
        loader: ProductConfigLoader,
    ) -> None:
        """Configure persistence and candidate loading."""
        self._unit_of_work_factory = unit_of_work_factory
        self._loader = loader

    async def prepare(
        self,
        *,
        candidate_path: Path | None,
        actor_member_id: UUID | None,
        activation_command_id: UUID | None,
        reason: str = "Product configuration bootstrap.",
    ) -> ActiveProductConfig:
        """Return or create the active product configuration deterministically."""
        if candidate_path is None:
            async with self._unit_of_work_factory() as unit_of_work:
                active = await unit_of_work.get_active_product_config()
            if active is None:
                message = "The first bootstrap requires a valid product config candidate."
                raise ProductConfigError(message)
            return active

        candidate = self._loader(candidate_path)
        if actor_member_id is None or activation_command_id is None:
            message = "Candidate bootstrap requires stable actor and activation identities."
            raise ProductConfigError(message)
        _require_reason(reason)

        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_product_config_mutation_gate()
            members = await unit_of_work.lock_all_members()
            actor = _require_active_administrator(members, actor_member_id)
            await unit_of_work.ingest_product_config_locked(
                candidate=candidate,
                actor_id=actor.id,
            )
            await unit_of_work.activate_product_config_locked(
                ProductConfigActivationCommand(
                    activation_command_id=activation_command_id,
                    target_config_version=candidate.config_version,
                    actor_member_id=actor.id,
                    reason=reason,
                )
            )
            await unit_of_work.commit()

        async with self._unit_of_work_factory() as unit_of_work:
            active = await unit_of_work.get_active_product_config()
        if active is None:  # pragma: no cover - defensive storage contract guard.
            message = "Product config activation committed without an active pointer."
            raise ProductConfigError(message)
        return active


class EconomyQueryService:
    """Authorize ledger history, reconciliation, and current level reads."""

    def __init__(self, unit_of_work_factory: EconomyUnitOfWorkFactory) -> None:
        """Configure the transaction factory."""
        self._unit_of_work_factory = unit_of_work_factory

    async def history(
        self,
        *,
        telegram_user_id: int,
        target_member_id: UUID,
        limit: int = 50,
        cursor: LedgerHistoryCursor | None = None,
    ) -> LedgerHistoryPage:
        """Return one authorized stable page of ledger history."""
        if limit < 1 or limit > _MAX_HISTORY_PAGE_SIZE:
            message = "Ledger history page size must be between 1 and 100."
            raise ValueError(message)
        async with self._unit_of_work_factory() as unit_of_work:
            unresolved_actor = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            if unresolved_actor is None:
                message = "Ledger history actor is not a registered member."
                raise AuthorizationError(message)
            members = await unit_of_work.lock_members((unresolved_actor.id, target_member_id))
            actor = members[unresolved_actor.id]
            target = members[target_member_id]
            if not _can_read_economy(actor=actor, target=target):
                message = "Actor is not allowed to read the target ledger."
                raise AuthorizationError(message)
            return await unit_of_work.read_ledger_history(
                member_id=target.id,
                limit=limit,
                cursor=cursor,
            )

    async def reconcile(self, *, actor_member_id: UUID) -> tuple[ReconciliationMismatch, ...]:
        """Return read-only mismatches to an active administrator."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.set_repeatable_read()
            await _lock_active_administrator(unit_of_work, actor_member_id)
            return await unit_of_work.reconcile_economy()

    async def level(self, *, target_member_id: UUID) -> ResolvedLevel:
        """Resolve one member level against the active scale."""
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.resolve_member_level(target_member_id)


async def _lock_active_administrator(
    unit_of_work: EconomyUnitOfWork,
    actor_member_id: UUID,
) -> Member:
    members = await unit_of_work.lock_members((actor_member_id,))
    return _require_active_administrator(members, actor_member_id)


def _require_active_administrator(members: dict[UUID, Member], actor_member_id: UUID) -> Member:
    actor = members[actor_member_id]
    if actor.status is not MemberStatus.ACTIVE or actor.role is not MemberRole.ADMINISTRATOR:
        message = "An active administrator is required."
        raise AuthorizationError(message)
    return actor


def _can_read_economy(*, actor: Member, target: Member) -> bool:
    if actor.status is not MemberStatus.ACTIVE:
        return False
    return actor.role is MemberRole.ADMINISTRATOR or actor.id == target.id


def _require_reason(reason: str) -> None:
    if not reason.strip():
        message = "A non-empty reason is required."
        raise ValueError(message)
