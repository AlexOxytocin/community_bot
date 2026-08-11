"""Shared presentation for the editable own-profile Telegram card."""

# ruff: noqa: RUF001 - Russian user-facing text is intentional.

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.domain.registration import ProfileField

if TYPE_CHECKING:
    from community_bot.application.registration import ProfileSnapshot

PROFILE_TEXT = "Моя карточка"


def own_profile_card(profile: ProfileSnapshot) -> str:
    """Render the complete owner-visible profile card."""
    return (
        f"{profile.display_name}\n"
        f"{profile.city or 'Город не указан'} · {profile.timezone}\n\n"
        f"{profile.short_bio or 'Описание не заполнено'}\n\n"
        f"Цель: {profile.current_goal or '—'}\n"
        f"Могу помочь: {', '.join(profile.help_categories) or '—'}\n"
        f"Навыки: {', '.join(profile.skill_tags) or '—'}\n"
        f"Доступность: {profile.availability or '—'}\n\n"
        f"Уровень: {profile.level.level_number} · {profile.level.display_name}\n"
        f"Опыт: {profile.experience_total}\n"
        f"Баланс: {profile.credit_balance} кредитов"
    )


def profile_edit_keyboard() -> InlineKeyboardMarkup:
    """Return one reachable edit action for every owner-editable field."""
    buttons = [
        InlineKeyboardButton(
            text=_profile_field_label(field),
            callback_data=f"profile:edit:{field.value}",
        )
        for field in ProfileField
    ]
    return InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons])


def _profile_field_label(field: ProfileField) -> str:
    labels = {
        ProfileField.DISPLAY_NAME: "Изменить имя",
        ProfileField.CITY: "Изменить город",
        ProfileField.TIMEZONE: "Изменить часовой пояс",
        ProfileField.SHORT_BIO: "Изменить описание",
        ProfileField.CURRENT_GOAL: "Изменить цель",
        ProfileField.HELP_CATEGORIES: "Изменить категории помощи",
        ProfileField.SKILL_TAGS: "Изменить навыки",
        ProfileField.AVAILABILITY: "Изменить доступность",
    }
    return labels[field]
