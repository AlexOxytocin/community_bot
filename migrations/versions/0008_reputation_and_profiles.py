# ruff: noqa: E501
"""Add karma, profile permissions, and reliability invariants.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the MVP reputation persistence boundary."""
    op.add_column(
        "members",
        sa.Column(
            "permissions_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_members_permissions",
        "members",
        "permissions_json IN ('[]'::jsonb, '[\"karma_review\"]'::jsonb, "
        "'[\"member_read\"]'::jsonb, "
        '\'["karma_review","member_read"]\'::jsonb, '
        '\'["member_read","karma_review"]\'::jsonb)',
    )
    op.execute(
        "UPDATE members SET permissions_json = "
        '\'["karma_review","member_read"]\'::jsonb '
        "WHERE role = 'administrator' AND status = 'active'"
    )
    op.add_column(
        "conversation_states",
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_conversation_states_revision", "conversation_states", "revision >= 0"
    )
    op.create_table(
        "karma_votes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rater_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rater_id <> target_id", name="ck_karma_votes_not_self"),
        sa.CheckConstraint("value IN (-1,0,1)", name="ck_karma_votes_value"),
        sa.CheckConstraint("revision > 0", name="ck_karma_votes_revision"),
        sa.ForeignKeyConstraint(["rater_id"], ["members.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rater_id", "target_id", name="uq_karma_votes_pair"),
        sa.UniqueConstraint("last_command_id"),
    )
    op.create_index("ix_karma_votes_target", "karma_votes", ["target_id"])
    op.create_table(
        "karma_vote_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("karma_vote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("old_value", sa.Integer()),
        sa.Column("new_value", sa.Integer(), nullable=False),
        sa.Column("old_comment", sa.Text()),
        sa.Column("new_comment", sa.Text(), nullable=False),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["karma_vote_id"], ["karma_votes.id"]),
        sa.ForeignKeyConstraint(["actor_member_id"], ["members.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("karma_vote_id", "revision", name="uq_karma_history_revision"),
        sa.UniqueConstraint("command_id"),
    )
    _create_karma_history_trigger()
    _create_reliability_constraints()


def downgrade() -> None:
    """Remove reputation storage and restore the prior member schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_reliability_event_validate ON reliability_events")
    op.execute("DROP FUNCTION IF EXISTS validate_reliability_event()")
    op.drop_index("uq_reliability_superseded_once", table_name="reliability_events")
    op.drop_index("uq_reliability_terminal_root", table_name="reliability_events")
    op.execute("DROP TRIGGER IF EXISTS trg_karma_vote_history_immutable ON karma_vote_history")
    op.execute("DROP FUNCTION IF EXISTS protect_karma_vote_history()")
    op.drop_table("karma_vote_history")
    op.drop_index("ix_karma_votes_target", table_name="karma_votes")
    op.drop_table("karma_votes")
    op.drop_constraint("ck_conversation_states_revision", "conversation_states", type_="check")
    op.drop_column("conversation_states", "revision")
    op.drop_constraint("ck_members_permissions", "members", type_="check")
    op.drop_column("members", "permissions_json")


def _create_karma_history_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_karma_vote_history() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'karma vote history is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_karma_vote_history_immutable BEFORE UPDATE OR DELETE "
        "ON karma_vote_history FOR EACH ROW EXECUTE FUNCTION protect_karma_vote_history()"
    )


def _create_reliability_constraints() -> None:
    op.create_index(
        "uq_reliability_terminal_root",
        "reliability_events",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text(
            "supersedes_event_id IS NULL AND event_type IN "
            "('approved','partially_approved','rejected','no_show','cancelled_performer','cancelled_creator')"
        ),
    )
    op.create_index(
        "uq_reliability_superseded_once",
        "reliability_events",
        ["supersedes_event_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_event_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION validate_reliability_event() RETURNS trigger AS $$
        DECLARE parent reliability_events%ROWTYPE;
        BEGIN
            IF NEW.event_type NOT IN (
                'accepted','approved','partially_approved','rejected','no_show',
                'cancelled_performer','cancelled_creator',
                'responsibility_excused','responsibility_restored'
            ) THEN
                RAISE EXCEPTION 'unsupported reliability event';
            END IF;
            IF NEW.supersedes_event_id IS NULL THEN
                IF NEW.event_type IN ('responsibility_excused','responsibility_restored') THEN
                    RAISE EXCEPTION 'responsibility correction requires a parent';
                END IF;
                RETURN NEW;
            END IF;
            SELECT * INTO parent FROM reliability_events WHERE id = NEW.supersedes_event_id FOR UPDATE;
            IF NOT FOUND OR parent.assignment_id <> NEW.assignment_id THEN
                RAISE EXCEPTION 'reliability correction must stay in one assignment';
            END IF;
            IF parent.event_type = 'accepted' OR NEW.event_type NOT IN (
                'responsibility_excused','responsibility_restored'
            ) THEN
                RAISE EXCEPTION 'invalid reliability supersede';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_reliability_event_validate BEFORE INSERT ON reliability_events "
        "FOR EACH ROW EXECUTE FUNCTION validate_reliability_event()"
    )
