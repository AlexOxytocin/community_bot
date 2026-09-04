"""Compact Telegram activity panels; all controls use absolute, revisioned values."""

# ruff: noqa: RUF001 - Russian UI copy.

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from community_bot.domain.community_preferences import TASK_CATEGORIES

CATEGORY_COPY = {
    "online": ("Онлайн ивенты", "Анонсы онлайн-ивентов с тегом #online от администраторов."),
    "offline": ("Офлайн ивенты", "Анонсы ивентов вживую с тегом #offline от администраторов."),
    "nomad": ("Цифровой кочевник", "Новые публикации с тегом #nomad от администраторов."),
    "important": (
        "Важные обновления чата",
        "Важные объявления и изменения в сообществе с тегом #important от администраторов.",
    ),
    "tasks": ("Взаимопомощь", "Новые задания, изменения по твоим заданиям, напоминания и споры."),
    "crypto": ("Крипта", "Публикации администраторов с тегом #crypto."),
}


def navigation(label: str, page: str) -> InlineKeyboardButton:
    """Build a read-only navigation action."""
    return InlineKeyboardButton(text=label, callback_data=f"activities:{page}")


def activity_panel(
    preferences: dict[str, object], page: str = "all"
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Render either the overview or a compact explanation with explicit subscription controls."""
    if page in (*TASK_CATEGORIES, "tasks_group"):
        page = "all"  # Old keyboards no longer open granular task settings.
    if page == "all":
        buttons = []
        for category in ("important", "nomad", "tasks", "online", "offline", "crypto"):
            enabled = (
                any(bool(preferences.get(key)) for key in TASK_CATEGORIES)
                if category == "tasks"
                else bool(preferences.get(category))
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{'☑' if enabled else '☐'} {CATEGORY_COPY[category][0]}",
                        callback_data=(
                            f"subscription:{category}:{int(not enabled)}:{preferences['revision']}"
                        ),
                    )
                ]
            )
        return (
            (
                "Активности и подписки\n\n"
                "Ребят, чтобы сэкономить ресурс вашего внимания, сделал подписочную "
                "систему на контент нашего чата. Вы можете выбрать только то, что вас "
                "интересует, и получать в боте сразу точку входа — без необходимости "
                "следить за всем чатом, читать и искать."
            ),
            buttons,
        )
    if page == "help":
        text = (
            "Об активностях\n\n"
            "Важные обновления чата — объявления и изменения с тегом #important.\n\n"
            "Цифровой кочевник — публикации администраторов с тегом #nomad.\n\n"
            "Взаимопомощь — новые задания, изменения своих заданий, напоминания и споры. "
            "Включаются и выключаются одной галочкой. "
            "По спорам приходят только события, к которым у тебя есть доступ.\n\n"
            "Онлайн ивенты — анонсы администраторов с тегом #online.\n\n"
            "Офлайн ивенты — анонсы администраторов с тегом #offline.\n\n"
            "Крипта — публикации администраторов с тегом #crypto.\n\n"
            "После подписки приходят только новые события. Отписаться можно в любой момент."
        )
        return text, [[navigation("К подпискам", "all")]]
    categories = (page,)
    if any(category not in CATEGORY_COPY for category in categories):
        return activity_panel(preferences)
    lines = [CATEGORY_COPY[page][0]]
    buttons = []
    for category in categories:
        label, description = CATEGORY_COPY[category]
        enabled = bool(preferences.get(category))
        lines.append(f"{label}: {'включено' if enabled else 'выключено'}.\n{description}")
        text = "Отписаться" if enabled else "Подписаться"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=(
                        f"subscription:{category}:{int(not enabled)}:{preferences['revision']}"
                    ),
                )
            ]
        )
    buttons.append([navigation("Назад к активностям", "all")])
    return "\n\n".join(lines), buttons
