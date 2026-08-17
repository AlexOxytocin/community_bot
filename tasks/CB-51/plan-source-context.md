# CB-51 — исходный контекст

## Каноническое основание

- Ветка создана от `main@5d039116840069f85e73df8d06702d69355aa365`.
- Jira CB-51: сжать backend и схему с полным переносом данных и поведения.
- ADR-0017 принят владельцем и merged через PR #62.
- `tasks/CB-64/parity-map.json`: 43 legacy tables, 26 capability packages и
  11 constraint groups; независимый review имеет `Status: approved`.

## Baseline

- production Python: 58 файлов / 20 029 строк;
- tests: 49 файлов / 14 268 строк / 297 test functions;
- 43 SQLAlchemy tables / 20 Alembic revisions / 3 540 migration LOC;
- 10 direct runtime dependencies;
- runtime frontend отсутствует.

## Основные места стоимости

- `infrastructure/db/database.py`: 1 449 строк, один UoW с 144 методами;
- `application/tasks.py`: 2 087 строк, TaskService 1 158 строк;
- `application/assignments.py`: AssignmentService 837 строк;
- `infrastructure/db/moderation.py`: 1 358 строк;
- `infrastructure/outbox/postgres.py`: 618 строк;
- один бизнес-переход повторяется в command/service/protocol/UoW/adapter/model
  и нескольких близких тестах.

## Неприкосновенная область

Сохраняются все capability из parity map: registration/members, catalog и
templates, durable drafts, member/group/community tasks, полный assignment и
settlement lifecycle, credits/experience/levels, karma/reliability/leaderboard,
config versions, disputes/appeals/sanctions/risk/interaction alerts,
notifications/reminders/finalizers, audit и exact replay.

В CB-51 удаляется только дублирующая backend-реализация после passing parity
oracle. Старый Telegram chat transport/FSM остаётся неизменённым dormant кодом
до passing `MINI_APP_REACHABILITY` в CB-57. Технические test-run данные не
импортируются только вместе со всем transitive synthetic-effect closure и
проверяемым archive manifest.

## Data safety

Исторические production deployments не доказывают пустую БД. Source DB нельзя
изменять. Перед cutover обязательны read-only inventory, backup, isolated
restore, отдельная compact DB, полный importer и checksum/state reconciliation.
Source защищается отдельной read-only ролью; до/после сравниваются database
identity, Alembic head, counts и logical checksums, а не физические bytes.
После первой реальной mutation legacy DB становится только архивом.
