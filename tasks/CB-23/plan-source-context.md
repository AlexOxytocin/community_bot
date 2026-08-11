# CB-23 — контекст representative migration oracle

## Источник дефекта

- Jira CB-23 и `tasks/CB-16/final-review.md`: supported-schema test начинался с revision `0009`, но сохранял только outbox rows.
- `tasks/CB-16/plan.md` и `test-plan.md` требуют representative domain chain: members, immutable ledger, task/assignment, karma и moderation history.
- Outbox backfill и operational constraints уже проверяются существующим тестом; их нельзя ослаблять.

## Границы

- Меняется только migration fixture/oracle и связанные артефакты задачи.
- Production migration `0010`, runtime code и схема не меняются.
- Fixture создаётся прямым SQL строго на схеме `0009`, чтобы доказательство не зависело от текущих ORM-моделей revision `0010`.
- Каждая проверка использует отдельную временную PostgreSQL DB и удаляет её в `finally`.
- Полная регрессия CB-16 не повторяется; запускается один migration test и статические проверки.
