# CB-23 — отчёт о реализации

## Результат

Существующий supported-schema test `0009→0010` усилен representative domain fixture и exact oracle. Production migration и runtime code не менялись.

Fixture на отдельной временной PostgreSQL DB содержит:

- 2 active members с согласованными ledger caches;
- 4 immutable account transactions: два starting grants, reserve автора и paid reward исполнителя;
- 1 member task, 1 approved/ever-paid assignment и 1 immutable result version;
- 1 current karma vote и 2 immutable history revisions;
- 1 fraud-review moderation case и 1 immutable dispute resolution, связанный через `current_resolution_id`;
- прежние unpublished/published outbox rows.

## Доказательства Jira AC

После первого и повторного `upgrade head` test проверяет:

- exact table counts `(2,4,1,1,1,1,2,1,1)` для members, ledger, task, assignment, result, karma current/history, moderation case/resolution;
- exact UUID, business identities, revisions, values, deltas, statuses, payloads и timestamps всех полей, явно включённых в manifest;
- нулевые orphan counts для всех значимых FK joins, включая same-case `current_resolution_id`;
- outbox backfill `unpublished→pending`, `published→materialized` без потери identity/payload/timestamps;
- operational constraints/indexes и отказ трёх invalid outbox states;
- idempotent повтор `upgrade head` с полным повторным oracle;
- создание и гарантированное удаление отдельной временной DB в `finally`.

## Выполненные проверки

- `uv run ruff format --check tests/integration/test_pilot_readiness.py` — успешно;
- `uv run ruff check tests/integration/test_pilot_readiness.py` — успешно;
- `uv run ty check tests/integration/test_pilot_readiness.py` — успешно;
- targeted migration test — `1 passed`;
- `git diff --check` — успешно.

Полный `pytest` не запускался: authoritative regression CB-16 уже выполнен, а CB-23 исправляет найденный после неё дефект отдельной веткой.

## Интеграция

Ветка `task/CB-23` должна быть влита отдельным PR в `task/CB-16`. После этого CB-16 проходит единый повторный final review и родительский PR в `main` без дублирования полной локальной регрессии.
