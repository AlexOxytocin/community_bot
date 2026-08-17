# CB-62 — переход к Mini App-only

## Цель

Удалить из текущего дерева полноценный Telegram chat UI и R1 pilot/release
обвязку, сохранив небольшое общее ядро для CB-51–CB-56. Не строить замену раньше
соответствующих задач и не поддерживать старый bot ради формальной parity.

Уровень процесса — 3: удаляется runtime surface и меняется принятая
архитектура. До реализации нужны approved plan review и принятие ADR-0016
владельцем.

## Планируемый результат

1. Принять `docs/adr/0016-mini-app-only-runtime.md`; отметить заменённые части
   ADR-0008/0009/0011/0012/0013/0014 без удаления исторических ADR.
2. Удалить `transport/telegram`, bot bootstrap/script и presentation tests.
3. Оставить worker/outbox, но убрать reply keyboard и callback mutations:
   outbound Telegram — только plain allowlisted notification.
4. Удалить pilot runtime и управляющий test-run CLI, но сохранить test-run
   data-isolation hooks, models, predicates и tests до отдельной безопасной
   data migration.
5. Удалить bot-specific deploy/release/smoke surfaces. PostgreSQL backup и
   restore drill адаптировать к transitional postgres/migrate/worker Compose;
   новую API/frontend topology создаёт CB-56.
6. Удалить старые task artifacts, сохранив только пакет CB-62. История остаётся
   в Git, статусы и критерии — в Jira.
7. Переписать README, architecture, stack, product/test docs и project rules так,
   чтобы они честно описывали переходное состояние: core готов, API/frontend
   ещё создаются CB-51–CB-55, production deployment временно отсутствует.
8. Перед удалением mixed Telegram tests перенести все core assertions по
   `test-migration-map.md`; зелёный coverage без invariant map недостаточен.
9. Очистить pyproject, lockfile, CI paths и package boundaries от удалённых
   entrypoints/исключений. `aiogram` остаётся только если его использует
   outbound notification adapter.

## Не входит

- ActorContext/operation receipts и migration — CB-51;
- FastAPI/auth/session/CSRF — CB-52;
- React shell и продуктовые экраны — CB-53–CB-55;
- новая production topology, TLS и rollout — CB-56;
- destructive database migration или удаление исторических данных;
- реальный deploy либо Telegram live action.

## Проверка

- allowlist файлов запрещает `transport/telegram`, bot/pilot/test-run
  entrypoints, R1 ops и старые task directories;
- AST/import test запрещает `aiogram` в domain/application и разрешает его
  только в outbound adapter/worker composition;
- поиск не находит reply keyboards, FSM, callback routers и старые console
  scripts в runtime;
- сохранённые domain/integration tests проходят после удаления presentation
  suite; coverage baseline пересчитывается по оставшемуся runtime;
- Alembic проходит upgrade/downgrade/upgrade без изменения старых revisions;
- `git diff --exit-code 21a4b4c -- migrations/versions` подтверждает byte-for-byte
  неизменность всех исторических revisions;
- Ruff format/lint, ty, package build и CI проходят;
- diff review отдельно подтверждает сохранность ledger, audit, outbox,
  domain/application правил и migration history.
- validator `cleanup-manifest.json` разрешает каждый base tracked path по exact
  rule, longest prefix либо `default=keep`; delete scope не выводится из prose.

## Риски

- Случайно удалить общую бизнес-логику: защищают inventory, path allowlist,
  domain/integration tests и независимый final review.
- Оставить скрытую зависимость worker от UI: notification adapter получает
  отдельный import-boundary test.
- Создать ложное впечатление готового Mini App: документация явно фиксирует
  переходный core-only этап и следующие Jira-задачи.
- Потерять эксплуатационный rollback: Git сохраняет старую реализацию; database
  downgrade в production не выполняется, migrations остаются неизменными.
- Раскрыть исторические test rows: управляющий CLI удаляется, но fail-closed
  query/outbox quarantine остаётся и покрывается отдельным PostgreSQL regression.

## Готовность

- ADR-0016 принят владельцем;
- plan review и final review имеют `Status: approved`;
- все проверки из `test-plan.md` зелёные;
- PR/CI слиты в `main`, CB-62 закрыта;
- после merge CB-51 начинается с компактного Mini App-only контракта.
