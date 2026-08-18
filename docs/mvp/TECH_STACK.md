# Технологический стек

Канонические решения: [ADR-0005](../adr/0005-mvp-technology-stack.md) и [ADR-0016](../adr/0016-mini-app-only-runtime.md).

## Сохранённый backend

| Область | Выбор |
|---|---|
| Язык | Python 3.13, asyncio |
| Данные | PostgreSQL 18, SQLAlchemy 2 async, asyncpg |
| Миграции | Alembic |
| Конфигурация | Pydantic 2, pydantic-settings |
| Outbox notifications | aiogram 3.x только как outbound Bot API client |
| Проверки | Ruff, ty, pytest, Hypothesis, Testcontainers |
| Наблюдаемость | structlog, Sentry без PII |
| Зависимости | uv и `uv.lock` |

Backend остаётся модульным монолитом. Domain/application не зависят от web или Telegram SDK. PostgreSQL UoW объединяет state, ledger, audit, idempotency receipt и outbox.

## Целевой web-слой

| Область | Выбор |
|---|---|
| HTTPS API | FastAPI внутри существующего монолита |
| Контракт | versioned `/api/v1`, Pydantic, OpenAPI |
| Frontend | React, TypeScript, Vite |
| Telegram integration | тонкий `PlatformBridge` и server-side validation auth proof |
| Actor identity | internal `member_id`; права читаются из PostgreSQL |
| Mutation identity | namespaced operation ID + payload fingerprint + stored outcome |
| Rollout | server-side fail-closed gates |

FastAPI и статический frontend реализованы в CB-52—CB-55. CB-56 добавляет только
внутренний ASGI process и readiness-контракт; публичный HTTPS остаётся отдельным
owner-gated шагом.

## Runtime после очистки

Текущий Compose содержит PostgreSQL, одноразовый `migrate`, `worker` и внутренний
`web`. Все три application process используют один image; `web` доступен только
в internal network и не публикует host port. `/healthz` доказывает живой ASGI
process, а `/readyz` fail-closed проверяет PostgreSQL, exact Alembic head,
product config, release/revision/freshness worker heartbeat и failed outbox.
Публичного HTTPS/TLS edge и release workflow пока нет. Backup и restore drill
сохранены как защита данных до появления нового deployment-контура.

Не добавляются без отдельного решения: Redis, Celery, внешний брокер, Kubernetes, микросервисы, browser auth и LLM в критических доменных решениях.
