# ruff: noqa: D102, D107, EM101, TRY003, S608, PLR0913
"""Wallet projections over the existing immutable economy ledger."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from community_bot.application.wallet import TRANSFER_THRESHOLD
from community_bot.infrastructure.db.models import (
    MemberModel,
    OutboxEventModel,
    WalletTransferModel,
)

_REWARDS = "('task_reward_earned','partial_task_reward','community_task_reward')"


class SqlAlchemyWalletStore:
    """Private projections; every query is constrained by the session member."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, member_id: UUID) -> dict:
        row = (
            (
                await self.session.execute(
                    text(f"""
          SELECT m.credit_balance_cached AS balance,
            COALESCE((SELECT sum(t.credit_delta) FROM account_transactions t
              LEFT JOIN account_transactions original ON original.id = t.reversed_transaction_id
              WHERE t.member_id = m.id
              AND COALESCE(original.transaction_type,t.transaction_type)
                IN {_REWARDS}),0) AS earned,
            COALESCE((SELECT -sum(t.credit_delta) FROM account_transactions t
              LEFT JOIN account_transactions original ON original.id=t.reversed_transaction_id
              WHERE t.member_id=m.id AND COALESCE(original.transaction_type,t.transaction_type)
                IN ('task_reward_reserved','task_reward_refunded')),0)
            - COALESCE((SELECT sum(t.credit_delta) FROM account_transactions t
              LEFT JOIN account_transactions original ON original.id=t.reversed_transaction_id
              LEFT JOIN assignments a ON a.id=COALESCE(t.assignment_id,original.assignment_id)
              JOIN tasks task ON task.id=COALESCE(t.task_id,original.task_id,a.task_id)
              WHERE task.creator_id=m.id
              AND COALESCE(original.transaction_type,t.transaction_type)
                IN {_REWARDS}),0) AS reserved
          FROM members m WHERE m.id=:member
        """),
                    {"member": member_id},
                )
            )
            .mappings()
            .one()
        )
        earned = max(0, int(row["earned"]))
        return {
            "balance": int(row["balance"]),
            "reserved": max(0, int(row["reserved"])),
            "earned": earned,
            "transfer_threshold": TRANSFER_THRESHOLD,
            "transfers_enabled": earned >= TRANSFER_THRESHOLD,
        }

    async def recipients(self, member_id: UUID, query: str, limit: int) -> list[dict]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = (
            await self.session.scalars(
                select(MemberModel)
                .where(
                    MemberModel.id != member_id,
                    MemberModel.status == "active",
                    MemberModel.display_name.ilike(f"%{escaped}%", escape="\\")
                    | MemberModel.telegram_username.ilike(f"%{escaped}%", escape="\\"),
                )
                .order_by(MemberModel.display_name, MemberModel.id)
                .limit(limit)
            )
        ).all()
        return [self._person(row) for row in rows]

    @staticmethod
    def _person(row: MemberModel) -> dict:
        return {
            "member_id": row.id,
            "display_name": row.display_name,
            "telegram_username": row.telegram_username,
        }

    async def _history(
        self,
        member_id: UUID,
        *,
        limit: int = 30,
        cursor: str | None = None,
        transaction_id: UUID | None = None,
    ) -> dict:
        params = {"member": member_id, "limit": limit + 1}
        where = "TRUE"
        if cursor:
            stamp, identifier = cursor.rsplit("|", 1)
            timestamp = datetime.datetime.fromisoformat(stamp)
            if timestamp.tzinfo is None:
                raise ValueError("History cursor requires timezone.")
            params.update(stamp=timestamp, identifier=UUID(identifier))
            where = "(h.created_at,h.id) < (:stamp,:identifier)"
        if transaction_id:
            params["transaction"] = transaction_id
            where = "h.id=:transaction"
        rows = (
            (
                await self.session.execute(
                    text(f"""
          WITH h AS (
            SELECT t.*, sum(t.credit_delta) OVER (ORDER BY t.created_at,t.id) AS historical_balance
            FROM account_transactions t WHERE t.member_id=:member
          )
          SELECT h.id AS transaction_id,h.transaction_type,h.credit_delta,h.experience_delta,
            h.comment,h.reason,h.created_at,task.id AS task_id,task.title AS task_title,
            h.reversed_transaction_id,
            COALESCE(h.balance_after,h.historical_balance) AS balance_after,
            h.balance_after IS NULL AS balance_reconstructed,
            wt.id AS transfer_id, peer.display_name AS counterparty_name,
            peer.telegram_username AS counterparty_username
          FROM h LEFT JOIN assignments assignment ON assignment.id=h.assignment_id
          LEFT JOIN tasks task ON task.id=COALESCE(h.task_id,assignment.task_id)
          LEFT JOIN wallet_transfers wt ON wt.outgoing_id=h.id OR wt.incoming_id=h.id
          LEFT JOIN members peer ON peer.id=CASE WHEN wt.sender_id=:member
            THEN wt.recipient_id ELSE wt.sender_id END
          WHERE {where} ORDER BY h.created_at DESC,h.id DESC LIMIT :limit
        """),
                    params,
                )
            )
            .mappings()
            .all()
        )
        items = [dict(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = f"{last['created_at'].isoformat()}|{last['transaction_id']}"
        return {"items": items, "next_cursor": next_cursor}

    async def history(self, member_id: UUID, *, limit: int, cursor: str | None) -> dict:
        return await self._history(member_id, limit=limit, cursor=cursor)

    async def operation(self, member_id: UUID, transaction_id: UUID) -> dict:
        page = await self._history(member_id, transaction_id=transaction_id)
        if not page["items"]:
            raise LookupError("Wallet operation not found.")
        return page["items"][0]

    async def receipt(self, transfer_id: UUID, member_id: UUID) -> dict:
        transfer = await self.session.get(WalletTransferModel, transfer_id)
        if transfer is None or transfer.sender_id != member_id:
            raise LookupError("Transfer receipt not found.")
        recipient = await self.session.get(MemberModel, transfer.recipient_id)
        operation = await self.operation(member_id, transfer.outgoing_id)
        return {
            "transfer_id": transfer.id,
            "transaction_id": transfer.outgoing_id,
            "recipient": self._person(recipient),
            "amount": transfer.amount,
            "comment": transfer.comment,
            "balance_after": int(operation["balance_after"]),
            "created_at": transfer.created_at,
            "replayed": False,
        }

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
    ) -> None:
        values = {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "amount": amount,
            "comment": comment,
            "outgoing_id": outgoing_id,
            "incoming_id": incoming_id,
        }
        transfer = WalletTransferModel(id=transfer_id, **values)
        self.session.add(transfer)
        self.session.add(
            OutboxEventModel(
                event_type="wallet.transfer_received",
                aggregate_type="member",
                aggregate_id=values["recipient_id"],
                payload_json={"amount": values["amount"]},
                business_key=f"wallet_transfer:{transfer_id}",
            )
        )
        await self.session.flush()
