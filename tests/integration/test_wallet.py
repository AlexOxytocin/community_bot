from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from community_bot.application.economy import EconomyService, ProductConfigBootstrapCoordinator
from community_bot.application.identity import ActorContext
from community_bot.application.wallet import (
    TransferCommand,
    TransfersLockedError,
    WalletService,
    transfer_commands,
)
from community_bot.bootstrap.product_config import load_product_config_candidate
from community_bot.bootstrap.settings import Settings
from community_bot.domain.economy import (
    IdempotencyConflictError,
    InsufficientBalanceError,
    ReversalCommand,
    earn_community_reward,
    refund_reward,
    reserve_reward,
    starting_grant,
)
from community_bot.domain.notifications import DeliveryWindow
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import (
    MemberModel,
    NotificationModel,
    TaskCategoryModel,
    TaskModel,
)
from community_bot.infrastructure.outbox.postgres import PostgresNotificationQueue
from community_bot.transport.web import create_web_app

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
WalletAccounts = tuple[Database, WalletService, list[ActorContext]]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest_asyncio.fixture
async def wallet_accounts(database_url: str) -> AsyncIterator[WalletAccounts]:
    db = Database(database_url)
    sessions = async_sessionmaker(db.engine, expire_on_commit=False)
    async with sessions.begin() as session:
        members = [
            MemberModel(
                telegram_user_id=800 + i,
                display_name=f"Wallet {i}",
                timezone="UTC",
                role="administrator" if i == 0 else "member",
                status="active",
                level_number=1,
            )
            for i in range(3)
        ]
        session.add_all(members)
    await ProductConfigBootstrapCoordinator(db.unit_of_work, load_product_config_candidate).prepare(
        candidate_path=Path(__file__).parents[2] / "config/product-config.v1.json",
        actor_member_id=members[0].id,
        activation_command_id=uuid4(),
        reason="Wallet fixture",
    )
    economy = EconomyService(db.unit_of_work)
    await economy.apply_batch(tuple(starting_grant(member.id) for member in members))
    await economy.apply_one(
        earn_community_reward(member_id=members[0].id, amount=95, idempotency_key="wallet-earned")
    )
    async with sessions.begin() as session:
        await session.execute(text("UPDATE members SET role='member'"))
    actors = [
        ActorContext(
            member_id=m.id,
            provider="telegram",
            authenticated_at=datetime.datetime.now(datetime.UTC),
        )
        for m in members
    ]
    try:
        yield db, WalletService(db.unit_of_work), actors
    finally:
        await db.dispose()


async def test_wallet_concurrency_replay_history_and_atomic_pair(  # noqa: PLR0915
    wallet_accounts: WalletAccounts,
) -> None:
    db, service, actors = wallet_accounts
    sender, recipient, other = actors
    command = TransferCommand(recipient.member_id, 80, "same-operation", "Спасибо")
    origin = "http://127.0.0.1:8000"
    app = create_web_app(
        settings=Settings(
            _env_file=None,
            environment="development",
            bot_token="123456:LOCAL_TEST_TOKEN",  # noqa: S106 - synthetic test-only token.
            mini_app_origin=origin,
            local_review_telegram_user_id=800,
        ),
        database=db,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        assert (await client.get("/api/v1/wallet")).status_code == 401
        assert (await client.get("/local-review")).status_code == 303
        headers = {"origin": origin, "idempotency-key": "12345"}
        payload = {"recipient_id": str(command.recipient_id), "amount": 80, "comment": "Спасибо"}
        bad_origin = await client.post(
            "/api/v1/wallet/transfers",
            json=payload,
            headers={**headers, "origin": "https://other.example"},
        )
        assert bad_origin.status_code == 403
        invalid = await client.post(
            "/api/v1/wallet/transfers", json={**payload, "amount": "80"}, headers=headers
        )
        assert invalid.status_code == 422
        responses = await asyncio.gather(
            *(
                client.post("/api/v1/wallet/transfers", json=payload, headers=headers)
                for _ in range(2)
            )
        )
        assert sorted(response.status_code for response in responses) == [200, 201]
        receipts = [response.json() for response in responses]
        assert (await client.get("/api/v1/wallet")).json()["balance"] == 35
    assert receipts[0]["transfer_id"] == receipts[1]["transfer_id"]
    assert sorted(item["replayed"] for item in receipts) == [False, True]
    assert (await service.read(sender))["balance"] == 35
    assert (await service.read(recipient))["balance"] == 100
    assert (await service.read(sender))["earned"] == 95
    assert (await service.read(recipient))["earned"] == 0
    with pytest.raises(TransfersLockedError):
        await service.transfer(recipient, TransferCommand(sender.member_id, 1, "locked"))
    with pytest.raises(IdempotencyConflictError):
        await service.transfer(sender, TransferCommand(other.member_id, 80, "12345"))
    page = await service.read(sender, kind="history", limit=1, cursor=None)
    assert page["items"][0]["balance_after"] == 35
    assert page["items"][0]["counterparty_id"] == recipient.member_id
    assert page["next_cursor"]
    older = await service.read(sender, kind="history", limit=5, cursor=page["next_cursor"])
    assert len(older["items"]) == 2
    with pytest.raises(LookupError):
        await service.read(
            other, kind="operation", transaction_id=page["items"][0]["transaction_id"]
        )
    results = await asyncio.gather(
        *(
            service.transfer(sender, TransferCommand(person.member_id, 30, str(uuid4())))
            for person in (recipient, other)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, InsufficientBalanceError) for result in results) == 1
    assert (await service.read(sender))["balance"] == 5
    async with db.engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM wallet_transfers")) == 2
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM outbox_events WHERE event_type='wallet.transfer_received'"
                )
            )
            == 2
        )
        assert (
            await connection.scalar(
                text(
                    "SELECT sum(credit_delta) FROM account_transactions "
                    "WHERE transaction_type LIKE 'transfer_%'"
                )
            )
            == 0
        )
    sessions = async_sessionmaker(db.engine, expire_on_commit=False)
    queue = PostgresNotificationQueue(sessions)
    now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    claims = await queue.claim_outbox(
        now=now, limit=10, lease_duration=datetime.timedelta(minutes=1)
    )
    for claim in claims:
        await queue.materialize(
            claim, now=now, window=DeliveryWindow(start=datetime.time(0), end=datetime.time(23, 59))
        )
    async with sessions() as session:
        notices = (await session.scalars(select(NotificationModel))).all()
        assert len(notices) == 2
        assert all(notice.member_id != sender.member_id for notice in notices)
        assert sorted(notice.payload_json["amount"] for notice in notices) == [30, 80]


async def test_unpaired_transfer_is_rejected_by_database(wallet_accounts: WalletAccounts) -> None:
    db, _, actors = wallet_accounts
    _, pair = transfer_commands(
        actors[0].member_id, TransferCommand(actors[1].member_id, 10, "orphan")
    )
    with pytest.raises(DBAPIError):
        await EconomyService(db.unit_of_work).apply_one(pair[0])
    async with db.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(MemberModel.credit_balance_cached).where(
                    MemberModel.id == actors[0].member_id
                )
            )
            == 115
        )


async def test_wallet_resolves_published_reserve_and_its_reversal(
    wallet_accounts: WalletAccounts,
) -> None:
    db, service, actors = wallet_accounts
    owner, other, admin = actors
    now = datetime.datetime.now(datetime.UTC)
    sessions = async_sessionmaker(db.engine, expire_on_commit=False)
    publication = uuid4()
    async with sessions.begin() as session:
        category = await session.scalar(select(TaskCategoryModel).limit(1))
        assert category is not None
        task = TaskModel(
            origin="member",
            creator_id=owner.member_id,
            author_display_name="Owner",
            category_id=category.id,
            title="Связанное задание",
            description="Task",
            completion_criteria="Done",
            materials_json={},
            input_payload_json={},
            credit_reward_per_performer=2,
            performer_slots=1,
            reserved_credit_total=2,
            estimated_minutes=10,
            minimum_level=1,
            format="online",
            deadline_at=now + datetime.timedelta(days=1),
            safety_snapshot_json={},
            publish_command_id=publication,
            published_at=now,
        )
        session.add(task)
    economy = EconomyService(db.unit_of_work)
    reserve = await economy.apply_one(
        reserve_reward(
            member_id=owner.member_id,
            amount=2,
            idempotency_key=f"task_publish:{publication}:reserve",
        )
    )
    operation = await service.read(owner, kind="operation", transaction_id=reserve.transaction_id)
    assert operation["task_id"] == task.id
    assert operation["task_title"] == task.title
    assert operation["task_owned"] is True
    with pytest.raises(LookupError):
        await service.read(other, kind="operation", transaction_id=reserve.transaction_id)
    async with sessions.begin() as session:
        await session.execute(
            text("UPDATE members SET role='administrator' WHERE id=:id"), {"id": admin.member_id}
        )
    reversal = await economy.apply_one(
        ReversalCommand(
            reversed_transaction_id=reserve.transaction_id,
            idempotency_key="reserve-reversal",
            actor_member_id=admin.member_id,
            reason="Пересмотр",
        )
    )
    operation = await service.read(owner, kind="operation", transaction_id=reversal.transaction_id)
    assert operation["task_id"] == task.id
    assert operation["reversed_transaction_id"] == reserve.transaction_id
    assert operation["actor_name"] == "Wallet 2"
    for prefix, suffix in (("task_cancel", "refund"), ("task_close", "free_slots:refund")):
        refund = await economy.apply_one(
            refund_reward(
                member_id=owner.member_id,
                amount=2,
                idempotency_key=f"{prefix}:{task.id}:{suffix}",
            )
        )
        operation = await service.read(
            owner, kind="operation", transaction_id=refund.transaction_id
        )
        assert operation["task_id"] == task.id


async def test_wallet_immutable_pair_and_revoked_earnings(wallet_accounts: WalletAccounts) -> None:
    db, service, actors = wallet_accounts
    sender, recipient, admin = actors
    receipt = await service.transfer(sender, TransferCommand(recipient.member_id, 10, "immutable"))
    async with db.engine.begin() as connection:
        await connection.execute(
            text("UPDATE members SET role='administrator' WHERE id=:id"), {"id": admin.member_id}
        )
        earned_id = await connection.scalar(
            text("SELECT id FROM account_transactions WHERE idempotency_key='wallet-earned'")
        )
    with pytest.raises(DBAPIError, match="immutable"):
        async with db.engine.begin() as connection:
            await connection.execute(
                text("UPDATE wallet_transfers SET amount=11 WHERE id=:id"),
                {"id": receipt["transfer_id"]},
            )
    with pytest.raises(IdempotencyConflictError, match="individual transfer"):
        await EconomyService(db.unit_of_work).apply_one(
            ReversalCommand(
                reversed_transaction_id=receipt["transaction_id"],
                idempotency_key="illegal-leg-reversal",
                actor_member_id=admin.member_id,
                reason="Test rejection of one-leg reversal",
            )
        )
    await EconomyService(db.unit_of_work).apply_one(
        ReversalCommand(
            reversed_transaction_id=earned_id,
            idempotency_key="revoked-reward",
            actor_member_id=admin.member_id,
            reason="Test cancelled reward",
        )
    )
    summary = await service.read(sender)
    assert summary["earned"] == 0
    assert summary["balance"] == 10
    assert not summary["transfers_enabled"]
    replay = await service.transfer(sender, TransferCommand(recipient.member_id, 10, "immutable"))
    assert replay["replayed"]
    assert replay["balance_after"] == 105
