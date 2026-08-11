# CB-15 — план реализации

## Цель

Довести PostgreSQL outbox до работающего MVP-контура уведомлений, сделать
`bot`/`worker` наблюдаемыми и развернуть весь runtime на собственном сервере с
проверяемым backup/restore.

## Изменение решения владельцем

После реализации Render-варианта, но до provisioning и final review, владелец
выбрал собственный сервер и поручил развернуть всё на нём. ADR-0009 заменяет
hosting/release/backup часть ADR-0008. External backup, R2, application object
storage и webhook по-прежнему исключены.

## Область изменений

- durable outbox/notifications, bounded retry, delivery и reminders;
- heartbeat/readiness, безопасные JSON-логи и optional Sentry;
- один Docker image для `migrate`, `worker` и `bot`;
- production Docker Compose с PostgreSQL 18 во внутренней сети;
- последовательный deployment `migration → worker readiness → bot readiness`;
- root-owned secrets, ограниченная ротация container logs;
- ежедневный локальный `pg_dump`, семь суток хранения и isolated restore drill;
- целевые unit/integration/smoke/ops tests и синхронизация документации.

## Вне области изменений

- Redis, Celery, Kubernetes, отдельный broker, web API и webhook;
- application object storage, R2 и любой external backup;
- новый reverse proxy или публичные порты;
- полная продуктовая регрессия и запуск когорты — CB-16.

## Реализация runtime

`compose.production.yaml` создаёт отдельные `postgres`, `migrate`, `worker` и
`bot`. PostgreSQL не публикует порт. Все application services используют один
`COMMUNITY_BOT_IMAGE`; секреты читаются из root-owned environment file вне Git.

Deployment script принимает только точный GHCR SHA-256 digest либо точный
локальный `sha256:IMAGE_ID` для bootstrap, проверяет
root-owned `0600` secret file, запускает PostgreSQL,
выполняет Alembic под advisory lock, запускает worker и ждёт readiness, затем
запускает bot и ждёт readiness. Текущая и предыдущая image identity сохраняются
для rollback без schema downgrade.

Backup timer ежедневно создаёт custom-format dump через временный файл и
атомарное переименование. Restore drill поднимает отдельную временную БД,
восстанавливает dump, проверяет `alembic_version` и ключевые таблицы и удаляет
только временную БД. Цели для логической аварии: `RPO <= 24h`, `RTO <= 4h`.
Полная потеря хоста явно не покрывается MVP.

## Шаги

1. Сохранить реализованный notification/worker/health контур.
2. Зафиксировать ADR-0009 и синхронизировать канонические документы.
3. Заменить Render assets на production Compose, deployment и backup scripts.
4. Проверить Compose contract, shell syntax, targeted tests, Ruff/ty/build и
   Docker smoke.
5. На собственном сервере создать изолированный deployment, не затрагивая
   существующие приложения, и применить immutable image identity.
6. Запустить migration, worker и bot; проверить container health и безопасные
   логи.
7. Выполнить реальный backup → isolated restore drill и зафиксировать RPO/RTO.
8. Обновить implementation report, Jira и передать полный snapshot на final
   review. Полную регрессию не запускать — она остаётся CB-16.

## Риски и меры

- внешний успех Telegram до DB commit: exactly-once заявляется только для DB;
- poison/stale lease: bounded attempts, terminal state и token fencing;
- privacy leak: allowlist payload и общий recursive scrubber;
- partial deploy: worker-first, readiness gates, previous image и forward-only
  migration;
- конфликт с другими сервисами: отдельный project/network/volume, без ports;
- потеря сервера: принятый MVP-риск, честно отделённый от логического backup;
- отсутствующий `BOT_TOKEN`: инфраструктура и БД могут быть готовы, но bot не
  запускается до передачи секрета безопасным способом.

## Критерии готовности

- все восемь Jira-критериев имеют воспроизводимое доказательство;
- production Compose запущен, PostgreSQL/worker/bot healthy;
- реальный local backup восстановлен в isolated DB, `RPO <= 24h`, `RTO <= 4h`;
- targeted tests без skip/deselect, Ruff, ty, migration, build и Docker smoke
  зелёные;
- секреты не попали в git, Jira или логи;
- `implementation-report.md` заполнен фактами;
- независимый `final-review.md` имеет `Status: approved`.
