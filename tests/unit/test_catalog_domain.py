from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from community_bot.domain.catalog import (
    CatalogCursor,
    CatalogError,
    PayloadValidationError,
    TaskFormat,
    TemplateDraft,
    validate_payload,
    validate_template_draft,
)

SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"summary": {"type": "string", "minLength": 2}},
    "required": ["summary"],
    "additionalProperties": False,
}
MANIFEST_PATH = Path(__file__).parents[2] / "migrations" / "data" / "task_catalog_v1.json"


def test_seed_manifest_has_stable_identity_schemas_and_safety_copy() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert [item["id"] for item in manifest["categories"]] == [
        f"10000000-0000-4000-8000-{index:012d}" for index in range(1, 9)
    ]
    assert [item["id"] for item in manifest["templates"]] == [
        f"20000000-0000-4000-8000-{index:012d}" for index in range(1, 9)
    ]
    assert len({item["code"] for item in manifest["categories"]}) == 8
    assert len({item["code"] for item in manifest["templates"]}) == 8
    for schema in manifest["schemas"].values():
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["required"]
    safety_copy = " ".join(
        f"{item['creator_instructions']} {item['performer_instructions']}"
        for item in manifest["templates"]
    ).lower()
    assert "не требуйте" in safety_copy
    assert "персональные данные" in safety_copy
    assert "не ставьте диагнозы" in safety_copy


def draft() -> TemplateDraft:
    return TemplateDraft(
        category_code="development",
        code="repository_review",
        name="Проверка репозитория",
        description="Структурированная проверка репозитория для нового пользователя.",
        creator_instructions="Передайте ссылку и опишите ожидаемый пользовательский путь.",
        performer_instructions="Пройдите путь и зафиксируйте конкретные наблюдения.",
        completion_criteria="Есть резюме, наблюдения и подтверждения результата.",
        input_schema=SCHEMA,
        result_schema=SCHEMA,
        credit_reward=2,
        estimated_minutes=30,
        format=TaskFormat.ONLINE,
        minimum_level=1,
        maximum_performers=1,
        moderation_required=False,
    )


def test_cursor_is_compact_and_rejects_tampering() -> None:
    cursor = CatalogCursor(10, "repository_review")
    assert CatalogCursor.decode(cursor.encode()) == cursor
    with pytest.raises(CatalogError):
        CatalogCursor.decode("10:Bad-Code")


def test_template_schema_and_payload_are_validated_before_use() -> None:
    assert validate_template_draft(draft()) == draft()
    assert validate_payload(SCHEMA, {"summary": "ok"}) == {"summary": "ok"}
    with pytest.raises(PayloadValidationError) as error:
        validate_payload(SCHEMA, {"unexpected": True})
    assert error.value.errors


def test_invalid_or_remote_schema_and_limits_are_rejected() -> None:
    with pytest.raises(CatalogError):
        validate_template_draft(replace(draft(), credit_reward=5))
    with pytest.raises(CatalogError):
        validate_template_draft(
            replace(
                draft(),
                input_schema={
                    "type": "object",
                    "properties": {"x": {"$ref": "https://example.com/schema"}},
                    "required": ["x"],
                    "additionalProperties": False,
                },
            )
        )
