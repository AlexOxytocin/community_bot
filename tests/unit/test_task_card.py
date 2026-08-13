"""Boundary tests for canonical Telegram task cards."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from community_bot.domain.catalog import TaskFormat
from community_bot.infrastructure.db.tasks import published_task_from_model
from community_bot.transport.telegram.task_card import published_task_card

if TYPE_CHECKING:
    from community_bot.application.tasks import PublishedTask


def test_task_card_deduplicates_payload_values_and_preserves_plain_url() -> None:
    """Repeated schema values appear once while materials stay actionable."""
    repeated = "Проверьте <первый экран> и опишите три улучшения."
    task = _task(
        input_payload={"context": repeated, "constraints": repeated, "items": [repeated]},
        materials={"url": "https://example.com/landing"},
    )

    text = published_task_card(task)

    assert text.count(repeated) == 1
    assert "https://example.com/landing" in text
    assert "Как выполнить:" in text
    assert "Результат:" in text
    assert "context" not in text
    assert "constraints" not in text


def test_task_card_stays_inside_telegram_text_limit() -> None:
    """Unusually long valid snapshots are clipped without losing metadata."""
    task = _task(
        description="A" * 2000,
        completion_criteria="B" * 2500,
        input_payload={"context": "C" * 3000},
        materials={"text": "D" * 2000},
    )

    text = published_task_card(task)

    assert len(text) <= 3800
    assert text.endswith("Формат: online")


def _task(**changes: object) -> PublishedTask:
    values: dict[str, object] = {
        "title": "Проверка лендинга",
        "author_display_name": "Автор",
        "description": "Проверка ясности оффера и пользовательского пути.",
        "performer_instructions": "Дайте честную и конкретную обратную связь.",
        "completion_criteria": "Список конкретных улучшений.",
        "input_payload": {"context": "Проверьте первый экран."},
        "public_input_keys": ("context", "materials", "constraints"),
        "materials": {"url": "https://example.com"},
        "credit_reward_per_performer": 2,
        "deadline_at": datetime.datetime(2026, 8, 14, 19, 7, tzinfo=datetime.UTC),
        "format": TaskFormat.ONLINE,
        "city": None,
    }
    values.update(changes)
    return cast("PublishedTask", SimpleNamespace(**values))


def test_task_card_preserves_each_public_value_and_prioritizes_url() -> None:
    """Long values are individually clipped instead of hiding later fields."""
    url = "https://example.com/landing"
    task = _task(
        input_payload={
            "context": "A" * 1000,
            "materials": "B" * 1000,
            "constraints": "C" * 1000,
            "internal_id": "must-not-leak",
        },
        materials={"text": "D" * 1000, "url": url},
    )

    text = published_task_card(task)

    assert url in text
    assert "must-not-leak" not in text
    assert "A" * 247 + "..." in text
    assert "B" * 247 + "..." in text
    assert "C" * 247 + "..." in text
    assert text.endswith("Формат: online")


def test_task_card_uses_public_keys_from_template_snapshot() -> None:
    """A future template field is visible without changing the presenter."""
    task = _task(
        input_payload={"audience": "Основатели небольших продуктов", "internal_id": "secret"},
        public_input_keys=("audience",),
        materials={"text": "Дополнительные материалы не требуются"},
    )

    text = published_task_card(task)

    assert "Основатели небольших продуктов" in text
    assert "secret" not in text


def test_task_card_omits_unsafe_uris_from_legacy_published_snapshot() -> None:
    """Historical task input cannot expose executable URI schemes."""
    task = _task(
        input_payload={
            "context": "Проверьте первый экран",
            "materials": "tg:resolve?domain=unsafe",
            "constraints": "javascript:alert(1)",
        },
        materials={"url": "file:C:/private.txt", "text": "https://example.com/safe"},
    )

    text = published_task_card(task)

    assert "Проверьте первый экран" in text
    assert "https://example.com/safe" in text
    assert "tg:resolve" not in text
    assert "javascript:" not in text
    assert "file:C:" not in text


def test_legacy_snapshot_uses_all_previously_validated_input_fields() -> None:
    """Tasks created before the allowlist snapshot retain arbitrary schema fields."""
    now = datetime.datetime(2026, 8, 13, 12, 0, tzinfo=datetime.UTC)
    model = SimpleNamespace(
        id=uuid4(),
        creator_id=uuid4(),
        created_by_admin_id=None,
        reviewer_admin_id=None,
        origin="member",
        author_display_name="Автор",
        template_id=uuid4(),
        template_version=1,
        title="Проверка аудитории",
        description="Проверьте соответствие оффера аудитории.",
        safety_snapshot_json={"performer_instructions": "Дайте конкретную обратную связь."},
        completion_criteria="Сформулирован вывод.",
        input_payload_json={"audience": "Основатели небольших продуктов"},
        materials_json={"text": "Дополнительные материалы не требуются"},
        credit_reward_per_performer=2,
        performer_slots=1,
        reserved_credit_total=2,
        minimum_level=1,
        format="online",
        city=None,
        deadline_at=now + datetime.timedelta(days=1),
        status="published",
        publish_command_id=uuid4(),
        created_at=now,
    )

    task = published_task_from_model(cast("Any", model))

    assert task.public_input_keys == ("audience",)
    assert "Основатели небольших продуктов" in published_task_card(task)
