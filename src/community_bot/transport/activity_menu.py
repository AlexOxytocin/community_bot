"""Compact Telegram activity panels; all controls use absolute, revisioned values."""

# ruff: noqa: RUF001 - Russian UI copy.

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

CATEGORY_COPY = {
    "online": ("Онлайн-встречи", "Анонсы онлайн-встреч с тегом #online от администраторов."),
    "offline": ("Офлайн-встречи", "Анонсы встреч вживую с тегом #offline от администраторов."),
    "nomad": ("Цифровой кочевник", "Новые публикации с тегом #nomad от администраторов."),
    "important": (
        "Важные обновления чата",
        "Важные объявления и изменения в сообществе с тегом #important от администраторов.",
    ),
    "tasks": ("Новые задания", "Новые задания участников и комьюнити."),
    "task_updates": (
        "Мои задания",
        "Исполнители, результаты и изменения заданий, в которых ты участвуешь.",
    ),
    "task_reminders": ("Напоминания", "Сроки выполнения и проверки твоих заданий."),
    "disputes": (
        "Споры",
        "Открытие и решения по твоим спорам. Для модераторов — события в рамках их доступа.",
    ),
}
TASK_CATEGORIES = ("tasks", "task_updates", "task_reminders", "disputes")


def navigation(label: str, page: str) -> InlineKeyboardButton:
    """Build a read-only navigation action."""
    return InlineKeyboardButton(text=label, callback_data=f"activities:{page}")


def activity_panel(
    preferences: dict[str, object], page: str = "all"
) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Render either the overview or a compact explanation with explicit subscription controls."""
    if page == "all":
        buttons = []
        for category in ("online", "offline", "nomad", "important", "tasks_group"):
            if category == "tasks_group":
                count = sum(bool(preferences.get(key)) for key in TASK_CATEGORIES)
                label = f"Задания · {count} из {len(TASK_CATEGORIES)}"
            else:
                label = f"{'☑' if preferences.get(category) else '☐'} {CATEGORY_COPY[category][0]}"
            buttons.append([navigation(label, category)])
        buttons.append([navigation("Что входит в активности?", "help")])
        return (
            (
                "Активности и подписки\n\nВыбери, что получать в боте. "
                "☑ — включено, ☐ — выключено. Настройки общие с приложением."
            ),
            buttons,
        )
    if page == "help":
        text = (
            "Об активностях\n\n"
            "Онлайн- и офлайн-встречи, Цифровой кочевник — ссылки на публикации "
            "администраторов с тегами #online, #offline и #nomad.\n\n"
            "Важные обновления чата — объявления и изменения с тегом #important.\n\n"
            "Задания — новые предложения, изменения своих заданий, напоминания и споры. "
            "Каждый тип можно настроить отдельно. "
            "По спорам приходят только события, к которым у тебя есть доступ.\n\n"
            "После подписки приходят только новые события. Отписаться можно в любой момент."
        )
        return text, [[navigation("К подпискам", "all")]]
    categories = TASK_CATEGORIES if page == "tasks_group" else (page,)
    if any(category not in CATEGORY_COPY for category in categories):
        return activity_panel(preferences)
    lines = ["Задания" if page == "tasks_group" else CATEGORY_COPY[page][0]]
    buttons = []
    for category in categories:
        label, description = CATEGORY_COPY[category]
        enabled = bool(preferences.get(category))
        lines.append(f"{label}: {'включено' if enabled else 'выключено'}.\n{description}")
        text = (
            f"{'Отключить' if enabled else 'Включить'}: {label}"
            if page == "tasks_group"
            else ("Отписаться" if enabled else "Подписаться")
        )
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
