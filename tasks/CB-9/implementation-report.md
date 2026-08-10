# CB-9 — отчёт о реализации

## Результат

Реализован минимальный каталог MVP: восемь категорий и восемь безопасных
пилотных шаблонов, level-aware просмотр с фильтрами и keyset-пагинацией,
неизменяемые версии, административные переключатели и проверка input/result по
JSON Schema Draft 2020-12. Публичная application-граница готова для CB-10 и не
создаёт экземпляры заданий внутри CB-9.

## Критерии Jira

| Критерий | Реализация | Доказательство |
|---|---|---|
| Видны только active и доступные шаблоны | Active member + актуальный LevelResolver; фильтр active category/template и minimum level | `test_seed_level_filters_and_payload_boundary`, `test_admin_toggles_versions_retry_and_history` |
| Пагинация без пропусков и дублей | Keyset `(category.sort_order, template.code)`; version UUID не входит в позицию | `test_keyset_does_not_repeat_code_when_version_changes`, Telegram smoke |
| Стоимость меняется новой версией | Catalog gate сериализует writers; старая строка остаётся неизменной, active partial unique | `test_admin_toggles_versions_retry_and_history`, `test_two_version_writers_are_serialized` |
| Неактивная категория скрывает новые публикации без удаления истории | Меняется только `is_active`; DB-trigger запрещает DELETE/изменение идентичности | `test_admin_toggles_versions_retry_and_history`, `test_database_immutability_and_migration_cycle` |
| Невалидные обязательные поля отклоняются до доменной команды | Draft/schema проверяются до catalog mutation; input валидируется в `for_creation` до границы CB-10 | `test_template_schema_and_payload_are_validated_before_use`, `test_invalid_or_remote_schema_and_limits_are_rejected`, `test_seed_level_filters_and_payload_boundary` |
| Seed и миграции воспроизводимы | `0005` загружает неизменяемый manifest с фиксированными UUID и валидирует обе схемы | `test_database_immutability_and_migration_cycle`, `test_seed_level_filters_and_payload_boundary` |

## Существенные гарантии

- все admin-команды используют порядок `update gate → exact receipt → catalog
  gate → actor/version locks → audit/receipt → one commit`;
- exact retry не создаёт вторую версию, audit или receipt;
- два разных writer получают последовательные номера без deadlock;
- старый template ID читается для result validation независимо от текущего
  `is_active`;
- категория логического `template.code` неизменяема между версиями: application-проверка
  даёт понятную ошибку, а PostgreSQL trigger блокирует обход прямым INSERT;
- удалённые `$ref`, незакрытые object-схемы, payload с неизвестными полями,
  награды вне `1..4` и длительность больше `120` минут отклоняются;
- Telegram callback пагинации укладывается в лимит 64 bytes.

## Проверки

Целевой контур готового кода:

```text
uv run pytest -q --no-cov tests/unit/test_catalog_domain.py \
  tests/integration/test_catalog.py \
  tests/integration/test_economy_extended.py \
  tests/integration/test_registration.py::test_registration_migration_cycle_returns_to_head \
  tests/architecture/test_import_boundaries.py tests/unit/test_settings.py
```

Результат: `37 passed`, без пропусков. В контур входят прямые доказательства
фиксированных seed identity/schema/safety copy; отказов member/moderator/paused admin без
receipt/audit; wrong-type input до downstream-вызова; result validation по исторической
версии; Telegram unauthorized/replay/invalid arguments без частичных эффектов; а также
запрета смены категории между версиями через service и PostgreSQL.

Дополнительно успешно выполнены
`uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check` и
`git diff --check`.

Полная регрессия продукта не выполняется в CB-9 и остаётся в CB-16 по принятому
процессу. Найденные во время реализации дефекты миграции и контракта исправлены
в этой ветке, отдельные баг-задачи не создавались.
