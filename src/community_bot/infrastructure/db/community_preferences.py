"""Persist shared preferences, audited admission changes, and topic events."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from community_bot.domain.community_preferences import (
    NotificationCategory,
    PreferencesConflictError,
    RegistrationMode,
    notification_category,
    topic_message_url,
)
from community_bot.infrastructure.db.models import (
    AuditEventModel,
    CommunityRegistrationPolicyModel,
    MemberModel,
    MemberNotificationPreferencesModel,
    NotificationModel,
    OutboxEventModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def active_superadministrator(member: MemberModel | None) -> bool:
    """Match the domain role and explicit non-delegated superadministrator permission."""
    return bool(
        member
        and member.status == "active"
        and member.role == "administrator"
        and "superadministrator" in member.permissions_json
    )


async def subscription_allows(
    session: AsyncSession,
    member_id: uuid.UUID,
    notification_type: str,
    occurred_at: datetime.datetime,
) -> bool:
    """Recheck current subscriptions and do not resurrect events after resubscribing."""
    category = notification_category(notification_type)
    if category is None:
        return True
    preferences = await session.get(MemberNotificationPreferencesModel, member_id)
    if preferences is None:
        return False
    since = getattr(preferences, f"{category}_since")
    return bool(getattr(preferences, category) and (since is None or since <= occurred_at))


class CommunityPreferencesStore:
    """Narrow persistence adapter; identities always come from authenticated transports."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Use the runtime's shared session factory."""
        self.sessions = sessions

    async def member_for_telegram(self, telegram_user_id: int) -> MemberModel | None:
        """Resolve an immutable Telegram identity, including blocked accounts."""
        async with self.sessions() as session:
            return await session.scalar(
                select(MemberModel).where(MemberModel.telegram_user_id == telegram_user_id)
            )

    async def preferences(self, member_id: uuid.UUID) -> dict[str, object]:
        """Read active member settings without opt-in side effects."""
        async with self.sessions() as session:
            await self._require_member(session, member_id)
            row = await session.get(MemberNotificationPreferencesModel, member_id)
            return self._preferences(row)

    async def set_preference(
        self,
        member_id: uuid.UUID,
        category: NotificationCategory,
        enabled: bool,  # noqa: FBT001 - absolute setting shared by both adapters.
        expected_revision: int,
    ) -> dict[str, object]:
        """Serialize device/bot changes and record the start of each subscription."""
        if category not in {"tasks", "nomad"} or type(enabled) is not bool:
            message = "Invalid notification preference"
            raise ValueError(message)
        async with self.sessions() as session, session.begin():
            await self._require_member(session, member_id, lock=True)
            row = await session.get(MemberNotificationPreferencesModel, member_id)
            if row is None:
                row = MemberNotificationPreferencesModel(
                    member_id=member_id, tasks=False, nomad=False, revision=0
                )
                session.add(row)
            if row.revision != expected_revision:
                message = "Settings changed; reload them"
                raise PreferencesConflictError(message)
            if getattr(row, category) != enabled:
                setattr(row, category, enabled)
                setattr(row, f"{category}_since", datetime.datetime.now(datetime.UTC))
                row.revision += 1
            await session.flush()
            return self._preferences(row)

    async def policy(self, actor_id: uuid.UUID | None = None) -> dict[str, object]:
        """Read admission mode; optional actor enforces the moderator UI boundary."""
        async with self.sessions() as session:
            if actor_id is not None:
                await self._require_superadministrator(session, actor_id)
            row = await session.get(CommunityRegistrationPolicyModel, 1)
            if row is None:
                message = "Registration policy missing"
                raise RuntimeError(message)
            return {"mode": row.mode, "revision": row.revision}

    async def set_policy(
        self,
        actor_id: uuid.UUID,
        mode: RegistrationMode,
        expected_revision: int,
    ) -> dict[str, object]:
        """Change one policy revision and its audit record atomically."""
        if mode not in {"standard", "simplified"}:
            message = "Invalid registration mode"
            raise ValueError(message)
        async with self.sessions() as session, session.begin():
            await self._require_superadministrator(session, actor_id, lock=True)
            row = await session.get(CommunityRegistrationPolicyModel, 1, with_for_update=True)
            if row is None:
                message = "Registration policy missing"
                raise RuntimeError(message)
            if row.revision != expected_revision:
                message = "Registration policy changed"
                raise PreferencesConflictError(message)
            if row.mode != mode:
                before = {"mode": row.mode, "revision": row.revision}
                row.mode = mode
                row.revision += 1
                session.add(
                    AuditEventModel(
                        actor_member_id=actor_id,
                        action="registration_policy_changed",
                        entity_type="registration_policy",
                        entity_id="1",
                        before_json=before,
                        after_json={"mode": mode, "revision": row.revision},
                    )
                )
            return {"mode": row.mode, "revision": row.revision}

    async def publish_nomad(  # noqa: PLR0913 - explicit Telegram publication identity.
        self,
        *,
        author_id: int,
        chat_id: int,
        topic_id: int,
        message_id: int,
        published_at: datetime.datetime,
        album_id: str | None = None,
    ) -> bool:
        """Stage a single event per post or album after checking the current author role."""
        async with self.sessions() as session, session.begin():
            author = await session.scalar(
                select(MemberModel)
                .where(MemberModel.telegram_user_id == author_id)
                .with_for_update()
            )
            if not active_superadministrator(author):
                return False
            key = f"nomad:{chat_id}:{topic_id}:" + (
                f"album:{album_id}" if album_id else f"message:{message_id}"
            )
            event_id = uuid.uuid4()
            statement = (
                insert(OutboxEventModel)
                .values(
                    id=event_id,
                    event_type="nomad.published",
                    aggregate_type="nomad_post",
                    aggregate_id=event_id,
                    business_key=key,
                    status="pending",
                    attempt_count=0,
                    payload_json={
                        "message_url": topic_message_url(chat_id, topic_id, message_id),
                        "occurred_at": published_at.isoformat(),
                    },
                )
                .on_conflict_do_nothing(index_elements=[OutboxEventModel.business_key])
            )
            result = await session.execute(statement.returning(OutboxEventModel.id))
            return result.scalar_one_or_none() is not None

    async def allows_delivery(self, notification_id: uuid.UUID) -> bool:
        """Recheck eligibility immediately before an external send."""
        async with self.sessions() as session:
            row = await session.get(NotificationModel, notification_id)
            if row is None or row.status != "processing":
                return False
            member = await session.get(MemberModel, row.member_id)
            return bool(
                member
                and member.status == "active"
                and await subscription_allows(
                    session, row.member_id, row.notification_type, row.created_at
                )
            )

    @staticmethod
    def _preferences(row: MemberNotificationPreferencesModel | None) -> dict[str, object]:
        return {
            "tasks": row.tasks if row else False,
            "nomad": row.nomad if row else False,
            "revision": row.revision if row else 0,
        }

    @staticmethod
    async def _require_member(
        session: AsyncSession,
        member_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> MemberModel:
        member = await session.get(MemberModel, member_id, with_for_update=lock)
        if member is None or member.status != "active":
            message = "Active membership required"
            raise PermissionError(message)
        return member

    async def _require_superadministrator(
        self,
        session: AsyncSession,
        member_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> None:
        member = await self._require_member(session, member_id, lock=lock)
        if not active_superadministrator(member):
            message = "Superadministrator required"
            raise PermissionError(message)
