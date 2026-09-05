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
            "Что за активности у нас есть?\n\n"
            "🧪 Эксперименты с ИИ\n"
            "Мы создаём и тестируем новые форматы взаимодействия с искусственным "
            "интеллектом. За экспериментами можно наблюдать, участвовать в голосованиях, "
            "предлагать идеи и влиять на их развитие.\n\n"
            "🤖 Сейчас проходит «Цифровой кочевник»\n"
            "ИИ Alex Goodman получил собственную цифровую жизнь и цель — самостоятельно "
            "заработать на свой хостинг. Участники наблюдают за ним, предлагают идеи и "
            "выбирают его следующие шаги.\n\n"
            "💬 Живое общение\n"
            "Общаемся с людьми, которым интересны ИИ, технологии и собственные проекты. "
            "Делимся опытом, обсуждаем идеи и находим единомышленников.\n\n"
            "🫶 Ивенты взаимопомощи\n"
            "Участники создают задания, когда нужна помощь с проектом, продвижением, "
            "соцсетями, GitHub, консультацией или поиском контактов. Можно помогать другим, "
            "получать кредиты сообщества и использовать их для собственных заданий.\n\n"
            "₿ Криптотехнологии\n"
            "У нас есть отдельная ветка о практическом использовании криптовалют, блокчейна "
            "и других децентрализованных технологий. Обсуждаем инструменты, проекты, идеи "
            "и личный опыт участников.\n\n"
            "🤝 Офлайн-встречи\n"
            "Встречаемся вживую, знакомимся, обсуждаем проекты и технологии, обмениваемся "
            "опытом и просто хорошо проводим время вместе.\n\n"
            "💻 Онлайн-встречи\n"
            "Проводим созвоны, тематические обсуждения, разборы проектов, знакомства "
            "и просто общаемся на разные темы."
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
