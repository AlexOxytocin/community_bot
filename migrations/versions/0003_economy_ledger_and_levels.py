"""Create the economic ledger and versioned product levels.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable economy and product configuration structures."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM members
                WHERE credit_balance_cached <> 0
                   OR experience_total_cached <> 0
                   OR level_number <> 1
            ) THEN
                RAISE EXCEPTION
                    'legacy member caches must be zero at level 1 before economy migration';
            END IF;
        END;
        $$
        """
    )
    op.alter_column(
        "members",
        "credit_balance_cached",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="credit_balance_cached::bigint",
    )
    op.alter_column(
        "members",
        "experience_total_cached",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="experience_total_cached::bigint",
    )

    _create_account_transactions()
    _create_product_configuration()
    _create_immutability_triggers()
    _create_reversal_trigger()


def downgrade() -> None:
    """Remove empty economy structures without discarding economic history."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_transactions)
               OR EXISTS (SELECT 1 FROM product_config_versions)
               OR EXISTS (
                    SELECT 1 FROM members
                    WHERE credit_balance_cached <> 0
                       OR experience_total_cached <> 0
                       OR level_number <> 1
                       OR level_config_version_id IS NOT NULL
               ) THEN
                RAISE EXCEPTION
                    'economy migration cannot be downgraded with persisted economic state';
            END IF;
        END;
        $$
        """
    )

    op.execute("DROP TRIGGER account_transactions_validate_reversal ON account_transactions")
    op.execute("DROP FUNCTION validate_account_transaction_reversal()")
    op.execute("DROP TRIGGER active_product_config_guard ON active_product_config")
    op.execute("DROP FUNCTION guard_active_product_config()")
    for table_name in (
        "level_backfill_runs",
        "product_config_activations",
        "levels",
        "product_config_versions",
        "account_transactions",
    ):
        op.execute(f"DROP TRIGGER {table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION reject_immutable_economy_mutation()")

    op.drop_constraint(
        "fk_members_level_config_version",
        "members",
        type_="foreignkey",
    )
    op.drop_column("members", "level_config_version_id")
    op.drop_table("level_backfill_runs")
    op.drop_table("active_product_config")
    op.drop_table("product_config_activations")
    op.drop_table("levels")
    op.drop_table("product_config_versions")
    op.drop_index(
        "uq_account_transactions_starting_grant_member",
        table_name="account_transactions",
    )
    op.drop_index(
        "ix_account_transactions_member_history",
        table_name="account_transactions",
    )
    op.drop_table("account_transactions")

    op.alter_column(
        "members",
        "experience_total_cached",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="experience_total_cached::integer",
    )
    op.alter_column(
        "members",
        "credit_balance_cached",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="credit_balance_cached::integer",
    )


def _create_account_transactions() -> None:
    op.create_table(
        "account_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credit_delta", sa.BigInteger(), nullable=False),
        sa.Column("experience_delta", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("created_by_member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reversed_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "transaction_type IN ('starting_grant', 'task_reward_reserved', "
            "'task_reward_earned', 'task_reward_refunded', 'partial_task_reward', "
            "'community_task_reward', 'penalty', 'admin_adjustment', 'fraud_reversal')",
            name="ck_account_transactions_type",
        ),
        sa.CheckConstraint(
            "(transaction_type = 'starting_grant' AND credit_delta = 5 "
            "AND experience_delta = 0) OR "
            "(transaction_type = 'task_reward_reserved' AND credit_delta < 0 "
            "AND experience_delta = 0) OR "
            "(transaction_type IN ('task_reward_earned', 'partial_task_reward', "
            "'community_task_reward') AND credit_delta > 0 "
            "AND experience_delta = credit_delta) OR "
            "(transaction_type = 'task_reward_refunded' AND credit_delta > 0 "
            "AND experience_delta = 0) OR "
            "(transaction_type = 'penalty' AND credit_delta < 0 "
            "AND experience_delta = 0) OR "
            "(transaction_type = 'admin_adjustment' "
            "AND (credit_delta <> 0 OR experience_delta <> 0)) OR "
            "(transaction_type = 'fraud_reversal' "
            "AND (credit_delta <> 0 OR experience_delta <> 0))",
            name="ck_account_transactions_deltas",
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.ForeignKeyConstraint(
            ["reversed_transaction_id"],
            ["account_transactions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("reversed_transaction_id"),
    )
    op.create_index(
        "ix_account_transactions_member_history",
        "account_transactions",
        ["member_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "uq_account_transactions_starting_grant_member",
        "account_transactions",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("transaction_type = 'starting_grant'"),
    )


def _create_product_configuration() -> None:
    op.create_table(
        "product_config_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_table(
        "levels",
        sa.Column("product_config_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level_number", sa.Integer(), nullable=False),
        sa.Column("experience_required", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level_up_message", sa.Text(), nullable=True),
        sa.Column("permissions_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_config_version_id"],
            ["product_config_versions.id"],
        ),
        sa.PrimaryKeyConstraint("product_config_version_id", "level_number"),
        sa.UniqueConstraint(
            "product_config_version_id",
            "experience_required",
            name="uq_levels_config_experience",
        ),
    )
    op.create_table(
        "product_config_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_config_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activated_by_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_code", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_config_version_id"],
            ["product_config_versions.id"],
        ),
        sa.ForeignKeyConstraint(["activated_by_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activation_command_id"),
    )
    op.create_table(
        "active_product_config",
        sa.Column("singleton_key", sa.Boolean(), nullable=False),
        sa.Column("product_config_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("singleton_key", name="ck_active_product_config_singleton"),
        sa.ForeignKeyConstraint(
            ["product_config_version_id"],
            ["product_config_versions.id"],
        ),
        sa.ForeignKeyConstraint(["activation_id"], ["product_config_activations.id"]),
        sa.PrimaryKeyConstraint("singleton_key"),
    )
    op.create_table(
        "level_backfill_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_config_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("processed_members", sa.Integer(), nullable=False),
        sa.Column("outcome_code", sa.Text(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["activation_id"], ["product_config_activations.id"]),
        sa.ForeignKeyConstraint(
            ["product_config_version_id"],
            ["product_config_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activation_id"),
    )
    op.add_column(
        "members",
        sa.Column("level_config_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_members_level_config_version",
        "members",
        "product_config_versions",
        ["level_config_version_id"],
        ["id"],
    )


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_immutable_economy_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "account_transactions",
        "product_config_versions",
        "levels",
        "product_config_activations",
        "level_backfill_runs",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_immutable_economy_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION guard_active_product_config() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'active product config pointer cannot be deleted';
            END IF;
            IF NEW.singleton_key IS DISTINCT FROM OLD.singleton_key THEN
                RAISE EXCEPTION 'active product config singleton key cannot change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER active_product_config_guard
        BEFORE UPDATE OR DELETE ON active_product_config
        FOR EACH ROW EXECUTE FUNCTION guard_active_product_config()
        """
    )


def _create_reversal_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_account_transaction_reversal() RETURNS trigger AS $$
        DECLARE
            source_member_id uuid;
            source_credit_delta bigint;
            source_experience_delta bigint;
            source_transaction_type text;
        BEGIN
            IF NEW.transaction_type <> 'fraud_reversal' THEN
                IF NEW.reversed_transaction_id IS NOT NULL THEN
                    RAISE EXCEPTION 'only fraud_reversal may reference a source transaction';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.reversed_transaction_id IS NULL THEN
                RAISE EXCEPTION 'fraud_reversal requires a source transaction';
            END IF;

            SELECT member_id, credit_delta, experience_delta, transaction_type
              INTO source_member_id, source_credit_delta,
                   source_experience_delta, source_transaction_type
              FROM account_transactions
             WHERE id = NEW.reversed_transaction_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'reversal source transaction does not exist';
            END IF;
            IF source_transaction_type = 'fraud_reversal' THEN
                RAISE EXCEPTION 'a reversal cannot reverse another reversal';
            END IF;
            IF NEW.member_id <> source_member_id THEN
                RAISE EXCEPTION 'reversal member must match its source';
            END IF;
            IF NEW.credit_delta <> -source_credit_delta
               OR NEW.experience_delta <> -source_experience_delta THEN
                RAISE EXCEPTION 'reversal deltas must be exact source inverses';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_transactions_validate_reversal
        BEFORE INSERT ON account_transactions
        FOR EACH ROW EXECUTE FUNCTION validate_account_transaction_reversal()
        """
    )
