"""Tagged activities and granular task subscriptions, preserving effective consent.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_NEW = ("online", "offline", "task_updates", "task_reminders", "disputes")


def upgrade() -> None:
    """New event topics opt out; split existing task consent without broadening it."""
    for category in _NEW:
        op.add_column(
            "member_notification_preferences",
            sa.Column(category, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(
            "member_notification_preferences",
            sa.Column(f"{category}_since", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute("""UPDATE member_notification_preferences SET
        task_updates=tasks, task_reminders=tasks, disputes=tasks,
        task_updates_since=tasks_since, task_reminders_since=tasks_since,
        disputes_since=tasks_since, revision=revision+1""")
    op.create_table(
        "activity_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("message_url", sa.Text(), nullable=False),
        sa.Column("parts_json", postgresql.JSONB(), nullable=False),
        sa.Column("categories_json", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("chat_id", "source_key"),
    )
    # A topic-only campaign must not escape the cutover after switching to explicit tags.
    op.execute("""UPDATE notifications SET status='failed', last_error_code='legacy_topic_retired',
        lease_token=NULL, lease_expires_at=NULL
        WHERE notification_type='nomad.published' AND status IN ('pending','processing')""")
    op.execute("""UPDATE outbox_events SET status='failed', last_error_code='legacy_topic_retired',
        lease_token=NULL, lease_expires_at=NULL
        WHERE event_type='nomad.published' AND status IN ('pending','processing')""")


def downgrade() -> None:
    """Collapse preferences conservatively; never turn an opt-out back on."""
    op.execute("""UPDATE member_notification_preferences SET
        tasks=tasks AND task_updates AND task_reminders AND disputes, revision=revision+1""")
    op.drop_table("activity_publications")
    for category in reversed(_NEW):
        op.drop_column("member_notification_preferences", f"{category}_since")
        op.drop_column("member_notification_preferences", category)
