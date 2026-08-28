# ruff: noqa: D102, D107, EM101, PLR2004, TRY003
"""Superadministrator credit grants backed by the immutable economy ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from community_bot.domain.economy import AdministrativeContext, manual_credit_grant
from community_bot.domain.members import (
    AuthorizationError,
    MemberStatus,
    is_superadministrator,
)

if TYPE_CHECKING:
    import datetime
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from community_bot.application.economy import EconomyMutationPort, LedgerHistoryCursor
    from community_bot.application.identity import ActorContext
    from community_bot.domain.members import Member


@dataclass(frozen=True, slots=True)
class CreditGrantRecipient:
    """One existing account available as a grant recipient."""

    member_id: UUID
    telegram_username: str | None
    display_name: str
    status: str
    credit_balance: int


@dataclass(frozen=True, slots=True)
class CreditGrantRecord:
    """One immutable manual grant enriched for administrative history."""

    transaction_id: UUID
    recipient: CreditGrantRecipient
    actor_member_id: UUID
    actor_telegram_username: str | None
    actor_display_name: str
    amount: int
    reason: str
    created_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class CreditGrantHistoryPage:
    """One stable descending page of manual grants."""

    items: tuple[CreditGrantRecord, ...]
    next_cursor: LedgerHistoryCursor | None


@dataclass(frozen=True, slots=True)
class CreditGrantCommand:
    """One idempotent superadministrator grant request."""

    actor_member_id: UUID
    target_member_id: UUID
    amount: int
    reason: str
    operation_key: str


@dataclass(frozen=True, slots=True)
class CreditGrantReceipt:
    """Persisted result returned after the ledger and cache commit together."""

    transaction_id: UUID
    recipient: CreditGrantRecipient
    amount: int
    reason: str
    replayed: bool


class CreditGrantUnitOfWork(Protocol):
    """Storage needed by the superadministrator grant workflow."""

    @property
    def economy(self) -> EconomyMutationPort: ...

    async def get_member(self, member_id: UUID) -> Member | None: ...

    async def credit_grant_recipients(
        self, *, query: str, limit: int
    ) -> tuple[CreditGrantRecipient, ...]: ...

    async def credit_grant_recipient(self, member_id: UUID) -> CreditGrantRecipient | None: ...

    async def credit_grant_history(
        self, *, limit: int, cursor: LedgerHistoryCursor | None
    ) -> CreditGrantHistoryPage: ...

    async def commit(self) -> None: ...


class CreditGrantUnitOfWorkFactory(Protocol):
    """Create isolated grant transactions."""

    def __call__(self) -> AbstractAsyncContextManager[CreditGrantUnitOfWork]: ...


class CreditGrantService:
    """Authorize, persist, and query credit-only administrative grants."""

    def __init__(self, unit_of_work_factory: CreditGrantUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def self_recipient(self, actor: ActorContext) -> CreditGrantRecipient:
        """Return the current superadministrator's own selectable card."""
        async with self._unit_of_work_factory() as uow:
            await self._active_superadministrator(uow, actor.member_id)
            recipient = await uow.credit_grant_recipient(actor.member_id)
            if recipient is None:
                raise LookupError("Member does not exist.")
            return recipient

    async def recipients(
        self, actor: ActorContext, *, query: str, limit: int
    ) -> tuple[CreditGrantRecipient, ...]:
        """Search all existing accounts by display name or Telegram username."""
        normalized = " ".join(query.split()).lstrip("@")
        if not normalized or len(normalized) > 80:
            raise ValueError("A recipient search query is required.")
        async with self._unit_of_work_factory() as uow:
            await self._active_superadministrator(uow, actor.member_id)
            return await uow.credit_grant_recipients(query=normalized, limit=limit)

    async def recipient(self, actor: ActorContext, member_id: UUID) -> CreditGrantRecipient:
        """Return one existing account after superadministrator authorization."""
        async with self._unit_of_work_factory() as uow:
            await self._active_superadministrator(uow, actor.member_id)
            recipient = await uow.credit_grant_recipient(member_id)
            if recipient is None:
                raise LookupError("Member does not exist.")
            return recipient

    async def grant(self, command: CreditGrantCommand, actor: ActorContext) -> CreditGrantReceipt:
        """Append one grant and update the recipient cache atomically."""
        if command.actor_member_id != actor.member_id:
            raise AuthorizationError("Grant actor identity does not match the session.")
        reason = " ".join(command.reason.split())
        if not 3 <= len(reason) <= 500:
            raise ValueError("Grant reason must contain between 3 and 500 characters.")
        if isinstance(command.amount, bool) or command.amount <= 0:
            raise ValueError("Grant amount must be a positive integer.")
        economy_command = manual_credit_grant(
            member_id=command.target_member_id,
            amount=command.amount,
            idempotency_key=(f"manual_credit_grant:{actor.member_id}:{command.operation_key}"),
            context=AdministrativeContext(
                actor_member_id=actor.member_id,
                reason=reason,
            ),
        )
        async with self._unit_of_work_factory() as uow:
            prepared = await uow.economy.prepare_batch(
                (economy_command,), additional_member_ids=(actor.member_id,)
            )
            current = prepared.members[actor.member_id]
            self._require_active_superadministrator(current)
            result = (await prepared.apply())[0]
            recipient = await uow.credit_grant_recipient(command.target_member_id)
            if recipient is None:
                raise LookupError("Member does not exist.")
            await uow.commit()
            return CreditGrantReceipt(
                transaction_id=result.transaction_id,
                recipient=recipient,
                amount=command.amount,
                reason=reason,
                replayed=result.replayed,
            )

    async def history(
        self,
        actor: ActorContext,
        *,
        limit: int,
        cursor: LedgerHistoryCursor | None,
    ) -> CreditGrantHistoryPage:
        """Read immutable global grant history for a current superadministrator."""
        async with self._unit_of_work_factory() as uow:
            await self._active_superadministrator(uow, actor.member_id)
            return await uow.credit_grant_history(limit=limit, cursor=cursor)

    async def _active_superadministrator(
        self, uow: CreditGrantUnitOfWork, member_id: UUID
    ) -> Member:
        member = await uow.get_member(member_id)
        if member is None:
            raise AuthorizationError("An active superadministrator is required.")
        self._require_active_superadministrator(member)
        return member

    @staticmethod
    def _require_active_superadministrator(member: Member) -> None:
        if member.status is not MemberStatus.ACTIVE or not is_superadministrator(member):
            raise AuthorizationError("An active superadministrator is required.")
