"""Small, shared policies for community subscriptions and admission."""

from __future__ import annotations

from typing import Literal

NotificationCategory = Literal[
    "online",
    "offline",
    "nomad",
    "important",
    "crypto",
    "tasks",
    "task_updates",
    "task_reminders",
    "disputes",
]
NOTIFICATION_CATEGORIES: tuple[NotificationCategory, ...] = (
    "online",
    "offline",
    "nomad",
    "important",
    "crypto",
    "tasks",
    "task_updates",
    "task_reminders",
    "disputes",
)
PUBLICATION_CATEGORIES = frozenset({"online", "offline", "nomad", "important", "crypto"})
TASK_CATEGORIES: tuple[NotificationCategory, ...] = (
    "tasks",
    "task_updates",
    "task_reminders",
    "disputes",
)
RegistrationMode = Literal["standard", "simplified"]


class PreferencesConflictError(ValueError):
    """The user is editing an outdated settings revision."""


def notification_category(notification_type: str) -> NotificationCategory | None:
    """Classify only the user-controlled directions, not security or wallet events."""
    if notification_type == "nomad.published":
        return "nomad"
    if notification_type in {
        "assignment_disputed",
        "assignment_rejection_pending_dispute",
        "moderation_case_resolved",
    }:
        return "disputes"
    if (
        notification_type.startswith("review_reminder_")
        or notification_type == "task_deadline_reminder"
    ):
        return "task_reminders"
    if notification_type == "task.published":
        return "tasks"
    if notification_type.startswith(("task.", "assignment_")):
        return "task_updates"
    return None


def topic_message_url(chat_id: int, topic_id: int | None, message_id: int) -> str:
    """Build a private supergroup link from verified numeric Telegram identities."""
    if (
        not str(chat_id).startswith("-100")
        or (topic_id is not None and topic_id <= 0)
        or message_id <= 0
    ):
        message = "Invalid Telegram topic identity"
        raise ValueError(message)
    topic = f"{topic_id}/" if topic_id is not None else ""
    return f"https://t.me/c/{str(chat_id)[4:]}/{topic}{message_id}"
