# CB-108 — независимый review плана

## Проверенная область

`plan.md`, `plan-source-context.md`, `test-plan.md`, ADR-0018/0019,
`ops/release_contract.py`, backup/restore primitives, production Compose и
migration `0022`.

## Critical

1. Обычный `_create_backup` делает rename без `fsync` dump/directory и prune-ит
   старые dumps до restore proof. Cutover обязан использовать no-prune запись:
   temp → `fsync(dump)` → atomic rename → `fsync(backup_dir)` → isolated restore
   proof → migration. Нужен тест порядка и аварийной точки.

## Major

1. Реальный PostgreSQL gate должен пройти exact subprocess boundary
   `pg_dump → pg_restore → proof → Compose migrate → rerun`, а не только Alembic.
2. План должен явно покрыть `pending+0021`, `pending+0022` и
   `ready-target+0022`; missing/tampered proof при live `0022` обязан отклоняться.
3. Повторный review отдельно проверяет incompatible previous/rollback semantics,
   root-owned update exact activator и отсутствие generic framework.

Status: changes_requested

## Повторная проверка после исправлений

No-prune durable ordering, exact subprocess test, три rerun state, обязательный
proof при live `0022`, запрет incompatible rollback, root-owned exact activator
update и отсутствие generic framework закреплены в обновлённом плане.

Critical/Major: не обнаружены.

Ponytail: `Lean already. Ship.`

Status: approved
