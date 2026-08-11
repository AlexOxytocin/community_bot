# ruff: noqa: E501
"""Add disputes, sanctions, interaction alerts, and risk signals.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()


def upgrade() -> None:
    """Create the complete MVP moderation persistence boundary."""
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        "jsonb_typeof(permissions_json) = 'array' AND "
        'permissions_json <@ \'["karma_review","member_read","interaction_review"]\'::jsonb',
    )
    op.add_column(
        "assignments",
        sa.Column("slot_ever_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE assignments SET slot_ever_paid = true "
        "WHERE status IN ('approved','partially_approved')"
    )
    op.drop_index("uq_assignments_occupied_slot", table_name="assignments")
    op.create_index(
        "uq_assignments_occupied_slot",
        "assignments",
        ["task_id", "slot_number"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('accepted','submitted','rejected_pending_dispute','disputed',"
            "'reviewer_required','approved','partially_approved','rejected','no_show') "
            "OR slot_ever_paid"
        ),
    )
    op.execute(
        "UPDATE members SET permissions_json = permissions_json || '[\"interaction_review\"]'::jsonb "
        "WHERE role = 'administrator' AND status = 'active' "
        "AND NOT permissions_json @> '[\"interaction_review\"]'::jsonb"
    )
    op.drop_constraint("ck_account_transactions_type", "account_transactions", type_="check")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_type",
        "account_transactions",
        "transaction_type IN ('starting_grant','task_reward_reserved','task_reward_earned',"
        "'task_reward_refunded','partial_task_reward','community_task_reward','penalty',"
        "'admin_adjustment','fraud_reversal','resolution_reversal')",
    )
    op.create_check_constraint(
        "ck_account_transactions_deltas",
        "account_transactions",
        "(transaction_type = 'starting_grant' AND credit_delta = 5 AND experience_delta = 0) OR "
        "(transaction_type = 'task_reward_reserved' AND credit_delta < 0 AND experience_delta = 0) OR "
        "(transaction_type IN ('task_reward_earned','partial_task_reward','community_task_reward') "
        "AND credit_delta > 0 AND experience_delta = credit_delta) OR "
        "(transaction_type = 'task_reward_refunded' AND credit_delta > 0 AND experience_delta = 0) OR "
        "(transaction_type = 'penalty' AND credit_delta < 0 AND experience_delta = 0) OR "
        "(transaction_type = 'admin_adjustment' AND (credit_delta <> 0 OR experience_delta <> 0)) OR "
        "(transaction_type IN ('fraud_reversal','resolution_reversal') "
        "AND (credit_delta <> 0 OR experience_delta <> 0))",
    )
    _allow_resolution_reversals()
    op.create_table(
        "moderation_cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assignment_id", UUID, sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("dispute_id", UUID, sa.ForeignKey("assignment_disputes.id"), unique=True),
        sa.Column("case_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("opened_by_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("open_command_id", UUID, unique=True, nullable=False),
        sa.Column("open_payload_hash", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("current_resolution_id", UUID),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("case_type IN ('dispute','fraud_review')", name="ck_cases_type"),
        sa.CheckConstraint("status IN ('open','resolved','appealed')", name="ck_cases_status"),
    )
    op.create_index(
        "uq_moderation_cases_active_assignment",
        "moderation_cases",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open','resolved','appealed')"),
    )
    op.execute(
        "INSERT INTO moderation_cases (id, assignment_id, dispute_id, case_type, status, "
        "opened_by_member_id, open_command_id, open_payload_hash, reason, revision, opened_at) "
        "SELECT gen_random_uuid(), assignment_id, id, 'dispute', 'open', performer_id, "
        "open_command_id, md5(comment), comment, 0, opened_at "
        "FROM assignment_disputes"
    )
    op.create_table(
        "dispute_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("moderation_cases.id"), nullable=False),
        sa.Column("author_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_dispute_evidence_case_id", "dispute_evidence", ["case_id"])
    op.create_table(
        "dispute_resolutions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, sa.ForeignKey("moderation_cases.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("actor_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("command_id", UUID, unique=True, nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("effect_json", JSONB, nullable=False),
        sa.Column("conflict_snapshot_json", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version IN (1,2)", name="ck_dispute_resolution_version"),
        sa.UniqueConstraint("case_id", "version", name="uq_dispute_resolution_version"),
    )
    op.create_foreign_key(
        "fk_moderation_cases_current_resolution",
        "moderation_cases",
        "dispute_resolutions",
        ["current_resolution_id"],
        ["id"],
    )
    op.create_table(
        "reliability_outcome_corrections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("assignment_id", UUID, sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("case_id", UUID, sa.ForeignKey("moderation_cases.id"), nullable=False),
        sa.Column("resolution_version", sa.Integer(), nullable=False),
        sa.Column("previous_outcome", sa.Text(), nullable=False),
        sa.Column("new_outcome", sa.Text(), nullable=False),
        sa.Column("actor_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("case_id", "resolution_version", name="uq_reliability_case_version"),
    )
    op.create_table(
        "dispute_appeals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "case_id", UUID, sa.ForeignKey("moderation_cases.id"), unique=True, nullable=False
        ),
        sa.Column("appellant_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("command_id", UUID, unique=True, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "moderation_decision_drafts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("case_id", UUID, sa.ForeignKey("moderation_cases.id"), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolution_command_id", UUID, unique=True, nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state IN ('pending','confirmed')", name="ck_moderation_draft_state"),
    )
    op.create_table(
        "member_sanctions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("target_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("author_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("sanction_type", sa.Text(), nullable=False),
        sa.Column("restricted_actions_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("previous_status", sa.Text()),
        sa.Column("applied_status", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False, server_default="active"),
        sa.Column("command_id", UUID, unique=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "sanction_type IN ('notice','warning','restriction','suspension','ban')",
            name="ck_member_sanctions_type",
        ),
        sa.CheckConstraint("state IN ('active','revoked','expired')", name="ck_sanctions_state"),
    )
    op.create_index(
        "ix_member_sanctions_target_member_id", "member_sanctions", ["target_member_id"]
    )
    op.create_table(
        "sanction_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("sanction_id", UUID, sa.ForeignKey("member_sanctions.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_member_id", UUID, sa.ForeignKey("members.id")),
        sa.Column("reason", sa.Text()),
        sa.Column("command_id", UUID, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "interaction_alerts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("first_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("second_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="open"),
        sa.Column("interaction_count", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column(
            "config_version_id", UUID, sa.ForeignKey("product_config_versions.id"), nullable=False
        ),
        sa.Column("outcome", sa.Text()),
        sa.Column("meeting_notes", sa.Text()),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("first_member_id < second_member_id", name="ck_alert_pair_order"),
        sa.CheckConstraint("state IN ('open','closed')", name="ck_alert_state"),
    )
    op.create_index(
        "uq_interaction_alert_open_pair",
        "interaction_alerts",
        ["first_member_id", "second_member_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_table(
        "interaction_alert_assignments",
        sa.Column("alert_id", UUID, sa.ForeignKey("interaction_alerts.id"), primary_key=True),
        sa.Column("assignment_id", UUID, sa.ForeignKey("assignments.id"), primary_key=True),
        sa.UniqueConstraint("alert_id", "assignment_id", name="uq_alert_assignment"),
    )
    op.create_table(
        "moderation_risk_signals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("target_member_id", UUID, sa.ForeignKey("members.id")),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), unique=True, nullable=False),
        sa.Column("details_json", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "karma_vote_moderation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("karma_vote_id", UUID, sa.ForeignKey("karma_votes.id"), nullable=False),
        sa.Column("vote_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("actor_member_id", UUID, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("command_id", UUID, unique=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("state IN ('excluded','restored')", name="ck_karma_moderation_state"),
    )
    _protect_history()


def downgrade() -> None:
    """Remove moderation persistence and restore the prior permission set."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM account_transactions
                WHERE transaction_type = 'resolution_reversal'
            ) THEN
                RAISE EXCEPTION
                    'migration 0009 cannot be downgraded after a resolution reversal';
            END IF;
        END;
        $$
        """
    )
    for table in (
        "karma_vote_moderation",
        "moderation_risk_signals",
        "sanction_events",
        "dispute_appeals",
        "dispute_evidence",
        "dispute_resolutions",
        "reliability_outcome_corrections",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS protect_moderation_history()")
    op.drop_table("karma_vote_moderation")
    op.drop_table("moderation_risk_signals")
    op.drop_table("interaction_alert_assignments")
    op.drop_table("interaction_alerts")
    op.drop_table("sanction_events")
    op.drop_table("member_sanctions")
    op.drop_table("moderation_decision_drafts")
    op.drop_table("dispute_appeals")
    op.drop_table("reliability_outcome_corrections")
    op.drop_constraint(
        "fk_moderation_cases_current_resolution", "moderation_cases", type_="foreignkey"
    )
    op.drop_table("dispute_resolutions")
    op.drop_index("ix_dispute_evidence_case_id", table_name="dispute_evidence")
    op.drop_table("dispute_evidence")
    op.drop_index("uq_moderation_cases_active_assignment", table_name="moderation_cases")
    op.drop_table("moderation_cases")
    op.drop_index("uq_assignments_occupied_slot", table_name="assignments")
    op.create_index(
        "uq_assignments_occupied_slot",
        "assignments",
        ["task_id", "slot_number"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('accepted','submitted','rejected_pending_dispute','disputed',"
            "'reviewer_required','approved','partially_approved','rejected','no_show')"
        ),
    )
    op.drop_column("assignments", "slot_ever_paid")
    _restore_fraud_only_reversals()
    op.drop_constraint("ck_account_transactions_type", "account_transactions", type_="check")
    op.drop_constraint("ck_account_transactions_deltas", "account_transactions", type_="check")
    op.create_check_constraint(
        "ck_account_transactions_type",
        "account_transactions",
        "transaction_type IN ('starting_grant','task_reward_reserved','task_reward_earned',"
        "'task_reward_refunded','partial_task_reward','community_task_reward','penalty',"
        "'admin_adjustment','fraud_reversal')",
    )
    op.create_check_constraint(
        "ck_account_transactions_deltas",
        "account_transactions",
        "(transaction_type = 'starting_grant' AND credit_delta = 5 AND experience_delta = 0) OR "
        "(transaction_type = 'task_reward_reserved' AND credit_delta < 0 AND experience_delta = 0) OR "
        "(transaction_type IN ('task_reward_earned','partial_task_reward','community_task_reward') "
        "AND credit_delta > 0 AND experience_delta = credit_delta) OR "
        "(transaction_type = 'task_reward_refunded' AND credit_delta > 0 AND experience_delta = 0) OR "
        "(transaction_type = 'penalty' AND credit_delta < 0 AND experience_delta = 0) OR "
        "(transaction_type = 'admin_adjustment' AND (credit_delta <> 0 OR experience_delta <> 0)) OR "
        "(transaction_type = 'fraud_reversal' AND (credit_delta <> 0 OR experience_delta <> 0))",
    )
    op.execute("UPDATE members SET permissions_json = permissions_json - 'interaction_review'")
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        "permissions_json IN ('[]'::jsonb, '[\"karma_review\"]'::jsonb, "
        '\'["member_read"]\'::jsonb, \'["karma_review","member_read"]\'::jsonb, '
        '\'["member_read","karma_review"]\'::jsonb)',
    )


def _protect_history() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_moderation_history() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'moderation history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "dispute_evidence",
        "dispute_resolutions",
        "reliability_outcome_corrections",
        "dispute_appeals",
        "sanction_events",
        "moderation_risk_signals",
        "karma_vote_moderation",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_moderation_history()"
        )


def _allow_resolution_reversals() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_account_transaction_reversal() RETURNS trigger AS $$
        DECLARE
            source_member_id uuid;
            source_credit_delta bigint;
            source_experience_delta bigint;
            source_transaction_type text;
        BEGIN
            IF NEW.transaction_type NOT IN ('fraud_reversal', 'resolution_reversal') THEN
                IF NEW.reversed_transaction_id IS NOT NULL THEN
                    RAISE EXCEPTION 'only reversal transactions may reference a source transaction';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.reversed_transaction_id IS NULL THEN
                RAISE EXCEPTION 'reversal requires a source transaction';
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
            IF source_transaction_type IN ('fraud_reversal', 'resolution_reversal') THEN
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


def _restore_fraud_only_reversals() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_account_transaction_reversal() RETURNS trigger AS $$
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
