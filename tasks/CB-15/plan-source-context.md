# CB-15 — контекст и источники плана

## Jira и процесс

- CB-15 находится `В работе`, блокеры CB-13/CB-14 завершены, CB-15 блокирует
  общую регрессию CB-16.
- Восемь критериев требуют retry/dedup/concurrency/timezone/restart/health,
  реальный backup restore и отсутствие secret leaks.
- Полная регрессия выполняется в CB-16; здесь нужен один targeted gate по
  готовому коду.

## Принятые решения

- ADR-0005: PostgreSQL outbox, `FOR UPDATE SKIP LOCKED`, без Redis/Celery.
- ADR-0006: Bot API после commit; exactly-once только для DB-эффекта.
- ADR-0008: когорта пилота и Sentry privacy; его Render hosting заменён.
- ADR-0009: собственный Ubuntu/Docker host, private Compose network,
  PostgreSQL 18, один image, worker-first deployment, local seven-day backup и
  isolated restore drill.
- External backup, R2, application object storage и webhook исключены владельцем.

## Проверенные факты сервера

- Ubuntu 24.04, 4 CPU, около 8 ГБ RAM и достаточный свободный диск;
- Docker и Docker Compose активны;
- существующие containers используют собственные networks; Community Bot
  получает отдельные project/network/volume и не публикует ports;
- firewall не требует изменений, потому что Telegram использует long polling;
- deployment path ещё не существовал, поэтому коллизии с чужими файлами нет.

IP, SSH keys и секреты не сохраняются в git/Jira. Канонический deployment path —
`/opt/community-bot`, secrets path — `/opt/community-bot/shared/.env`.

## Ограничения

- Same-host backup закрывает логическую порчу, но не полную потерю сервера.
- Реальный bot/worker network runtime требует настоящий `BOT_TOKEN`; найденные
  чужие containers и их secrets не используются.
- Sentry остаётся необязательным.
