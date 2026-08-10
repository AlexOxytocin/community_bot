"""Application services for member routing and administrative changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from community_bot.domain.members import (
    AuthorizationError,
    ChangeKind,
    Member,
    StartOutcome,
    can_read_member,
    change_member,
    route_start,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class UpdateReceipt:
    """Previously committed processing result for one Telegram update."""

    update_id: int
    outcome_code: str


@dataclass(frozen=True, slots=True)
class AdministrativeChange:
    """Input for an auditable administrative member change."""

    update_id: int
    telegram_user_id: int
    target_member_id: UUID
    kind: ChangeKind
    requested_value: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AdministrativeChangeResult:
    """Deterministic persisted result of an administrative change update."""

    outcome_code: str


@dataclass(frozen=True, slots=True)
class ReadMemberQuery:
    """Server-authorized request to read one persisted member."""

    telegram_user_id: int
    target_member_id: UUID


class FoundationUnitOfWork(Protocol):
    """Transactional storage operations required by the application layer."""

    async def acquire_update_gate(self, update_id: int) -> None:
        """Acquire the transaction-scoped update gate."""
        ...

    async def get_receipt(self, update_id: int) -> UpdateReceipt | None:
        """Read a complete receipt by exact update ID."""
        ...

    async def get_member_by_telegram_user_id(self, telegram_user_id: int) -> Member | None:
        """Resolve an actor without making an access decision."""
        ...

    async def lock_members(self, member_ids: Sequence[UUID]) -> dict[UUID, Member]:
        """Lock and return members in deterministic UUID order."""
        ...

    async def save_member(self, member: Member) -> None:
        """Persist security-relevant member state."""
        ...

    async def flush_member_changes(self) -> None:
        """Send the locked member mutation to PostgreSQL before later effects."""
        ...

    async def append_member_audit(
        self,
        *,
        actor_id: UUID,
        before: Member,
        after: Member,
        reason: str | None,
    ) -> None:
        """Append one member change audit event."""
        ...

    async def add_receipt(
        self,
        *,
        update_id: int,
        update_type: str,
        actor_id: UUID | None,
        outcome_code: str,
    ) -> None:
        """Stage one fully populated receipt."""
        ...

    async def commit(self) -> None:
        """Commit the complete transaction."""
        ...


class UnitOfWorkFactory(Protocol):
    """Create isolated unit-of-work contexts."""

    def __call__(self) -> AbstractAsyncContextManager[FoundationUnitOfWork]:
        """Return a fresh unit-of-work context."""
        ...


class MemberFoundationService:
    """Orchestrate deterministic routing and atomic administrative changes."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        after_member_saved: Callable[[], None] | None = None,
    ) -> None:
        """Configure the transaction factory and an optional fault-injection hook."""
        self._unit_of_work_factory = unit_of_work_factory
        self._after_member_saved = after_member_saved

    async def process_start(self, *, update_id: int, telegram_user_id: int) -> StartOutcome:
        """Persist and return the deterministic route for one accepted update."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(update_id)
            receipt = await unit_of_work.get_receipt(update_id)
            if receipt is not None:
                return StartOutcome(receipt.outcome_code)

            member = await unit_of_work.get_member_by_telegram_user_id(telegram_user_id)
            outcome = route_start(member)
            await unit_of_work.add_receipt(
                update_id=update_id,
                update_type="start",
                actor_id=None if member is None else member.id,
                outcome_code=outcome.value,
            )
            await unit_of_work.commit()
        return outcome

    async def read_member(self, query: ReadMemberQuery) -> Member:
        """Read a member after checking current persisted actor and target rows."""
        async with self._unit_of_work_factory() as unit_of_work:
            unresolved_actor = await unit_of_work.get_member_by_telegram_user_id(
                query.telegram_user_id
            )
            if unresolved_actor is None:
                message = "Read actor is not a registered member."
                raise AuthorizationError(message)
            locked = await unit_of_work.lock_members((unresolved_actor.id, query.target_member_id))
            actor = locked[unresolved_actor.id]
            target = locked[query.target_member_id]
            if not can_read_member(actor=actor, target=target):
                message = "Actor is not allowed to read the target member."
                raise AuthorizationError(message)
            return target

    async def change_member(
        self,
        command: AdministrativeChange,
    ) -> AdministrativeChangeResult:
        """Apply one authorized member change and its audit event atomically."""
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.acquire_update_gate(command.update_id)
            receipt = await unit_of_work.get_receipt(command.update_id)
            if receipt is not None:
                return AdministrativeChangeResult(outcome_code=receipt.outcome_code)

            unresolved_actor = await unit_of_work.get_member_by_telegram_user_id(
                command.telegram_user_id
            )
            if unresolved_actor is None:
                message = "Administrative actor is not a registered member."
                raise PermissionError(message)
            locked = await unit_of_work.lock_members(
                (unresolved_actor.id, command.target_member_id)
            )
            actor = locked[unresolved_actor.id]
            before = locked[command.target_member_id]
            after = change_member(
                actor=actor,
                target=before,
                kind=command.kind,
                requested_value=command.requested_value,
            )
            await unit_of_work.save_member(after)
            await unit_of_work.flush_member_changes()
            if self._after_member_saved is not None:
                self._after_member_saved()
            await unit_of_work.append_member_audit(
                actor_id=actor.id,
                before=before,
                after=after,
                reason=command.reason,
            )
            await unit_of_work.add_receipt(
                update_id=command.update_id,
                update_type=f"member_{command.kind.value}_change",
                actor_id=actor.id,
                outcome_code="member_changed",
            )
            await unit_of_work.commit()
        return AdministrativeChangeResult(outcome_code="member_changed")
