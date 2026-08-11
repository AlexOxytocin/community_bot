"""One-time first-administrator bootstrap boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, Self

if TYPE_CHECKING:
    from types import TracebackType
    from uuid import UUID

_POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807


class InitialAdministratorReason(StrEnum):
    """Privacy-safe operator reasons accepted by the bootstrap command."""

    INITIAL_INSTALL = "initial_install"
    CLEAN_RECOVERY = "clean_recovery"


class InitialAdministratorConflictError(RuntimeError):
    """The database is not in the exact state required for bootstrap."""


@dataclass(frozen=True, slots=True)
class InitialAdministratorCommand:
    """Validated input for one bootstrap attempt."""

    telegram_user_id: int
    reason: InitialAdministratorReason

    def __post_init__(self) -> None:
        """Reject identities that cannot be stored safely in PostgreSQL."""
        if not 0 < self.telegram_user_id <= _POSTGRES_BIGINT_MAX:
            message = "Telegram user ID must be a positive PostgreSQL BIGINT."
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InitialAdministratorMember:
    """Minimum persisted identity needed for bootstrap decisions."""

    id: UUID
    telegram_user_id: int


@dataclass(frozen=True, slots=True)
class InitialAdministratorResult:
    """Safe bootstrap outcome returned to the CLI."""

    member_id: UUID
    created: bool


class InitialAdministratorUnitOfWork(Protocol):
    """Transactional persistence contract for the one-time bootstrap."""

    async def __aenter__(self) -> Self:
        """Open one transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback unfinished work and close the transaction."""
        ...

    async def acquire_gate(self) -> None:
        """Acquire the global transaction-scoped bootstrap gate."""
        ...

    async def active_administrators(self) -> tuple[InitialAdministratorMember, ...]:
        """Lock all active administrators."""
        ...

    async def target_member(self, telegram_user_id: int) -> InitialAdministratorMember | None:
        """Lock a member with the target Telegram identity."""
        ...

    async def has_bootstrap_provenance(self, member_id: UUID) -> bool:
        """Return whether the exact bootstrap marker exists."""
        ...

    async def create_administrator(self, telegram_user_id: int) -> InitialAdministratorMember:
        """Create the deterministic administrator state."""
        ...

    async def append_bootstrap_audit(
        self,
        member_id: UUID,
        reason: InitialAdministratorReason,
    ) -> None:
        """Append the privacy-safe provenance marker."""
        ...

    async def commit(self) -> None:
        """Commit the complete result."""
        ...


InitialAdministratorUnitOfWorkFactory = Callable[[], InitialAdministratorUnitOfWork]


class InitialAdministratorService:
    """Create the first administrator under a global database gate."""

    def __init__(self, unit_of_work: InitialAdministratorUnitOfWorkFactory) -> None:
        """Bind the service to a fresh-unit-of-work factory."""
        self._unit_of_work = unit_of_work

    async def bootstrap(
        self,
        command: InitialAdministratorCommand,
    ) -> InitialAdministratorResult:
        """Create one administrator or return the exact persisted bootstrap outcome."""
        async with self._unit_of_work() as unit_of_work:
            await unit_of_work.acquire_gate()
            administrators = await unit_of_work.active_administrators()
            if len(administrators) == 1:
                administrator = administrators[0]
                if (
                    administrator.telegram_user_id == command.telegram_user_id
                    and await unit_of_work.has_bootstrap_provenance(administrator.id)
                ):
                    await unit_of_work.commit()
                    return InitialAdministratorResult(
                        member_id=administrator.id,
                        created=False,
                    )

            target = await unit_of_work.target_member(command.telegram_user_id)
            if administrators or target is not None:
                message = "Initial administrator bootstrap conflicts with persisted state."
                raise InitialAdministratorConflictError(message)

            administrator = await unit_of_work.create_administrator(command.telegram_user_id)
            await unit_of_work.append_bootstrap_audit(administrator.id, command.reason)
            await unit_of_work.commit()
            return InitialAdministratorResult(member_id=administrator.id, created=True)
