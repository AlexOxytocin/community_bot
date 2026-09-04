"""Serialized tag publications and one delivery per publication/member."""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from community_bot.domain.community_preferences import PUBLICATION_CATEGORIES, topic_message_url
from community_bot.infrastructure.db.models import (
    ActivityPublicationModel,
    MemberModel,
    MemberNotificationPreferencesModel,
    NotificationModel,
    OutboxEventModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from community_bot.domain.notifications import DeliveryWindow


def activity_publisher(member: MemberModel | None) -> bool:
    """Community administrators and superadministrators, never moderators or anonymous posts."""
    return bool(member and member.status == "active" and member.role == "administrator")


class ActivityPublicationStore:
    """Persist only tagged messages and revisions of previously tracked messages."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Use the runtime session factory."""
        self.sessions = sessions

    async def observe(  # noqa: PLR0913 - immutable Telegram update identity.
        self,
        *,
        update_id: int,
        author_id: int,
        chat_id: int,
        topic_id: int | None,
        message_id: int,
        occurred_at: datetime.datetime,
        categories: set[str],
        album_id: str | None = None,
    ) -> bool:
        """Merge album tags, serialize duplicate edits and stage only category changes."""
        categories &= PUBLICATION_CATEGORIES
        key = f"album:{album_id}" if album_id else f"message:{message_id}"
        url = topic_message_url(chat_id, topic_id, message_id)
        async with self.sessions() as session, session.begin():
            author = await session.scalar(
                select(MemberModel)
                .where(MemberModel.telegram_user_id == author_id)
                .with_for_update()
            )
            if not activity_publisher(author) or author is None:
                return False
            if categories:
                await session.execute(
                    insert(ActivityPublicationModel)
                    .values(
                        id=uuid.uuid4(),
                        chat_id=chat_id,
                        source_key=key,
                        author_id=author.id,
                        message_url=url,
                        parts_json={},
                        categories_json={},
                        revision=0,
                    )
                    .on_conflict_do_nothing(index_elements=["chat_id", "source_key"])
                )
            post = await session.scalar(
                select(ActivityPublicationModel)
                .where(
                    ActivityPublicationModel.chat_id == chat_id,
                    ActivityPublicationModel.source_key == key,
                )
                .with_for_update()
            )
            if post is None or post.author_id != author.id:
                return False
            parts = dict(post.parts_json)
            previous = parts.get(str(message_id), {})
            # Telegram may reset update IDs after a week without updates.
            observed_at = occurred_at.astimezone(datetime.UTC).isoformat()
            if previous and (previous["observed_at"], previous["update_id"]) >= (
                observed_at,
                update_id,
            ):
                return False
            # An unchanged tag retains its publication time, so edits do not become a backlog.
            old_tags = previous.get("categories", {})
            parts[str(message_id)] = {
                "update_id": update_id,
                "observed_at": observed_at,
                "url": url,
                "categories": {
                    category: old_tags.get(category, occurred_at.isoformat())
                    for category in sorted(categories)
                },
            }
            merged: dict[str, str] = {}
            for part in parts.values():
                for category, since in part["categories"].items():
                    merged[category] = min(merged.get(category, since), since)
            changed = merged != post.categories_json
            post.parts_json = parts
            post.categories_json = merged
            # Prefer a message that still carries a tag (including when an album caption moves).
            tagged = [part for part in parts.values() if part["categories"]]
            if tagged:
                post.message_url = tagged[0]["url"]
            if not changed:
                return False
            post.revision += 1
            if merged:
                session.add(
                    OutboxEventModel(
                        id=uuid.uuid4(),
                        event_type="activity.published",
                        aggregate_type="activity_post",
                        aggregate_id=post.id,
                        business_key=f"activity:{post.id}:{post.revision}",
                        status="pending",
                        attempt_count=0,
                        payload_json={},
                    )
                )
            return True


def matching_categories(
    preferences: MemberNotificationPreferencesModel | None, categories: dict[str, str]
) -> list[str]:
    """Match current consent against the first occurrence of each currently active tag."""
    if preferences is None:
        return []
    result = []
    for category in sorted(PUBLICATION_CATEGORIES & categories.keys()):
        since = getattr(preferences, f"{category}_since")
        if getattr(preferences, category) and (
            since is None or since <= datetime.datetime.fromisoformat(categories[category])
        ):
            result.append(category)
    return result


async def activity_is_current(session: AsyncSession, notification: NotificationModel) -> bool:
    """Recheck source tags, publisher and consent even after materialization."""
    try:
        post_id = uuid.UUID(str(notification.payload_json.get("aggregate_id")))
    except ValueError:
        return False
    post = await session.get(ActivityPublicationModel, post_id)
    if post is None or not activity_publisher(await session.get(MemberModel, post.author_id)):
        return False
    preferences = await session.get(MemberNotificationPreferencesModel, notification.member_id)
    eligible = matching_categories(preferences, post.categories_json)
    # Restrict to categories in this delivery: an unrelated later edit is not consent to resend.
    return bool(set(eligible) & set(notification.payload_json.get("categories", [])))


async def materialize_activity(
    session: AsyncSession,
    event: OutboxEventModel,
    *,
    now: datetime.datetime,
    window: DeliveryWindow,
) -> None:
    """Fan out once per member, including overlapping tags and album revisions."""
    post = await session.get(ActivityPublicationModel, event.aggregate_id, with_for_update=True)
    if post is None or not post.categories_json:
        return
    if not activity_publisher(await session.get(MemberModel, post.author_id)):
        return
    rows = (
        await session.execute(
            select(MemberModel, MemberNotificationPreferencesModel)
            .join(
                MemberNotificationPreferencesModel,
                MemberNotificationPreferencesModel.member_id == MemberModel.id,
            )
            .where(
                MemberModel.status == "active",
                or_(
                    *[
                        getattr(MemberNotificationPreferencesModel, category).is_(True)
                        for category in PUBLICATION_CATEGORIES
                    ]
                ),
            )
        )
    ).all()
    for member, preferences in rows:
        categories = matching_categories(preferences, post.categories_json)
        if not categories:
            continue
        payload = {
            "aggregate_id": str(post.id),
            "categories": categories,
            "message_url": post.message_url,
            "revision": post.revision,
        }
        scheduled = window.schedule(
            candidate=now + datetime.timedelta(seconds=3), timezone_name=member.timezone
        )
        statement = insert(NotificationModel).values(
            id=uuid.uuid4(),
            member_id=member.id,
            notification_type="activity.published",
            payload_json=payload,
            status="pending",
            scheduled_at=scheduled,
            next_attempt_at=scheduled,
            attempt_count=0,
            deduplication_key=f"activity:{post.id}:member:{member.id}",
        )
        # Unattempted payloads may follow edits. Sent/ambiguous attempts are never resurrected.
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[NotificationModel.deduplication_key],
                set_={
                    "payload_json": payload,
                    "status": "pending",
                    "last_error_code": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "next_attempt_at": scheduled,
                    "scheduled_at": scheduled,
                },
                where=(NotificationModel.attempt_count == 0)
                & (NotificationModel.status.in_(["pending", "failed"])),
            )
        )
