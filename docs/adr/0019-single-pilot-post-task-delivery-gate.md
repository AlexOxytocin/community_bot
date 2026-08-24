# ADR-0019 — Single-pilot post-task delivery gate

**Статус:** Заменено ADR-0021; release safety применяется только к явной release-задаче

**Дата:** 2026-08-18

**Принято владельцем:** 2026-08-18

## Контекст

ADR-0018 публикует reviewed immutable image+host-package tuple, но намеренно не
даёт CI production authority. Без отдельного delivery rule merged deployable
задача может получить `Done`, оставаясь только локально/в CI проверенной. Один
pilot не оправдывает automatic CD или SSH framework, но требует проверяемой
цепочки от merge до публичного URL.

Первый rollout дополнительно меняет project/data boundary: old Compose project
`community-bot` с DB head `0020` несовместим по identity с immutable project
`community-mini-app-core`. Прямая initial activation не должна видеть пустую или
чужую DB. Существующий HTTPS origin уже содержит landing page на `/`.

## Решение

1. После merge в `main` и green main CI каждая продуктовая задача требует
   delivery независимо от формы diff. Любая другая задача с runtime diff также
   требует delivery. Только process/docs-only задача без runtime diff получает
   явный skip.
2. Delivery использует новый exact immutable release artifact проверенного
   merge и manual-first production activation ADR-0018 на одном pilot. Новая
   CD-платформа не создаётся.
3. После activation обязателен public smoke соответствующего URL и privacy-safe
   Jira evidence, связывающий merge/run/artifact/manifest/image/migration и
   результат smoke.
4. Migration-changing release всегда требует отдельного owner gate до server
   mutation. Schema downgrade и automatic recovery не допускаются.
5. Задача, для которой delivery обязателен, получает `Done` только после green
   public smoke. Waiver не допускается: документированный blocker оставляет
   задачу не в `Done` до устранения. Skip фиксируется с причиной и разрешён
   только process/docs-only задаче без runtime diff.
6. Для compatible releases сохраняется ровно одна previous tuple и rollback по
   ADR-0018.
7. Первый CB-57 cutover выполняется manual-first: owner-approved mutation freeze,
   stop old writers, fresh backup, restore в новый project/new volume, exact
   migration `0020→0021`, activation. Old stopped project+volume остаётся initial
   rollback snapshot до public smoke или первой новой production mutation.
8. Первый HTTPS edge переиспользует existing nginx/TLS/origin. Landing `/`
   сохраняется; proxy открывает только `/mini-app` к upstream `/`,
   `/mini-assets/` и `/api/v1/`. Конфигурация бэкапится до mutation; unrelated
   services не меняются.
9. Не вводятся automatic CD, GitHub production environment, SSH/deploy-key/
   forced-command workflow, daemon, dependency, provider/framework или новый
   secret mechanism.
10. Release candidate обязан закрывать complete public launch path. Для первого
    rollout CB-57 это включает минимальный official Telegram bridge и
    server-validated fresh-session handshake; baseline artifact без handshake не
    разворачивается. После merge выбирается новый exact green artifact.
11. Pilot delivery выполняется последовательно. Более новый delivery-required
    merge до activation может supersede предыдущий только exact monotonic artifact,
    который доказанно содержит оба merge и проходит smoke scopes обеих задач.
    Каждая Jira issue фиксирует фактически активированный artifact и решение
    `deploy|superseded|skip`; stale activation и `Done` до smoke запрещены.
12. Initial activation требует zero-workload worker/outbox preflight на smoke
    window и before/after business-state proof. После initial ready worker
    останавливается на quiescent smoke window; разрешено только expected
    heartbeat изменение. Resume worker и outbound Telegram processing возможны
    лишь после green smoke, zero-backlog recheck и явного owner go-live gate.
    Любой другой worker effect/outbound attempt закрывает old rollback.

## Рассмотренные альтернативы

### Automatic CD/SSH

Отклонено: увеличивает privileged surface без необходимости для одного pilot.

### Переиспользовать old volume через `COMPOSE_PROJECT_NAME=community-bot`

Отклонено: скрытая host config dependency меняет project identity immutable
package и оставляет слабую rollback boundary после migration.

### Развернуть новый пустой PostgreSQL

Отклонено: потеря current production data и ложная готовность.

### Проксировать весь origin `/`

Отклонено: заменяет существующий landing page вне области CB-57.

### Считать green CI достаточным

Отклонено: CI не доказывает activation, host migration, edge routing или public
availability.

## Последствия

- Каждая продуктовая задача и любая задача с runtime diff имеют один явный
  production gate и доказуемую release identity; process/docs-only задача без
  runtime diff не создаёт бессмысленный deploy.
- Owner остаётся trust boundary migration и manual activation.
- First cutover имеет короткую mutation freeze и дополнительный restore step, но
  сохраняет old data boundary для initial rollback.
- После первой new production mutation rollback на old schema запрещён; дальше
  работает только compatible previous tuple ADR-0018.
- Process не обещает full UI parity: smoke ограничен delivered scope задачи.

## Связанные материалы

- Jira CB-57.
- [План CB-57](../../tasks/CB-57/plan.md).
- [План ручной проверки](../../tasks/CB-57/test-plan.md).
- [ADR-0018](0018-reviewed-image-and-host-package-tuple.md).
