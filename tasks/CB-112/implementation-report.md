# Отчёт реализации CB-112

## Выполнено

- PR CI сокращён до обязательного `Quality`; DB, browser и auth/ledger запускаются только по changed paths.
- Удалены verified merge tree, release bundle, provenance и post-merge повторная image publication.
- `/readyz` публикует exact non-secret `release`.
- Один forced-command Python entrypoint применяет cached native build, проверяет target/live Alembic head, health web-контейнера и public `/readyz`, затем при ошибке выполняет rollback.
- Durable rollback хранит ровно предыдущий успешный runtime Docker tag `community-bot-dev:previous`; legacy `active.json` не является state fast dev path.
- SLA использует timestamp current GitHub push event.

## Проверка

- Native cached build на canonical host: 5 секунд.
- `ruff format`, `ruff check`, `ty`, targeted unit tests: green. После первого live-run internal readiness заменён с неслушающего loopback-порта на Docker health status; публичная проверка exact SHA сохранена.
