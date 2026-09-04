# ruff: noqa: D102, D107, EM101, TRY003, PLR0913
"""Private wallet reads and atomic, credit-only peer transfers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid5

from community_bot.domain.economy import EconomyCommand, TransactionType
from community_bot.domain.members import AuthorizationError, MemberStatus

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from community_bot.application.economy import EconomyMutationPort
    from community_bot.application.identity import ActorContext
    from community_bot.domain.members import Member

TRANSFER_THRESHOLD = 50
MAX_TRANSFER = 1_000_000_000
MAX_OPERATION_KEY = 128
MAX_COMMENT = 140
MAX_QUERY = 80
MAX_PAGE = 100


class TransfersLockedError(ValueError):
    """The sender has not earned enough verified task credits."""


@dataclass(frozen=True, slots=True)
class TransferCommand:
    """The sender comes from the session, never from the submitted body."""

    recipient_id: UUID
    amount: int
    operation_key: str
    comment: str | None = None


class WalletStore(Protocol):
    """Wallet persistence inside the shared economy transaction."""

    async def summary(self, member_id: UUID) -> dict: ...
    async def history(self, member_id: UUID, *, limit: int, cursor: str | None) -> dict: ...
    async def operation(self, member_id: UUID, transaction_id: UUID) -> dict: ...
    async def recipients(self, member_id: UUID, query: str, limit: int) -> list[dict]: ...
    async def receipt(self, transfer_id: UUID, member_id: UUID) -> dict: ...
    async def record_transfer(
        self,
        *,
        transfer_id: UUID,
        sender_id: UUID,
        recipient_id: UUID,
        amount: int,
        comment: str | None,
        outgoing_id: UUID,
        incoming_id: UUID,
    ) -> None: ...


class WalletUnitOfWork(Protocol):
    """Atomic wallet, ledger, member-cache and outbox boundary."""

    @property
    def economy(self) -> EconomyMutationPort: ...

    @property
    def wallet(self) -> WalletStore: ...

    async def get_member(self, member_id: UUID) -> Member | None: ...
    async def set_repeatable_read(self) -> None: ...
    async def commit(self) -> None: ...


class WalletUnitOfWorkFactory(Protocol):
    """Open one wallet transaction."""

    def __call__(self) -> AbstractAsyncContextManager[WalletUnitOfWork]: ...


def transfer_commands(
    sender_id: UUID, command: TransferCommand
) -> tuple[UUID, tuple[EconomyCommand, ...]]:
    """Validate and bind both legs to one stable sender-scoped operation identity."""
    if sender_id == command.recipient_id:
        raise ValueError("Self transfer is not allowed.")
    if type(command.amount) is not int or not 1 <= command.amount <= MAX_TRANSFER:
        raise ValueError("Transfer amount must be a positive bounded integer.")
    if not command.operation_key.strip() or len(command.operation_key) > MAX_OPERATION_KEY:
        raise ValueError("Invalid operation key.")
    comment = (command.comment or "").strip() or None
    if comment is not None and len(comment) > MAX_COMMENT:
        raise ValueError("Transfer comment is too long.")
    transfer_id = uuid5(sender_id, command.operation_key)
    commands = tuple(
        EconomyCommand(
            transaction_type=kind,
            member_id=member,
            credit_delta=delta,
            experience_delta=0,
            actor_member_id=sender_id,
            comment=comment,
            idempotency_key=f"wallet_transfer:{transfer_id}:{leg}",
        )
        for kind, member, delta, leg in (
            (TransactionType.TRANSFER_SENT, sender_id, -command.amount, "out"),
            (TransactionType.TRANSFER_RECEIVED, command.recipient_id, command.amount, "in"),
        )
    )
    return transfer_id, commands


class WalletService:
    """Authorize private reads and pair transfers under economy locks."""

    def __init__(self, unit_of_work_factory: WalletUnitOfWorkFactory) -> None:
        self._uow = unit_of_work_factory

    @staticmethod
    def _active(member: Member | None) -> None:
        if member is None or member.status is not MemberStatus.ACTIVE:
            raise AuthorizationError("An active wallet account is required.")

    async def read(
        self,
        actor: ActorContext,
        *,
        kind: str = "summary",
        limit: int = 30,
        cursor: str | None = None,
        transaction_id: UUID | None = None,
        transfer_id: UUID | None = None,
        query: str = "",
    ) -> dict:
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError("Invalid wallet page size.")
        async with self._uow() as uow:
            await uow.set_repeatable_read()
            self._active(await uow.get_member(actor.member_id))
            if kind == "summary":
                return await uow.wallet.summary(actor.member_id)
            if kind == "history":
                return await uow.wallet.history(actor.member_id, limit=limit, cursor=cursor)
            if kind == "operation":
                if transaction_id is None:
                    raise ValueError("Missing transaction identity.")
                return await uow.wallet.operation(actor.member_id, transaction_id)
            if kind == "receipt":
                if transfer_id is None:
                    raise ValueError("Missing transfer identity.")
                return await uow.wallet.receipt(transfer_id, actor.member_id)
            if kind != "recipients":
                raise ValueError("Unknown wallet projection.")
            query = " ".join(query.split()).lstrip("@")
            if not 1 <= len(query) <= MAX_QUERY:
                raise ValueError("Recipient query is required.")
            return {"items": await uow.wallet.recipients(actor.member_id, query, limit)}

    async def transfer(self, actor: ActorContext, command: TransferCommand) -> dict:
        transfer_id, commands = transfer_commands(actor.member_id, command)
        async with self._uow() as uow:
            prepared = await uow.economy.prepare_batch(commands)
            self._active(prepared.members.get(actor.member_id))
            # Existing committed receipts remain replayable even if the recipient is now inactive.
            try:
                existing = await uow.wallet.receipt(transfer_id, actor.member_id)
            except LookupError:
                existing = None
            if existing is not None:
                await prepared.apply()  # Verifies the exact original payload, never mutates twice.
                return {**existing, "replayed": True}
            self._active(prepared.members.get(command.recipient_id))
            summary = await uow.wallet.summary(actor.member_id)
            if not summary["transfers_enabled"]:
                raise TransfersLockedError("Earn 50 task credits before sending transfers.")
            outgoing, incoming = await prepared.apply()
            await uow.wallet.record_transfer(
                transfer_id=transfer_id,
                sender_id=actor.member_id,
                recipient_id=command.recipient_id,
                amount=command.amount,
                comment=commands[0].comment,
                outgoing_id=outgoing.transaction_id,
                incoming_id=incoming.transaction_id,
            )
            receipt = await uow.wallet.receipt(transfer_id, actor.member_id)
            await uow.commit()
            return {**receipt, "replayed": False}
