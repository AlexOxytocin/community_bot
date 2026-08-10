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
