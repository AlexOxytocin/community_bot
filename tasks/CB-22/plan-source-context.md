# CB-22 — контекст исправления метрик пилота

## Источник дефекта

- Jira CB-22 и `tasks/CB-16/final-review.md`: дефекты найдены после завершения кода CB-16 в итоговой регрессии и поэтому исправляются отдельной веткой.
- Утверждённый контракт находится в `tasks/CB-16/plan.md`, `docs/operations/PILOT_RUNBOOK.md` и `docs/operations/PILOT_CHECKLIST.md`.
- Frozen base — commit `c8bc6d8`, содержащий реализацию и результаты единственной полной регрессии CB-16.

## Фактические разрывы

1. JSON отчёта использует сокращённые имена rate-полей, не совпадающие с утверждённым публичным контрактом.
2. PostgreSQL adapter считает karma activity по текущей строке `karma_votes`, а не по всем immutable revisions `karma_vote_history`.
3. Тесты не доказывают часть положительных и privacy-safe сценариев, заявленных в отчёте CB-16.

## Границы

- Меняются только DTO/расчёт метрик, read-only PostgreSQL adapter, целевые tests и связанные документы.
- Схема БД, Telegram flows, ledger semantics и формулы метрик не меняются.
- CB-23 отдельно закрывает representative migration oracle; в CB-22 он не дублируется.
- Полная регрессия не повторяется: запускаются только целевые tests, Ruff, ty и build.
