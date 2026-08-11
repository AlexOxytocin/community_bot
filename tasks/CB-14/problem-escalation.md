# CB-14 — эскалация plan review

## Причина

Два последовательных plan review не одобрили release/backup contract. Остальная
область и семь Jira AC признаны корректными; расширять задачу не требуется.

## Попытки

1. `reviews/plan/attempt-01.md`: не были выбраны Pro plan, исполнимый backup и
   единый image identity.
2. `reviews/plan/attempt-02.md`: backup закрыт, но migration one-off опирался на
   старый base artifact, а partial deploy не имел совместимого rollback.

## Причина повторения

План смешал логическую последовательность release с фактической моделью Render:
one-off job наследует artifact base service, поэтому не может магически получить
ещё не развёрнутый digest. Кроме того, миграция рассматривалась как одноразовый
барьер без периода, когда старый и новый процессы работают с новой схемой.

## Единое исправление

- Новый digest назначается image-backed `worker`; его единственный pre-deploy
  command выполняет `alembic upgrade head` из нового image до switch worker.
- Миграции release только expand/backward-compatible. Старый digest обязан
  проходить smoke на новой схеме; destructive contract migration откладывается
  до отдельного следующего release после rollback window.
- PostgreSQL advisory lock и Alembic version table сериализуют повторный
  migration gate; retry на head не создаёт эффектов.
- При migration/worker failure оба старых процесса продолжают работу на
  расширенной совместимой схеме. При bot failure новый worker либо ждёт retry,
  либо откатывается на старый digest; schema downgrade не выполняется.
- GHCR хранит предыдущий digest минимум 30 дней и до успешного завершения
  следующего release.
- Backup-role получает только CONNECT, USAGE и SELECT для всех таблиц/sequence
  и default privileges; DML/DDL запрещены, чего достаточно для `pg_dump`.

## Контрольный барьер

Следующий review является эскалационным контрольным прогоном всего пакета. Если
он снова не одобрен, работа останавливается для решения владельца.
