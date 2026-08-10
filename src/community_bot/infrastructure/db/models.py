"""SQLAlchemy models for the member foundation."""

from __future__ import annotations

import datetime  # noqa: TC003 - SQLAlchemy resolves mapped annotations at runtime.
import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text, func
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
    credit_balance_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    experience_total_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
