from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from community_bot.application.identity import ActorContext
from community_bot.application.wallet import (
    TransferCommand,
    TransfersLockedError,
    WalletService,
    transfer_commands,
)
from community_bot.domain.economy import starting_grant, validate_economy_command
from community_bot.domain.members import AuthorizationError, MemberStatus


def test_transfer_pair_is_conserved_stable_and_credit_only() -> None:
    sender, recipient = uuid4(), uuid4()
    command = TransferCommand(recipient, 15, "one-operation", " Спасибо ")
    identity, pair = transfer_commands(sender, command)
    assert transfer_commands(sender, command) == (identity, pair)
    assert sum(item.credit_delta for item in pair) == 0
    assert all(item.experience_delta == 0 for item in pair)
    assert all(item.comment == "Спасибо" for item in pair)
    for item in pair:
        validate_economy_command(item)
    assert starting_grant(sender).credit_delta == 20


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, 1_000_000_001])
def test_invalid_transfer_amount(amount: float) -> None:
    with pytest.raises(ValueError, match="positive bounded integer"):
        transfer_commands(uuid4(), TransferCommand(uuid4(), amount, "operation"))


def test_self_transfer_and_empty_identity_rejected() -> None:
    sender = uuid4()
    with pytest.raises(ValueError, match="Self transfer"):
        transfer_commands(sender, TransferCommand(sender, 10, "operation"))
    with pytest.raises(ValueError, match="Invalid operation key"):
        transfer_commands(sender, TransferCommand(uuid4(), 10, ""))


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["sender", "recipient", "threshold"])
async def test_transfer_authorization_stops_before_ledger_writes(blocked: str) -> None:
    sender, recipient = uuid4(), uuid4()
    members = {
        identity: SimpleNamespace(status=MemberStatus.ACTIVE) for identity in (sender, recipient)
    }
    if blocked != "threshold":
        members[sender if blocked == "sender" else recipient].status = MemberStatus.SUSPENDED
    prepared = SimpleNamespace(members=members, apply=AsyncMock())
    wallet = AsyncMock()
    wallet.receipt.side_effect = LookupError("absent")
    wallet.summary.return_value = {"transfers_enabled": False}
    uow = SimpleNamespace(
        economy=SimpleNamespace(prepare_batch=AsyncMock(return_value=prepared)),
        wallet=wallet,
        commit=AsyncMock(),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=uow)
    context.__aexit__ = AsyncMock(return_value=False)
    actor = ActorContext(sender, "telegram", datetime.datetime.now(datetime.UTC))
    error = TransfersLockedError if blocked == "threshold" else AuthorizationError
    with pytest.raises(error):
        await WalletService(lambda: context).transfer(
            actor, TransferCommand(recipient, 1, "blocked")
        )
    prepared.apply.assert_not_awaited()
    wallet.record_transfer.assert_not_awaited()
    uow.commit.assert_not_awaited()
