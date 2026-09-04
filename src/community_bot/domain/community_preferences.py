"""Small, shared policies for community subscriptions and admission."""

from __future__ import annotations

from typing import Literal

NotificationCategory = Literal["tasks", "nomad"]
RegistrationMode = Literal["standard", "simplified"]


class PreferencesConflictError(ValueError):
    """The user is editing an outdated settings revision."""


def notification_category(notification_type: str) -> NotificationCategory | None:
    """Classify only the user-controlled directions, not security or wallet events."""
    if notification_type == "nomad.published":
        return "nomad"
    if notification_type.startswith(("task.", "assignment_", "review_reminder_")) or (
        notification_type in {"task_deadline_reminder", "moderation_case_resolved"}
    ):
        return "tasks"
    return None


def topic_message_url(chat_id: int, topic_id: int, message_id: int) -> str:
    """Build a private supergroup link from verified numeric Telegram identities."""
    if not str(chat_id).startswith("-100") or topic_id <= 0 or message_id <= 0:
        message = "Invalid Telegram topic identity"
        raise ValueError(message)
    return f"https://t.me/c/{str(chat_id)[4:]}/{topic_id}/{message_id}"
