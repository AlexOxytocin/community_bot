# CB-27 — отчёт о реализации

## Результат

Notification integration tests больше не зависят от часа запуска runner.
Production `DeliveryWindow`, worker и PostgreSQL adapter не изменялись.

## Причина

Тесты строили seed от `datetime.now(UTC)`, а затем ожидали немедленную доставку.
После `21:00 UTC` участник с timezone `UTC` корректно получал перенос на следующее
окно, из-за чего тестовые ожидания становились ложными.

## Исправление

- Test seed принимает явный aware timestamp.
- Сценарии немедленной доставки и reminders используют фиксированный полдень UTC.
- Outbox fixture в конкурентном сценарии получает согласованные `created_at` и
  `next_attempt_at`, поэтому claim также независим от реального wall clock.

## Проверки

- `uv run pytest -q --no-cov tests/integration/test_notifications.py` —
  `5 passed`, без skip/deselect.
- Ruff format/check — успешно.
- `uv run ty check tests/integration/test_notifications.py` — успешно.
- `git diff --check` — успешно.
- Полный PostgreSQL suite будет подтверждён GitHub CI после публикации PR.

## Область

Изменён один integration test file и артефакты Jira-задачи. Production-код,
схема, окно доставки и эксплуатационная конфигурация не менялись.
