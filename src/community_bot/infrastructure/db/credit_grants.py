"""PostgreSQL projections for superadministrator credit grants."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import aliased

from community_bot.application.credit_grants import (
    CreditGrantHistoryPage,
    CreditGrantRecipient,
    CreditGrantRecord,
)
from community_bot.application.economy import LedgerHistoryCursor
from community_bot.domain.economy import TransactionType
from community_bot.infrastructure.db.models import AccountTransactionModel, MemberModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def recipients(
    session: AsyncSession, *, query: str, limit: int
) -> tuple[CreditGrantRecipient, ...]:
    """Search every existing account without silently excluding access states."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    models = (
        await session.scalars(
            select(MemberModel)
            .where(
                MemberModel.display_name.ilike(pattern, escape="\\")
                | MemberModel.telegram_username.ilike(pattern, escape="\\")
            )
            .order_by(MemberModel.display_name.asc(), MemberModel.id.asc())
            .limit(limit)
        )
    ).all()
    return tuple(_recipient(model) for model in models)


async def recipient(session: AsyncSession, member_id: UUID) -> CreditGrantRecipient | None:
    """Read one selectable account including its current credit balance."""
    model = await session.get(MemberModel, member_id)
    return None if model is None else _recipient(model)


async def history(
    session: AsyncSession,
    *,
    limit: int,
    cursor: LedgerHistoryCursor | None,
) -> CreditGrantHistoryPage:
    """Read stable descending manual-grant history with actor and recipient labels."""
    recipient_model = aliased(MemberModel)
    actor_model = aliased(MemberModel)
    statement = (
        select(AccountTransactionModel, recipient_model, actor_model)
        .join(recipient_model, recipient_model.id == AccountTransactionModel.member_id)
        .join(actor_model, actor_model.id == AccountTransactionModel.created_by_member_id)
        .where(
            AccountTransactionModel.transaction_type == TransactionType.MANUAL_CREDIT_GRANT.value
        )
    )
    if cursor is not None:
        statement = statement.where(
            (AccountTransactionModel.created_at < cursor.created_at)
            | (
                (AccountTransactionModel.created_at == cursor.created_at)
                & (AccountTransactionModel.id < cursor.transaction_id)
            )
        )
    rows = (
        await session.execute(
            statement.order_by(
                AccountTransactionModel.created_at.desc(),
                AccountTransactionModel.id.desc(),
            ).limit(limit + 1)
        )
    ).all()
    page_rows = rows[:limit]
    items = tuple(
        CreditGrantRecord(
            transaction_id=transaction.id,
            recipient=_recipient(target),
            actor_member_id=actor.id,
            actor_telegram_username=actor.telegram_username,
            actor_display_name=actor.display_name,
            amount=transaction.credit_delta,
            reason=transaction.reason or "",
            created_at=transaction.created_at,
        )
        for transaction, target, actor in page_rows
    )
    next_cursor = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1][0]
        next_cursor = LedgerHistoryCursor(
            created_at=last.created_at,
            transaction_id=last.id,
        )
    return CreditGrantHistoryPage(items=items, next_cursor=next_cursor)


def _recipient(model: MemberModel) -> CreditGrantRecipient:
    return CreditGrantRecipient(
        member_id=model.id,
        telegram_username=model.telegram_username,
        display_name=model.display_name,
        status=model.status,
        credit_balance=model.credit_balance_cached,
    )
