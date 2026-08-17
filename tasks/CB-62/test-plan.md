# CB-62 — план проверки

## Статические gates

- `ruff format --check .`, `ruff check .`, `ty check`;
- `git diff --check` и secret-like scan;
- `uv build` или эквивалентная проверка package metadata/entrypoints;
- links/path check для удалённых документов и scripts.

## Структурные проверки

1. В runtime нет `transport/telegram`, bot/pilot/test-run entrypoints, FSM,
   reply keyboards и mutation callback routers.
2. `aiogram` разрешён только минимальному outbound notification adapter и его
   worker composition; domain/application не импортируют framework.
3. Существуют и импортируются domain/application, PostgreSQL UoW, ledger,
   audit, outbox и worker contracts.
4. Все существующие Alembic revisions присутствуют и migration cycle проходит.
5. Старые task artifacts и R1 operations отсутствуют в текущем дереве.
6. `git diff --exit-code 21a4b4c -- migrations/versions` проходит: historical
   revision content не изменён.

## Поведенческие проверки

- unit tests доменных правил;
- PostgreSQL integration tests экономики, заданий, назначений, модерации,
  регистрации и уведомлений, кроме удалённых pilot/presentation сценариев;
- notification worker отправляет allowlisted plain message и сохраняет retry/
  permanent failure semantics без keyboard/callback;
- health/migrate/bootstrap-admin/product-config/worker entrypoints проходят
  локальный smoke, удалённые entrypoints не устанавливаются.
- legacy active/completed test-run rows, assignments и pending outbox остаются
  скрыты от обычных actors; test notification recipients не расширяются;
- backup и isolated restore drill сохраняют revision и ledger reconciliation
  checks на transitional core Compose.

## Контроль удаления

- сравнить tracked paths до/после с `inventory.md`;
- сверить каждый удалённый mixed test с `test-migration-map.md` и новым target;
- проверить, что из `migrations/` не удалён ни один revision;
- проверить, что нет изменений правил ledger/audit/domain state machines, кроме
  механического удаления pilot/test-run hooks;
- полный pytest запускается по оставшемуся test tree с coverage не ниже 80%;
- live Telegram и production deployment не выполняются и не заявляются.
