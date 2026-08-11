# CB-15 — план целевого тестирования

## Контуры

- unit/transport/application tests для retry, reminders, privacy и entrypoints;
- PostgreSQL 18 integration для leases, concurrency, restart и health;
- Testcontainers fallback без `DATABASE_URL`;
- production Compose config, shell syntax, Docker build/entrypoint smoke;
- реальный server deploy и backup → isolated restore drill;
- полная продуктовая регрессия остаётся CB-16.

## Матрица

| № | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 | Materialize/replay/fault | Один persistent результат, rollback не оставляет полусостояние |
| 2 | Два materializer/delivery worker | `SKIP LOCKED` даёт непересекающиеся актуальные leases |
| 3 | Retry/permanent/limit | Bounded backoff либо terminal `failed` |
| 4 | Restart/stale token | Expired lease reclaim, stale completion отклонён |
| 5 | Deadline/review reminders | Dedup, terminal suppression и корректные recipients |
| 6 | IANA timezone/DST/deadline | `[09:00,21:00)` и точный deadline соблюдены |
| 7 | Privacy | Нет secret/free-form markers в persistence/logs/Sentry |
| 8 | Readiness | DB, migration и heartbeat дают точный healthy/unhealthy outcome |
| 9 | Migration cycle | `upgrade → downgrade previous → upgrade` сохраняет constraints |
| 10 | Production Compose | Четыре service, internal DB, без опубликованных ports/secrets |
| 11 | Deployment order | Только immutable digest/ID; migrate, worker healthy, затем bot healthy |
| 12 | Partial failure | Bot не стартует до worker readiness, previous identity сохранена |
| 13 | Docker image | Все четыре entrypoint доступны и используют один release |
| 14 | Local backup | Непустой custom dump, root `0600`, release/env восстановлены, retention rule |
| 15 | Restore drill | Отдельная БД восстановлена, revision/таблицы валидны, production не меняется |
| 16 | Existing server isolation | Другие containers/ports не изменены, новых inbound ports нет |
| 17 | Исключённая область | Нет R2/external backup/object storage/webhook реализации |

## Команды

- `uv run pytest -ra <targeted files>`;
- Testcontainers integration без `DATABASE_URL`;
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`;
- Alembic cycle на PostgreSQL 18, `uv build`, Docker build и entrypoint smoke;
- `docker compose -f compose.production.yaml config`;
- `bash -n ops/*.sh`, `git diff --check`, Markdown link и secret scans;
- на сервере: deploy script, оба `community-health`, backup script и restore
  drill с измеренными UTC timestamps.

Реальная Telegram отправка участникам не является частью targeted проверки.
Bot long polling запускается только при наличии настоящего `BOT_TOKEN`.
