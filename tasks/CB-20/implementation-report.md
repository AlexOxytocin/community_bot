# CB-20 — отчёт реализации

## Результат

Добавлена отдельная CLI-команда `community-bootstrap-admin`. Она под единым PostgreSQL
transaction-scoped advisory lock создаёт первый deterministic active administrator и связанное
append-only audit-событие одним commit. Точный повтор подтверждается только сохранённым bootstrap
provenance; любые чужие состояния отклоняются без изменений.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| CLI с обязательным Telegram ID | Пройден | Entry point в `pyproject.toml`, unit smoke и реальный CLI-вызов в integration E2E |
| Только при отсутствии admin, retry/conflict | Пройден | Последовательные и конкурентные same/different identity тесты |
| Audit и безопасная причина | Пройден | Allowlist `initial_install|clean_recovery`, exact safe audit schema, privacy assertions |
| Invite и регистрация через Dispatcher | Пройден | Один тест вызывает CLI, production `_dispatcher`, `/invite_create` и `/start` |
| Точный runbook | Пройден | First install, clean recovery, exit codes и запрет ручного SQL описаны в `PILOT_RUNBOOK.md` |
| PostgreSQL с пустой схемы | Пройден | Изолированная migrated PostgreSQL DB из стандартной fixture |
| Целевые quality gates | Пройден | 13 targeted tests, Ruff, ty, build, CLI smoke и diff-check успешны |

## Проверочная матрица

- чистая БД: один member и один bootstrap audit;
- точный повтор: `already_applied` без новых записей;
- existing target/active admin без provenance и mixed state со вторым active admin: conflict без
  изменений;
- fault после audit flush: полный rollback, следующий retry становится winner;
- concurrent same ID: `created` + `already_applied`, одна пара записей;
- concurrent different IDs: один winner + один conflict, без дедлока;
- ID вне positive PostgreSQL BIGINT и reason вне allowlist отклоняются;
- bootstrap member имеет полный admin permission set, UTC, approved timestamp, нулевые caches и
  не получает starting grant;
- invitation хранится только как hash, новый участник создаётся pending, update receipts сохранены;
- audit не содержит Telegram ID, username, token, CLI argv или свободный payload; ошибки CLI не
  отражают raw invalid input и неожиданные DB exception parameters.

## Выполненные команды

- `uv run pytest -ra tests/unit/test_initial_admin.py tests/integration/test_initial_admin.py --no-cov` —
  `13 passed`, без skip/deselect;
- `uv run ruff format --check .` — `292 files already formatted`;
- `uv run ruff check .` — успешно;
- `uv run ty check` — успешно;
- `uv build` — sdist и wheel собраны;
- `uv run community-bootstrap-admin --help` — exit `0`;
- `git diff --check` — успешно.

Полная регрессия намеренно не запускалась: по процессу она выполняется один раз в CB-16 после
слияния CB-20 и CB-21.

## Отклонения и остаточные риски

Отклонений от одобренного плана нет. Оператор с production DB credentials остаётся доверенной
стороной; доступ к root-owned `.env` регулируется существующим operational contract.
