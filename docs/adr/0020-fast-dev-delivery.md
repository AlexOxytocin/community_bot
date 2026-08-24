# ADR-0020 — Быстрый automatic delivery одного dev server

**Статус:** Принято

**Дата:** 2026-08-24

## Решение

Для canonical dev server обычный merge с неизменным Alembic head автоматически вызывает один существующий ограниченный server entrypoint с exact `main` SHA. GitHub workflow сериализован (`cancel-in-progress: false`), а entrypoint удерживает host lock и до mutation сверяет, что SHA ещё current `main`, target Alembic head совпадает с active manifest и live DB. Затем он использует native cached build, перезапускает runtime и доказывает public `/readyz` с этим SHA; при неуспехе одним действием возвращает exact image+OCI revision, захваченные у работающего web container.

`active.json` остаётся legacy manual-release state для backup/restore и не является runtime authority fast dev path; fast deploy не переписывает его ложной bundle identity.

PR обязан иметь один быстрый `Quality` path. DB/Alembic, browser и auth/ledger проверки включаются только по затронутым путям и не задерживают обычный merge. После merge не выполняются повторные тесты, provenance, release bundle или ручная activation. `/readyz` публикует non-secret exact `release`, а deploy измеряет время от push trigger, bounded-poll не дольше 120 секунд и rollback при timeout.

Изменение `migrations/` или `alembic.ini`, либо differing Alembic head, не имеет fast-path: до server mutation оно fail-closed направляется в прежний безопасный slow/manual path с backup и migration gate.

## Граница замены

Заменяются только противоречащие dev-flow части ADR-0018 (manual-first bundle/provenance и запрет automatic server action) и ADR-0019 (manual delivery после каждого merge и запрет automatic CD). Их contract для migration safety, exact identity, single previous compatible rollback и data protection сохраняется.

## Последствия

Нет нового CD framework, provider SDK, runner, dependency, registry flow или второй deployment path. Native cached build сначала измеряется; fallback prebuilt PR image допустим лишь если его время превышает 90 секунд.
