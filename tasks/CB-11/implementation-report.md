# CB-11 — отчёт о реализации

## Результат

Реализован единый атомарный цикл назначения: принятие свободного слота, отмена и
replacement, версии результата, полное/частичное подтверждение, отклонение и
приватное открытие спора. Добавлены migration `0007`, product config v2 с
настраиваемым лимитом `3`, корреляция ledger с task/assignment, outbox и receipts.
После первого финального ревью одним пакетом закрыты community settlement,
единый порядок `task gate → task row → assignment rows`, возврат свободных slots,
business replay terminal-решения и сохраняемый Telegram input→preview→callback.
После второго финального ревью применён эскалационный барьер: обе попытки
сохранены в `reviews/final/`, а одним финальным изменением добавлены exact
terminal command identity, новый durable draft для каждой result version,
непереиспользуемый paid slot и общий task-cancel/assignment aggregate gate.

## Матрица Jira

| Критерий | Реализация | Доказательство |
|---|---|---|
| Последний слот | task advisory gate и partial unique occupied-slot index | конкурентный last-slot и replacement PostgreSQL test |
| Недопустимый переход | `AssignmentStatus` и domain guards | unit/integration tests |
| Версии результата | append-only versions и отдельный durable draft/command для каждой | concurrent service v1/v2 и synthetic Telegram v1/v2/restart |
| Полная выплата один раз | correlated economy batch + receipt replay | full exchange, один reward row |
| Частичная выплата | `ceil(reward/2)` и refund остатка | таблица 2/3/4/5/11 в unit test |
| Спор замораживает расчёт | immutable `assignment_disputes`, состояние `disputed` | reject/dispute integration test |
| Гонка cancel/review | общий task gate для task cancel/accept/decision/deadline | принудительный accept↔task-cancel и replacement race |
| Полный обмен | publish → accept → persistent preview/callback → full | PostgreSQL и synthetic aiogram restart test |

## Выполненные проверки

- Ruff format/check и ty;
- targeted unit + PostgreSQL integration: `75 passed`, без skip/deselect;
- отдельный Testcontainers fallback без `DATABASE_URL`: `14 passed`;
- Alembic `0006→0007→0006→0007`;
- legacy config v1 hash и config v2 policy;
- build, entrypoints, diff/link/secret scan перед final review.

Прямой assignment-набор теперь включает 14 PostgreSQL tests: last-slot и
active-limit concurrency, self/low-level/paused/expired/duplicate reject без
receipt, concurrent replacement и result versions, community
full/partial/reject/no-show, paid multi-slot, reserve oracle, четыре fault
checkpoints, SQL append-only и synthetic Telegram accept→v1→v2→author full.

Полная регрессия намеренно остаётся отдельной задачей CB-16.
