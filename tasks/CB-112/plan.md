# План CB-112

## Цель

Обычный merge без изменения Alembic автоматически доставляет exact `main` SHA на canonical dev server и подтверждает `/readyz` за 120 секунд или быстрее.

## Минимальное изменение

1. Заменить PR CI одним обязательным `Quality` path: format, lint, typecheck, короткие unit и один целевой smoke. Отдельные PostgreSQL/Alembic, browser и auth/ledger jobs вычисляют затронутые пути стандартным `git diff` и запускаются параллельно только при необходимости.
2. Удалить `verified-merge-tree`, image-contract, post-merge publication, provenance и release bundle. На `push main` оставить один serialized deploy job (`cancel-in-progress: false`): он передаёт full SHA существующему ограниченному server entrypoint, который под host lock сверяет current `main`, делает cached native build/restart и проверяет `/readyz` с exact `RELEASE`.
3. Добавить к публичному non-secret JSON `/readyz` ровно поле `release` из validated server settings и unit oracle exact SHA; это делает assertion внешне проверяемым, а не выводом из CI.
4. Быстрый путь разрешён только при unchanged Alembic head: до host mutation entrypoint сверяет target head, active manifest и live DB head, затем пропускает backup/migration. Изменённые `migrations/`/`alembic.ini` или differing head fail-closed уходят в отдельную slow/manual procedure.
5. Сохранить текущую previous compatible version как единственный rollback; при ошибке entrypoint возвращает её и требует green `/readyz`. Timer начинается с GitHub push event; entrypoint bounded-poll до общего лимита 120 секунд, затем rollback и non-zero result.
6. Сузить workflow/policy assertions, которые сейчас требуют immutable bundle/manual activation: `agents/config.yaml`, `agents/workflow.yaml`, architecture/ops tests. Они сохраняют serialization, migration owner gate, public smoke и one rollback, но описывают fast dev flow.
7. Внести короткий ADR, заменяющий только manual-first/provenance/dev-delivery части ADR-0018 и ADR-0019; остальная защита данных сохраняется.

## Проверки и границы

- До выбора fallback замерить native cached build на server. Если он не превышает 90 секунд, image fallback не добавляется; если превышает — добавить только prebuilt PR image.
- До PR сверить branch protection и оставить required ровно `Quality`; changed-path matrix закрепить workflow test, чтобы optional DB/browser/auth-ledger jobs не стали скрытым merge gate.
- Локально: workflow syntax, changed-path matrix, `/readyz.release` unit oracle, targeted policy/ops tests, format/lint/typecheck и target smoke.
- После merge: один реальный ordinary deploy и два idempotent redeploy exact SHA без мусорных commits, если Jira честно фиксирует их как эквивалентные измерения одного post-merge path; для каждого — trigger timestamp, elapsed, exact `release`, green `/readyz` и rollback result при failure.
- Не меняются product/runtime semantics, зависимости, providers, self-hosted runners и второй deploy route.

## Риски

GitHub secret/forced command может отсутствовать. Тогда будет зафиксирован ровно минимальный credential или forced-command contract; без него автоматическое требование не имитируется и не заменяется платформой.
