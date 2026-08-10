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

    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id"), primary_key=True
    )
    flow_type: Mapped[str] = mapped_column(Text, nullable=False)
    current_step: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TaskCategoryModel(Base):
    """Immutable catalog category with an administrative visibility switch."""

    __tablename__ = "task_categories"
    __table_args__ = (CheckConstraint("sort_order >= 0", name="ck_task_categories_sort_order"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
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
            "current_step IN ('input', 'deadline', 'format', 'materials', "
            "'slots', 'preview', 'published')",
            name="ck_task_creation_drafts_step",
        ),
        CheckConstraint("revision >= 0", name="ck_task_creation_drafts_revision"),
        CheckConstraint(
            "format IS NULL OR format IN ('online', 'offline')",
            name="ck_task_creation_drafts_format",
        ),
        CheckConstraint(
            "performer_slots IS NULL OR performer_slots BETWEEN 1 AND 10",
            name="ck_task_creation_drafts_slots",
        ),
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
    template_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_templates.id"), nullable=False
    )
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
        CheckConstraint("status IN ('published', 'cancelled')", name="ck_tasks_status"),
        CheckConstraint("credit_reward_per_performer > 0", name="ck_tasks_reward"),
        CheckConstraint("performer_slots BETWEEN 1 AND 10", name="ck_tasks_slots"),
        CheckConstraint("reserved_credit_total >= 0", name="ck_tasks_reserved_nonnegative"),
        CheckConstraint("minimum_level > 0", name="ck_tasks_minimum_level"),
        CheckConstraint("format IN ('online', 'offline')", name="ck_tasks_format"),
        CheckConstraint("deadline_at > published_at", name="ck_tasks_future_deadline"),
        CheckConstraint(
            "(origin = 'member' AND creator_id IS NOT NULL "
            "AND reserved_credit_total = credit_reward_per_performer * performer_slots) "
            "OR (origin = 'community' AND creator_id IS NULL AND reserved_credit_total = 0)",
            name="ck_tasks_origin_reserve",
        ),
        Index("ix_tasks_creator_created", "creator_id", "created_at", "id"),
        Index("ix_tasks_status_deadline", "status", "deadline_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_templates.id"), nullable=False
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("members.id")
    )
    author_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("task_categories.id"), nullable=False
    )
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


class AccountTransactionModel(Base):
    """Append-only source of truth for credits and experience."""

    __tablename__ = "account_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('starting_grant', 'task_reward_reserved', "
            "'task_reward_earned', 'task_reward_refunded', 'partial_task_reward', "
            "'community_task_reward', 'penalty', 'admin_adjustment', 'fraud_reversal')",
            name="ck_account_transactions_type",
        ),
        CheckConstraint(
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
