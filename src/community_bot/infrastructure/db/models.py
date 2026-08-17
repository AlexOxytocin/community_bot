"""SQLAlchemy models for members, audit, economy, and product configuration."""

from __future__ import annotations

import datetime  # noqa: TC003 - SQLAlchemy resolves mapped annotations at runtime.
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from community_bot.domain.members import MemberRole, MemberStatus


class Base(DeclarativeBase):
    """Declarative metadata root."""


class TestRunModel(Base):
    """One isolated live smoke-test execution."""

    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'failed')", name="ck_test_runs_status"),
        CheckConstraint("marker LIKE 'TEST-%'", name="ck_test_runs_marker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    marker: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    started_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class TestRunParticipantModel(Base):
    """Member whose live Telegram actions belong to one test run."""

    __tablename__ = "test_run_participants"
    __table_args__ = (
        Index(
            "uq_test_run_participants_active_member",
            "member_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_runs.id"), primary_key=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), primary_key=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    left_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class MemberModel(Base):
    """Persistent member profile and security state."""

    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('member', 'moderator', 'administrator')",
            name="ck_members_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'paused', 'restricted', "
            "'suspended', 'left', 'banned')",
            name="ck_members_status",
        ),
        CheckConstraint(
            "jsonb_typeof(permissions_json) = 'array' AND "
            "permissions_json <@ "
            '\'["karma_review","member_read","interaction_review","superadministrator"]\'::jsonb',
            name="ck_members_permissions",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    short_bio: Mapped[str | None] = mapped_column(Text)
    current_goal: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str | None] = mapped_column(Text)
    help_categories_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    skill_tags_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    permissions_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, default=MemberRole.MEMBER.value)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=MemberStatus.PENDING.value)
    level_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    credit_balance_cached: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    experience_total_cached: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    level_config_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_versions.id")
    )
    invited_by_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InvitationModel(Base):
    """Hashed invitation with an atomic usage allowance."""

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("max_uses > 0", name="ck_invitations_max_uses"),
        CheckConstraint(
            "uses_count >= 0 AND uses_count <= max_uses",
            name="ck_invitations_uses_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    intended_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InvitationRedemptionModel(Base):
    """One member account created through one invitation."""

    __tablename__ = "invitation_redemptions"
    __table_args__ = (
        UniqueConstraint("invitation_id", "member_id", name="uq_invitation_redemption_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invitations.id"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), unique=True, nullable=False
    )
    redeemed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RegistrationApplicationModel(Base):
    """Current moderation state of a member registration."""

    __tablename__ = "registration_applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name="ck_registration_applications_status",
        ),
    )

    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    consented_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConversationStateModel(Base):
    """Persistent resumable Telegram conversation state."""

    __tablename__ = "conversation_states"
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_conversation_states_revision"),)

    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), primary_key=True
    )
    flow_type: Mapped[str] = mapped_column(Text, nullable=False)
    current_step: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TaskCategoryModel(Base):
    """Immutable catalog category with an administrative visibility switch."""

    __tablename__ = "task_categories"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_task_categories_sort_order"),
        CheckConstraint(
            "visibility IN ('public', 'admin_only')",
            name="ck_task_categories_visibility",
        ),
        CheckConstraint(
            "creation_mode IN ('template', 'freeform', 'both')",
            name="ck_task_categories_creation_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="public")
    creation_mode: Mapped[str] = mapped_column(Text, nullable=False, default="template")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TaskTemplateModel(Base):
    """One immutable task template version with a mutable catalog switch."""

    __tablename__ = "task_templates"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_task_templates_code_version"),
        CheckConstraint("version > 0", name="ck_task_templates_version"),
        CheckConstraint("credit_reward BETWEEN 1 AND 4", name="ck_task_templates_reward"),
        CheckConstraint("estimated_minutes BETWEEN 1 AND 120", name="ck_task_templates_minutes"),
        CheckConstraint("format IN ('online', 'offline', 'any')", name="ck_task_templates_format"),
        CheckConstraint("minimum_level > 0", name="ck_task_templates_minimum_level"),
        CheckConstraint("maximum_performers BETWEEN 1 AND 10", name="ck_task_templates_performers"),
        Index(
            "uq_task_templates_active_code",
            "code",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "ix_task_templates_catalog",
            "category_id",
            "is_active",
            "minimum_level",
            "code",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_categories.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    creator_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    performer_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    completion_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credit_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    minimum_level: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_performers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    moderation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskCreationDraftModel(Base):
    """Persistent resumable member task creation draft."""

    __tablename__ = "task_creation_drafts"
    __table_args__ = (
        CheckConstraint(
            "current_step IN ('task_kind', 'category', 'time_size', 'reward', 'title', "
            "'description', 'completion_criteria', 'input', 'deadline', 'format', "
            "'materials', 'slots', 'preview', 'published')",
            name="ck_task_creation_drafts_step",
        ),
        CheckConstraint("revision >= 0", name="ck_task_creation_drafts_revision"),
        CheckConstraint(
            "format IS NULL OR format IN ('online', 'offline')",
            name="ck_task_creation_drafts_format",
        ),
        CheckConstraint(
            "performer_slots IS NULL OR performer_slots > 0",
            name="ck_task_creation_drafts_slots",
        ),
        CheckConstraint(
            "task_kind IS NULL OR task_kind IN ('solo', 'group')",
            name="ck_task_creation_drafts_kind",
        ),
        CheckConstraint(
            "time_size IS NULL OR time_size IN ('xs', 's', 'm', 'l', 'xl')",
            name="ck_task_creation_drafts_time_size",
        ),
        CheckConstraint("origin IN ('member', 'community')", name="ck_task_creation_drafts_origin"),
        Index(
            "uq_task_creation_drafts_current_creator",
            "creator_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    test_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_runs.id")
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False, default="member")
    reviewer_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    community_approval_requested_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    community_approved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    community_approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_templates.id")
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_categories.id")
    )
    task_kind: Mapped[str | None] = mapped_column(Text)
    time_size: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    completion_criteria: Mapped[str | None] = mapped_column(Text)
    credit_reward_per_performer: Mapped[int | None] = mapped_column(Integer)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    input_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deadline_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    format: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    materials_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    performer_slots: Mapped[int | None] = mapped_column(Integer)
    current_step: Mapped[str] = mapped_column(Text, nullable=False, default="input")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    publish_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TaskModel(Base):
    """Immutable published task snapshot with a small creation-owned lifecycle."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("origin IN ('member', 'community')", name="ck_tasks_origin"),
        CheckConstraint(
            "status IN ('published', 'settling', 'expired', 'partially_completed', "
            "'completed', 'cancelled', 'closed_for_new_performers')",
            name="ck_tasks_status",
        ),
        CheckConstraint("credit_reward_per_performer > 0", name="ck_tasks_reward"),
        CheckConstraint("performer_slots > 0", name="ck_tasks_slots"),
        CheckConstraint("reserved_credit_total >= 0", name="ck_tasks_reserved_nonnegative"),
        CheckConstraint("minimum_level > 0", name="ck_tasks_minimum_level"),
        CheckConstraint("format IN ('online', 'offline')", name="ck_tasks_format"),
        CheckConstraint(
            "time_size IS NULL OR time_size IN ('xs', 's', 'm', 'l', 'xl')",
            name="ck_tasks_time_size",
        ),
        CheckConstraint("deadline_at > published_at", name="ck_tasks_future_deadline"),
        CheckConstraint(
            "(origin = 'member' AND creator_id IS NOT NULL "
            "AND reserved_credit_total = credit_reward_per_performer * performer_slots) "
            "OR (origin = 'community' AND creator_id IS NULL AND reserved_credit_total = 0)",
            name="ck_tasks_origin_reserve",
        ),
        CheckConstraint(
            "(origin = 'member' AND created_by_admin_id IS NULL "
            "AND reviewer_admin_id IS NULL AND community_approved_by_admin_id IS NULL) OR "
            "(origin = 'community' AND "
            "((created_by_admin_id IS NULL AND reviewer_admin_id IS NULL "
            "AND community_approved_by_admin_id IS NULL) OR "
            "(created_by_admin_id IS NOT NULL AND reviewer_admin_id IS NOT NULL "
            "AND community_approved_by_admin_id IS NOT NULL "
            "AND created_by_admin_id <> reviewer_admin_id)))",
            name="ck_tasks_community_provenance",
        ),
        Index("ix_tasks_creator_created", "creator_id", "created_at", "id"),
        Index("ix_tasks_status_deadline", "status", "deadline_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    test_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_runs.id"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_templates.id")
    )
    template_version: Mapped[int | None] = mapped_column(Integer)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    reviewer_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    community_approved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    author_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_categories.id"), nullable=False
    )
    time_size: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    completion_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    materials_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    credit_reward_per_performer: Mapped[int] = mapped_column(Integer, nullable=False)
    performer_slots: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_credit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_level: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(Text)
    deadline_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="published")
    safety_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    publish_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    published_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    closed_for_new_performers_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OutboxEventModel(Base):
    """Durable internal event awaiting a future delivery worker."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    business_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','materialized','failed')",
            name="ck_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbox_lease_state",
        ),
        CheckConstraint(
            "(status = 'materialized' AND published_at IS NOT NULL) OR status <> 'materialized'",
            name="ck_outbox_materialized_at",
        ),
        CheckConstraint(
            "(status = 'failed' AND last_error_code IS NOT NULL) OR status <> 'failed'",
            name="ck_outbox_failed_error",
        ),
        Index("ix_outbox_due", "status", "next_attempt_at", "created_at"),
    )


class NotificationModel(Base):
    """One addressable, retryable notification derived from a durable event."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','sent','failed')",
            name="ck_notifications_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_notifications_attempt_count"),
        CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_notifications_lease_state",
        ),
        CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL) OR status <> 'sent'",
            name="ck_notifications_sent_at",
        ),
        CheckConstraint(
            "(status = 'failed' AND last_error_code IS NOT NULL) OR status <> 'failed'",
            name="ck_notifications_failed_error",
        ),
        Index("ix_notifications_due", "status", "next_attempt_at", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    scheduled_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(Text)
    deduplication_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProcessHeartbeatModel(Base):
    """Latest readiness heartbeat for one runtime process."""

    __tablename__ = "process_heartbeats"

    process_name: Mapped[str] = mapped_column(Text, primary_key=True)
    release: Mapped[str] = mapped_column(Text, nullable=False)
    migration_revision: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssignmentModel(Base):
    """One immutable acceptance identity with a mutable lifecycle."""

    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "performer_id", name="uq_assignments_task_performer"),
        CheckConstraint("slot_number > 0", name="ck_assignments_slot_positive"),
        CheckConstraint(
            "status IN ('accepted', 'submitted', 'rejected_pending_dispute', 'disputed', "
            "'approved', 'partially_approved', 'rejected', 'cancelled', 'no_show', "
            "'reviewer_required')",
            name="ck_assignments_status",
        ),
        Index(
            "uq_assignments_occupied_slot",
            "task_id",
            "slot_number",
            unique=True,
            postgresql_where=text(
                "status IN ('accepted', 'submitted', 'rejected_pending_dispute', "
                "'disputed', 'reviewer_required', 'approved', 'partially_approved', "
                "'rejected', 'no_show') OR slot_ever_paid"
            ),
        ),
        Index("ix_assignments_performer_status", "performer_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    performer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="accepted")
    accepted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    review_deadline_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reject_dispute_deadline_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_command_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), unique=True
    )
    terminal_outcome: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    slot_ever_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TaskCancellationRequestModel(Base):
    """Durable creator request to cancel all still-unstarted assignments."""

    __tablename__ = "task_cancellation_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','completed','declined','obsolete')",
            name="ck_task_cancellation_requests_status",
        ),
        Index(
            "uq_task_cancellation_requests_pending",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False, index=True
    )
    requested_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class TaskCancellationResponseModel(Base):
    """One performer's durable response to a task cancellation request."""

    __tablename__ = "task_cancellation_responses"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "assignment_id", name="uq_task_cancellation_response_assignment"
        ),
        CheckConstraint(
            "status IN ('pending','accepted','declined','obsolete')",
            name="ck_task_cancellation_responses_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("task_cancellation_requests.id"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    performer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    responded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AssignmentResultVersionModel(Base):
    """Append-only result version submitted by a performer."""

    __tablename__ = "assignment_result_versions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "version", name="uq_assignment_result_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    submit_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssignmentSubmissionDraftModel(Base):
    """Durable Telegram result input and confirmation identity."""

    __tablename__ = "assignment_submission_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False, index=True
    )
    performer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    submit_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    submitted_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignment_result_versions.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssignmentDisputeModel(Base):
    """Immutable private dispute opening handed to future moderation."""

    __tablename__ = "assignment_disputes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), unique=True, nullable=False
    )
    performer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    open_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    opened_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModerationCaseModel(Base):
    """Mutable pointer to immutable moderation case history."""

    __tablename__ = "moderation_cases"
    __table_args__ = (
        CheckConstraint("case_type IN ('dispute', 'fraud_review')", name="ck_cases_type"),
        CheckConstraint("status IN ('open', 'resolved', 'appealed')", name="ck_cases_status"),
        Index(
            "uq_moderation_cases_active_assignment",
            "assignment_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'resolved', 'appealed')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignment_disputes.id"), unique=True
    )
    case_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    opened_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    open_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    open_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    current_resolution_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "dispute_resolutions.id",
            use_alter=True,
            name="fk_moderation_cases_current_resolution",
        ),
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class DisputeEvidenceModel(Base):
    """Append-only privacy-sensitive evidence metadata."""

    __tablename__ = "dispute_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("moderation_cases.id"), nullable=False, index=True
    )
    author_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DisputeResolutionModel(Base):
    """Immutable initial or appeal resolution."""

    __tablename__ = "dispute_resolutions"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_dispute_resolution_version"),
        CheckConstraint("version IN (1, 2)", name="ck_dispute_resolution_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("moderation_cases.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    effect_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conflict_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DisputeAppealModel(Base):
    """One immutable appeal request per moderation case."""

    __tablename__ = "dispute_appeals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("moderation_cases.id"), unique=True, nullable=False
    )
    appellant_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModerationDecisionDraftModel(Base):
    """Durable Telegram preview and confirmation identity."""

    __tablename__ = "moderation_decision_drafts"
    __table_args__ = (
        CheckConstraint("state IN ('pending','confirmed')", name="ck_moderation_draft_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("moderation_cases.id"), nullable=False
    )
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemberSanctionModel(Base):
    """Current sanction state with immutable event history."""

    __tablename__ = "member_sanctions"
    __table_args__ = (
        CheckConstraint(
            "sanction_type IN ('notice','warning','restriction','suspension','ban')",
            name="ck_member_sanctions_type",
        ),
        CheckConstraint("state IN ('active','revoked','expired')", name="ck_sanctions_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True
    )
    author_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    sanction_type: Mapped[str] = mapped_column(Text, nullable=False)
    restricted_actions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    previous_status: Mapped[str | None] = mapped_column(Text)
    applied_status: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SanctionEventModel(Base):
    """Append-only sanction lifecycle event."""

    __tablename__ = "sanction_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sanction_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("member_sanctions.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    command_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InteractionAlertModel(Base):
    """One review episode for an unordered member pair."""

    __tablename__ = "interaction_alerts"
    __table_args__ = (
        CheckConstraint("first_member_id < second_member_id", name="ck_alert_pair_order"),
        CheckConstraint("state IN ('open','closed')", name="ck_alert_state"),
        Index(
            "uq_interaction_alert_open_pair",
            "first_member_id",
            "second_member_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    first_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    second_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    interaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_versions.id"), nullable=False
    )
    outcome: Mapped[str | None] = mapped_column(Text)
    meeting_notes: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class InteractionAlertAssignmentModel(Base):
    """Immutable assignment membership of one alert episode."""

    __tablename__ = "interaction_alert_assignments"
    __table_args__ = (UniqueConstraint("alert_id", "assignment_id", name="uq_alert_assignment"),)

    alert_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interaction_alerts.id"), primary_key=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), primary_key=True
    )


class ModerationRiskSignalModel(Base):
    """Private idempotent signal that never applies an automatic sanction."""

    __tablename__ = "moderation_risk_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    entity_key: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KarmaVoteModerationModel(Base):
    """Reversible exclusion of one exact karma vote revision."""

    __tablename__ = "karma_vote_moderation"
    __table_args__ = (
        CheckConstraint("state IN ('excluded','restored')", name="ck_karma_moderation_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    karma_vote_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("karma_votes.id"), nullable=False
    )
    vote_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReliabilityEventModel(Base):
    """Append-only assignment reliability fact."""

    __tablename__ = "reliability_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    supersedes_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("reliability_events.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReliabilityOutcomeCorrectionModel(Base):
    """Append-only appeal correction of an immutable reliability root."""

    __tablename__ = "reliability_outcome_corrections"
    __table_args__ = (
        UniqueConstraint("case_id", "resolution_version", name="uq_reliability_case_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("moderation_cases.id"), nullable=False
    )
    resolution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    new_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class KarmaVoteModel(Base):
    """Current private karma vote for one ordered member pair."""

    __tablename__ = "karma_votes"
    __table_args__ = (
        UniqueConstraint("rater_id", "target_id", name="uq_karma_votes_pair"),
        CheckConstraint("rater_id <> target_id", name="ck_karma_votes_not_self"),
        CheckConstraint("value IN (-1, 0, 1)", name="ck_karma_votes_value"),
        CheckConstraint("revision > 0", name="ck_karma_votes_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rater_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KarmaVoteHistoryModel(Base):
    """Immutable revision of one private karma vote."""

    __tablename__ = "karma_vote_history"
    __table_args__ = (
        UniqueConstraint("karma_vote_id", "revision", name="uq_karma_history_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    karma_vote_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("karma_votes.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    old_value: Mapped[int | None] = mapped_column(Integer)
    new_value: Mapped[int] = mapped_column(Integer, nullable=False)
    old_comment: Mapped[str | None] = mapped_column(Text)
    new_comment: Mapped[str] = mapped_column(Text, nullable=False)
    command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    actor_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditEventModel(Base):
    """Append-only audit record."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProcessedTelegramUpdateModel(Base):
    """Complete receipt for one committed Telegram update transaction."""

    __tablename__ = "processed_telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    update_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    outcome_code: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WebSessionModel(Base):
    """Short-lived revocable Mini App session stored by token digest."""

    __tablename__ = "web_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(token_digest) = 32", name="ck_web_sessions_digest"),
        CheckConstraint("expires_at > created_at", name="ck_web_sessions_expiry"),
        CheckConstraint("authenticated_at <= expires_at", name="ck_web_sessions_authenticated_at"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_web_sessions_revoked_at",
        ),
    )

    token_digest: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    authenticated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AccountTransactionModel(Base):
    """Append-only source of truth for credits and experience."""

    __tablename__ = "account_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('starting_grant', 'task_reward_reserved', "
            "'task_reward_earned', 'task_reward_refunded', 'partial_task_reward', "
            "'community_task_reward', 'penalty', 'admin_adjustment', 'fraud_reversal', "
            "'resolution_reversal')",
            name="ck_account_transactions_type",
        ),
        CheckConstraint(
            "(transaction_type = 'starting_grant' AND credit_delta IN (5, 10) "
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
            "(transaction_type IN ('fraud_reversal', 'resolution_reversal') "
            "AND (credit_delta <> 0 OR experience_delta <> 0))",
            name="ck_account_transactions_deltas",
        ),
        Index(
            "ix_account_transactions_member_history",
            "member_id",
            "created_at",
            "id",
        ),
        Index(
            "uq_account_transactions_starting_grant_member",
            "member_id",
            unique=True,
            postgresql_where=text("transaction_type = 'starting_grant'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    credit_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    experience_delta: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_member_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    reversed_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("account_transactions.id"), unique=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tasks.id"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assignments.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductConfigVersionModel(Base):
    """Immutable product configuration version."""

    __tablename__ = "product_config_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LevelModel(Base):
    """One immutable level attached to a product configuration version."""

    __tablename__ = "levels"
    __table_args__ = (
        UniqueConstraint(
            "product_config_version_id",
            "experience_required",
            name="uq_levels_config_experience",
        ),
    )

    product_config_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_config_versions.id"),
        primary_key=True,
    )
    level_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    experience_required: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    level_up_message: Mapped[str | None] = mapped_column(Text)
    permissions_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ProductConfigActivationModel(Base):
    """Immutable activation command history."""

    __tablename__ = "product_config_activations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    activation_command_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    product_config_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_versions.id"), nullable=False
    )
    activated_by_member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    outcome_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    activated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ActiveProductConfigModel(Base):
    """Singleton pointer to the active immutable product configuration."""

    __tablename__ = "active_product_config"
    __table_args__ = (CheckConstraint("singleton_key", name="ck_active_product_config_singleton"),)

    singleton_key: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    product_config_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_versions.id"), nullable=False
    )
    activation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_activations.id"), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LevelBackfillRunModel(Base):
    """Immutable completed synchronous level backfill outcome."""

    __tablename__ = "level_backfill_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    activation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_config_activations.id"),
        unique=True,
        nullable=False,
    )
    product_config_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_config_versions.id"), nullable=False
    )
    processed_members: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_code: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
