"""Unlock the synthetic local-review wallet through an idempotent test reward."""

from __future__ import annotations

import asyncio
import datetime
import json

from sqlalchemy import select

from community_bot.application.economy import EconomyService
from community_bot.application.identity import ActorContext
from community_bot.application.wallet import TRANSFER_THRESHOLD, WalletService
from community_bot.domain.economy import earn_community_reward
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.models import AccountTransactionModel, MemberModel
from ops.seed_task_home_local import _REVIEW_TELEGRAM_USER_ID, _database_url


async def seed() -> dict:
    """Never target production or a real Telegram identity; preserve ledger invariants."""
    database = Database(_database_url())
    try:
        async with database.session_factory() as session:
            member = await session.scalar(
                select(MemberModel).where(
                    MemberModel.telegram_user_id == _REVIEW_TELEGRAM_USER_ID,
                    MemberModel.status == "active",
                )
            )
            if member is None:
                raise RuntimeError("Active synthetic local-review account is missing.")
            actor = ActorContext(
                member_id=member.id,
                provider="telegram",
                authenticated_at=datetime.datetime.now(datetime.UTC),
            )
            key = f"local_wallet_preview:{member.id}:unlock:v1"
            existing = await session.scalar(
                select(AccountTransactionModel.id).where(
                    AccountTransactionModel.idempotency_key == key
                )
            )
        wallet = WalletService(database.unit_of_work)
        before = await wallet.read(actor)
        if before["transfers_enabled"]:
            return {"changed": False, **before}
        if existing is not None:
            raise RuntimeError("Local reward was already used; refusing another grant.")
        await EconomyService(database.unit_of_work).apply_one(
            earn_community_reward(
                member_id=member.id,
                amount=TRANSFER_THRESHOLD - before["earned"],
                idempotency_key=key,
                comment="Локальное тестовое начисление для проверки переводов; не production.",
            )
        )
        return {"changed": True, **await wallet.read(actor)}
    finally:
        await database.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed()), ensure_ascii=False))
