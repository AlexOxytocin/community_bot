# CB-15 — архитектурное решение реализации

## Статус

Реализация применяет ADR-0005, ADR-0006 и принятый ADR-0009. ADR-0009 заменяет
hosting/release/backup часть ADR-0008, сохраняя privacy и продуктовые границы.

## Уведомления

Доменная команда и privacy-minimal outbox фиксируются одним commit. Materializer
и delivery worker используют короткий claim через `FOR UPDATE SKIP LOCKED`,
fenced lease, bounded retry и terminal outcome. Bot API вызывается после commit;
`notifications.deduplication_key` защищает persistent эффект от повтора.

Scheduler хранит UTC, вычисляет participant-local окно `[09:00,21:00)` через
IANA timezone и не переносит reminder позже доменного deadline. Payload строится
по allowlist; scrubber удаляет secrets, Telegram payload, comments, evidence и
materials из логов и Sentry.

## Self-hosted runtime

Один Docker image содержит Alembic, `community-worker`, `community-bot` и
`community-health`. Production Compose создаёт четыре service и отдельную
internal network. PostgreSQL 18 использует persistent volume и не имеет
опубликованного порта.

Deployment order фиксирован: database healthy → migration gate → worker
readiness → bot readiness. Один release использует одну image identity. Bot не
запускает migration; schema downgrade при rollback запрещён.

Секреты находятся вне deployment tree в обычном root-owned `.env` с mode `0600`;
deployment/backup/restore fail closed при ином owner/mode или symlink. Docker
logging имеет bounded size/file count. Существующий reverse proxy и firewall не
изменяются.

## Восстановление

Root-only systemd timer создаёт ежедневный custom-format `pg_dump` и хранит семь
суток. Drill восстанавливает выбранный dump в отдельную временную БД, проверяет
Alembic revision и ключевые таблицы, затем удаляет только drill DB. Рабочая БД
не переключается. Same-host backup покрывает логическую порчу, но не потерю
хоста; внешний storage исключён владельцем из MVP.
