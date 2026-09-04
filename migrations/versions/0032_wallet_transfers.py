# ruff: noqa: E501 - migration SQL statements kept intact for review.
"""Add conserved peer transfers and twenty-credit starting grants.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_TYPES = "transaction_type IN ('starting_grant','task_reward_reserved','task_reward_earned','task_reward_refunded','partial_task_reward','community_task_reward','penalty','admin_adjustment','fraud_reversal','resolution_reversal','manual_credit_grant'{extra})"
_DELTAS = """
 (transaction_type = 'starting_grant' AND credit_delta IN ({grants}) AND experience_delta = 0)
 OR (transaction_type = 'task_reward_reserved' AND credit_delta < 0 AND experience_delta = 0)
 OR (transaction_type IN ('task_reward_earned','partial_task_reward','community_task_reward') AND credit_delta > 0 AND experience_delta = credit_delta)
 OR (transaction_type IN ('task_reward_refunded','manual_credit_grant') AND credit_delta > 0 AND experience_delta = 0)
 OR (transaction_type = 'penalty' AND credit_delta < 0 AND experience_delta = 0)
 OR (transaction_type IN ('admin_adjustment','fraud_reversal','resolution_reversal') AND (credit_delta <> 0 OR experience_delta <> 0))
 {extra}
"""


def _constraints(*, new: bool) -> None:
    for name in ("ck_account_transactions_type", "ck_account_transactions_deltas"):
        op.drop_constraint(name, "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_type",
        "account_transactions",
        _TYPES.format(extra=",'transfer_sent','transfer_received'" if new else ""),
    )
    op.create_check_constraint(
        "ck_account_transactions_deltas",
        "account_transactions",
        _DELTAS.format(
            grants="5,10,20" if new else "5,10",
            extra="OR (transaction_type = 'transfer_sent' AND credit_delta < 0 AND experience_delta = 0) OR (transaction_type = 'transfer_received' AND credit_delta > 0 AND experience_delta = 0)"
            if new
            else "",
        ),
    )


def upgrade() -> None:
    """Keep historical grants and require conserved immutable transfer pairs."""
    _constraints(new=True)
    op.add_column(
        "account_transactions", sa.Column("balance_after", sa.BigInteger(), nullable=True)
    )
    op.create_table(
        "wallet_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sender_id", sa.Uuid(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "outgoing_id",
            sa.Uuid(),
            sa.ForeignKey("account_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "incoming_id",
            sa.Uuid(),
            sa.ForeignKey("account_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("amount > 0 AND sender_id <> recipient_id", name="ck_wallet_transfer"),
    )
    op.execute("""
    CREATE FUNCTION check_wallet_transfer() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t wallet_transfers; a account_transactions; b account_transactions;
    BEGIN
      IF TG_TABLE_NAME = 'wallet_transfers' THEN
        t := NEW;
      ELSE
        IF NEW.reversed_transaction_id IS NOT NULL AND EXISTS (
          SELECT 1 FROM account_transactions WHERE id = NEW.reversed_transaction_id
          AND transaction_type IN ('transfer_sent','transfer_received')) THEN
          RAISE EXCEPTION 'individual transfer legs cannot be reversed';
        END IF;
        IF NEW.transaction_type NOT IN ('transfer_sent','transfer_received') THEN RETURN NEW; END IF;
        SELECT * INTO t FROM wallet_transfers WHERE outgoing_id = NEW.id OR incoming_id = NEW.id;
        IF NOT FOUND THEN RAISE EXCEPTION 'transfer leg requires a conserved pair'; END IF;
      END IF;
      SELECT * INTO a FROM account_transactions WHERE id = t.outgoing_id;
      SELECT * INTO b FROM account_transactions WHERE id = t.incoming_id;
      IF a.transaction_type <> 'transfer_sent' OR b.transaction_type <> 'transfer_received'
         OR a.member_id <> t.sender_id OR b.member_id <> t.recipient_id
         OR a.credit_delta <> -t.amount OR b.credit_delta <> t.amount
         OR a.experience_delta <> 0 OR b.experience_delta <> 0
         OR a.created_by_member_id IS DISTINCT FROM t.sender_id
         OR b.created_by_member_id IS DISTINCT FROM t.sender_id THEN
        RAISE EXCEPTION 'invalid transfer pair';
      END IF;
      RETURN NEW;
    END $$;
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER wallet_pair AFTER INSERT ON wallet_transfers DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_wallet_transfer()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER wallet_leg AFTER INSERT ON account_transactions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_wallet_transfer()"
    )
    op.execute(
        "CREATE FUNCTION reject_wallet_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'wallet transfers are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER wallet_immutable BEFORE UPDATE OR DELETE ON wallet_transfers FOR EACH ROW EXECUTE FUNCTION reject_wallet_mutation()"
    )


def downgrade() -> None:
    """Only reverse the schema before new wallet data has been committed."""
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM wallet_transfers) OR EXISTS (
        SELECT 1 FROM account_transactions WHERE transaction_type = 'starting_grant' AND credit_delta = 20
      ) THEN RAISE EXCEPTION 'wallet rollback requires pre-cutover backup'; END IF;
    END $$;""")
    op.execute("DROP TRIGGER wallet_leg ON account_transactions")
    op.drop_table("wallet_transfers")
    op.execute("DROP FUNCTION check_wallet_transfer()")
    op.execute("DROP FUNCTION reject_wallet_mutation()")
    op.drop_column("account_transactions", "balance_after")
    _constraints(new=False)
