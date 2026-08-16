from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from community_bot.domain.tasks import TaskStatus
from community_bot.transport.telegram.navigation import (
    _CREATED_STATUS_GROUPS,
    _created_status_group_matches,
    _encode_uuid,
    _insights_menu_markup,
    _parse_archive_cursor,
    _section_back_markup,
    _task_filter_markup,
    _task_list_title,
)

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup


def _buttons(markup: InlineKeyboardMarkup) -> list[tuple[str, str | None]]:
    inline_keyboard = markup.inline_keyboard
    return [(button.text, button.callback_data) for row in inline_keyboard for button in row]


def test_selected_nested_menu_controls_are_stable() -> None:
    assert TaskStatus.PARTIALLY_COMPLETED in _CREATED_STATUS_GROUPS["active"]
    assert _buttons(_task_filter_markup("created", selected="completed")) == [
        ("Активные", "nav:menu:created:active"),
        ("✓ Последние завершённые", "nav:menu:noop"),
        ("Архив", "nav:menu:created:archive"),
        ("Назад", "nav:menu:mine"),
    ]
    assert _buttons(_insights_menu_markup(selected="statistics")) == [
        ("Баланс", "nav:menu:balance"),
        ("✓ Статистика", "nav:menu:noop"),
        ("Лидерборд", "nav:menu:leaderboard"),
        ("Назад", "nav:menu:root"),
    ]
    assert _buttons(_section_back_markup("tasks")) == [("Назад", "nav:menu:tasks")]
    assert _task_list_title("created") == "Созданные мной"
    assert _task_list_title("taken") == "Взятые мной"


def test_partially_completed_cards_are_split_by_free_slots() -> None:
    task = SimpleNamespace(status=TaskStatus.PARTIALLY_COMPLETED, performer_slots=2)
    free_slot_card = SimpleNamespace(task=task, assignees=(SimpleNamespace(),))
    full_card = SimpleNamespace(task=task, assignees=(SimpleNamespace(), SimpleNamespace()))

    assert _created_status_group_matches(free_slot_card, "active")
    assert not _created_status_group_matches(free_slot_card, "completed")
    assert not _created_status_group_matches(free_slot_card, "archive")
    assert not _created_status_group_matches(full_card, "active")
    assert _created_status_group_matches(full_card, "completed")
    assert _created_status_group_matches(full_card, "archive")


def test_archive_cursor_parsing_rejects_unknown_list_kind() -> None:
    cursor_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
    encoded_id = _encode_uuid(cursor_id)
    value = f"nav:list:ca:f4240:{encoded_id}:00000000002a"
    list_kind, (cursor_at, parsed_id), generation = _parse_archive_cursor(value)

    assert list_kind == "created"
    assert cursor_at.timestamp() == 1
    assert parsed_id == cursor_id
    assert generation == 42
    assert len(value.encode()) <= 64
    with pytest.raises(ValueError, match="invalid"):
        _parse_archive_cursor(f"nav:list:xx:f4240:{encoded_id}:00000000002a")
