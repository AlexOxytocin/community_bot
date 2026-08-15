# ruff: noqa: RUF001
"""Canonical plain-text presentation of a published task."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from community_bot.domain.tasks import TaskError, validate_public_text_uris

if TYPE_CHECKING:
    import datetime

    from community_bot.application.tasks import PublishedTask, TaskPreview

_MAX_CARD_TEXT = 3800


class TaskCardError(ValueError):
    """Signal an incomplete internal preview projection."""


def published_task_card(task: PublishedTask) -> str:
    """Render the performer-facing immutable task snapshot."""
    title = f"ТЕСТ · {task.title}" if getattr(task, "test_run_id", None) is not None else task.title
    return _task_card(
        title=title,
        author=task.author_display_name,
        description=task.description,
        performer_instructions=task.performer_instructions,
        completion_criteria=task.completion_criteria,
        input_payload=task.input_payload,
        public_input_keys=task.public_input_keys,
        materials=task.materials,
        credit_reward=task.credit_reward_per_performer,
        deadline_at=task.deadline_at,
        task_format=task.format.value,
        city=task.city,
    )


def preview_task_card(preview: TaskPreview) -> str:
    """Render the exact future card plus author-only reserve information."""
    draft = preview.draft
    if (
        draft.input_payload is None
        or draft.materials is None
        or draft.deadline_at is None
        or draft.format is None
    ):
        raise TaskCardError
    card = _task_card(
        title=(
            f"ТЕСТ · {preview.template_name}"
            if draft.test_run_id is not None
            else preview.template_name
        ),
        author=preview.author_display_name,
        description=preview.template_description,
        performer_instructions=preview.performer_instructions,
        completion_criteria=preview.completion_criteria,
        input_payload=draft.input_payload,
        public_input_keys=preview.public_input_keys,
        materials=draft.materials,
        credit_reward=preview.credit_reward_per_performer,
        deadline_at=draft.deadline_at,
        task_format=draft.format.value,
        city=draft.city,
    )
    return f"{card}\nК резервированию: {preview.reserved_credit_total} кредита"


def _task_card(  # noqa: PLR0913
    *,
    title: str,
    author: str,
    description: str,
    performer_instructions: str,
    completion_criteria: str,
    input_payload: Mapping[str, object],
    public_input_keys: tuple[str, ...],
    materials: Mapping[str, object],
    credit_reward: int,
    deadline_at: datetime.datetime,
    task_format: str,
    city: str | None,
) -> str:
    seen: set[str] = set()
    material_values = _material_values(materials, seen)
    details = _public_input_values(input_payload, public_input_keys, seen)
    format_line = task_format if city is None else f"{task_format}, {city}"
    sections = [
        _clip(title, 120),
        f"Автор: {_clip(author, 160)}",
        f"Описание: {_clip(description, 300)}",
    ]
    if details:
        sections.append(f"Детали от автора:\n{chr(10).join(details)}")
    sections.append(f"Как выполнить: {_clip(performer_instructions, 350)}")
    sections.append(f"Результат: {_clip(completion_criteria, 350)}")
    if material_values and material_values != ("Дополнительные материалы не требуются",):
        sections.append(f"Материалы:\n{chr(10).join(material_values)}")
    footer = "\n".join(
        (
            f"Награда: {credit_reward} кредита",
            f"Срок: {deadline_at:%d.%m.%Y %H:%M} UTC",
            f"Формат: {_clip(format_line, 140)}",
        )
    )
    body_limit = _MAX_CARD_TEXT - len(footer) - 1
    return f"{_clip(chr(10).join(sections), body_limit)}\n{footer}"


def _public_input_values(
    payload: Mapping[str, object], public_input_keys: tuple[str, ...], seen: set[str]
) -> tuple[str, ...]:
    return _unique_values((payload[key] for key in public_input_keys if key in payload), seen, 250)


def _material_values(payload: Mapping[str, object], seen: set[str]) -> tuple[str, ...]:
    ordered = (payload[key] for key in ("url", "text") if key in payload)
    return _unique_values(ordered, seen, 700)


def _unique_values(
    values_source: Iterable[object], seen: set[str], item_limit: int
) -> tuple[str, ...]:
    values: list[str] = []
    for raw in _leaf_values(values_source):
        try:
            validate_public_text_uris(raw)
        except TaskError:
            continue
        value = " ".join(raw.split())
        identity = value.casefold()
        if value and identity not in seen:
            seen.add(identity)
            values.append(_clip(value, item_limit))
    return tuple(values)


def _leaf_values(values: Iterable[object]) -> Iterable[str]:
    for value in values:
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            yield from _leaf_values(value.values())
        elif isinstance(value, (list, tuple)):
            yield from _leaf_values(value)
        elif isinstance(value, bool):
            yield "Да" if value else "Нет"
        elif isinstance(value, (int, float)):
            yield str(value)


def _clip(value: str, limit: int) -> str:
    clean = value.strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3].rstrip()}..."
