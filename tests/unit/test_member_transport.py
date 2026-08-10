from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from community_bot.domain.members import StartOutcome
from community_bot.transport.telegram.member_foundation import (
    REFRESH_MENU_TEXT,
    present_start,
)


def test_main_menu_has_only_the_working_refresh_button() -> None:
    presentation = present_start(StartOutcome.MAIN_MENU)

    assert presentation.text == "Главное меню"
    assert isinstance(presentation.reply_markup, ReplyKeyboardMarkup)
    assert [[button.text for button in row] for row in presentation.reply_markup.keyboard] == [
        [REFRESH_MENU_TEXT]
    ]


def test_unavailable_routes_remove_keyboard() -> None:
    expected_text = {
        StartOutcome.REGISTRATION_REQUIRED: "Для регистрации потребуется приглашение.",
        StartOutcome.REGISTRATION_PENDING: "Заявка ожидает подтверждения.",
        StartOutcome.ACCOUNT_UNAVAILABLE: ("Аккаунт недоступен. Обратитесь к администратору."),
    }

    for outcome, text in expected_text.items():
        presentation = present_start(outcome)
        assert presentation.text == text
        assert isinstance(presentation.reply_markup, ReplyKeyboardRemove)
