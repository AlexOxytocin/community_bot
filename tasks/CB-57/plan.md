# CB-57 — план первого production pilot deploy и post-task delivery gate

## Цель

Развернуть на одном pilot exact immutable release текущего реализованного среза
Community Mini App и закрепить постоянное правило доставки после merged задач,
которые меняют deployable runtime/config. Работа имеет уровень 3 из-за production,
security, migration и data-cutover риска.

CB-57 не является полной parity-приёмкой backend. Будущие UI capabilities
сохраняются за границами задачи; отсутствие экрана не означает удаления backend-
возможности или её доступность через текущий Mini App.

## Область изменений

- Proposed ADR-0019 и минимальные согласованные изменения process-документов:
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md`, `docs/release-2/README.md`, `agents/workflow.yaml` и
  один machine-checkable contract в существующем architecture test.
- Минимальный go-live blocker fix в существующих static files: official Telegram
  bridge, fresh-session handshake через существующий auth endpoint и один
  browser/integration oracle; без npm, framework или нового backend contract.
- Ручной first cutover одного pilot из нового exact green post-CB-57 release по
  ADR-0018 и `ops/release_contract.py`; `#71/1` остаётся baseline evidence.
- Owner-gated freeze, backup, restore в новый Compose project/volume, migration
  `0020→0021`, activation, readiness и public smoke.
- Одноразовый path-scoped nginx edge: сохранить landing page на `/`, открыть
  только `/mini-app`, `/mini-assets/` и `/api/v1/` к внутреннему `web`.
- Privacy-safe release/deploy/smoke evidence в Jira и task report после
  реализации.

## Вне области изменений

- полный UI parity и объявление всего backend доступным в Mini App;
- новые product screens, domain behavior или browser authentication;
- изменение immutable release bundle/Compose, `ops/release_contract.py` или
  migration `0021` ради обхода host topology;
- automatic CD, GitHub production job, SSH/deploy-key/forced-command workflow,
  daemon, dependency, provider/plugin/inventory abstraction;
- schema downgrade, automatic recovery, удаление old volume в CB-57;
- server IP, credentials, secret paths/content, `.env` content и raw auth data в
  git, Jira или evidence.

## Текущее состояние

- Base: `origin/main` `30ad7277e8cc23698706e32e583c1d78044286c4`.
- Baseline release: run `32106370758`, `#71/1`, artifact
  `community-mini-app-release-71-1` id `9313314990`, manifest SHA-256
  `2de8c1a18c01bf00e5cee3e07ffc0c9b9fd8e2cd3ac2961cc67b5ec6e37249af`,
  image `ghcr.io/alexoxytocin/community_bot@sha256:4090e0306fe275adb2119d8450c4c3035f186f261bd31ce31a56adb81a804d9f`,
  packaged head `0021`.
- Release 71 доказывает publication contract, но не является deploy candidate:
  current `index.html` не загружает official Telegram bridge, а `app.js`
  bootstrap сразу вызывает `/api/v1/me` и `/api/v1/tasks`, не отправляя
  `Telegram.WebApp.initData` в существующий `/api/v1/auth/telegram`. Fresh user
  не может получить session. Deploy candidate создаётся только новым exact green
  release после merge минимального CB-57 fix.
- Host: Ubuntu 24.04 arm64, Docker 29.2.1, Compose 5.0.2; current old project
  `community-bot`, network `community-bot_internal`, volume
  `community-bot_postgres-data`, live DB head `0020`.
- Artifact project `community-mini-app-core` использует отдельные network/volume.
  Поэтому initial `activate` до cutover fail-closed: `_preflight` не может
  выполнить `compose exec postgres` в несуществующем новом project.
- Migration `0021` только создаёт `web_sessions`; integration oracle доказывает
  сохранение существующих таблиц и данных.
- Текущий UI: catalog/task detail/accept, active assignments list/detail и
  read-only moderation queue. Это и только это входит в public acceptance.
- Существующий nginx уже обслуживает HTTPS и landing page на
  `allo.godmodetools.com`; он подключён только к `app_app_network`.

## Предлагаемое решение

### 1. Owner gate до любой server mutation

**Решение:** принято владельцем 2026-08-18 ответом «да разрешаю» для всех шести
пунктов ниже; ADR-0019 переведён в статус `Принято`. Разрешение не включает
чтение Telegram chats, отправку сообщений или live Telegram interaction.

Получить одно явное решение владельца, принимающее:

1. Proposed ADR-0019 и постоянный post-task delivery process;
2. one-time data cutover в новый project/volume;
3. временную mutation freeze от остановки old bot/worker до успешного public
   smoke либо rollback;
4. schema change `0020→0021`;
5. path-scoped edge go-live без изменения `/`.
6. conditional resume нового worker и outbound Telegram processing только после
   green smoke и повторного zero-backlog check.

Без полного подтверждения остановиться. Принять ADR за владельца нельзя.

### 2. Повторная идентификация перед cutover

- После merge CB-57 дождаться нового green release и выбрать его exact run;
  release 71 не разворачивать как user-testable. Проверить `success`, доступность
  artifact и записать exact commit/run/artifact/manifest/image/head identities.
- Проверить host architecture/tool versions, root ownership/modes, отсутствие
  managed `active.json`/конфликтующей initial release и локальное наличие exact
  image RepoDigest/OCI labels.
- Зафиксировать только безопасные identities; содержимое environment не читать в
  evidence.
- Выполнить pure `release_contract.py verify` и staged initial `activate` только
  настолько, насколько contract безопасно устанавливает content-addressed
  package до ожидаемого migration-head stop. Не создавать `pending` до green
  `_preflight`.

### 3. Минимальный fresh-session handshake до нового release

- В `index.html` подключить official `telegram-web-app.js` в `<head>` раньше
  других scripts, как требует Telegram Mini Apps documentation.
- В существующем `app.js` сначала проверить session через `/api/v1/me`. Только
  при `401` прочитать exact `globalThis.Telegram?.WebApp?.initData`; пустое или
  отсутствующее значение вне Telegram завершает bootstrap закрытым состоянием.
- Непустое значение один раз POST в существующий `/api/v1/auth/telegram`, не
  логировать и не сохранять client-side. Request body — raw `initData`, exact
  `Content-Type: text/plain; charset=utf-8`, same-origin `Origin` и
  `credentials: same-origin`, как требует existing endpoint. После `204` ровно
  один раз повторить bootstrap и загрузить `/me` + `/tasks`. Любой auth error
  fail closed без loop.
- Изменить CSP только на allowlist official Telegram script origin; не добавлять
  `unsafe-inline`, новый connect origin или package dependency.
- Расширить один существующий browser/integration scenario: fresh context без
  cookie получает initial `401`, bridge `initData` отправляется exact один раз,
  session устанавливается, повторный bootstrap показывает catalog; missing и
  invalid initData не вызывают retry loop. Existing-session path не POSTит proof.

Это остаётся в CB-57, а не в отдельном bug issue: blocker обнаружен в release
acceptance, исправление затрагивает один cohesive launch journey и не имеет
самостоятельной продуктовой области.

### 4. One-time data cutover (вариант A)

1. Объявить mutation freeze; проверить отсутствие незавершённых операций и
   текущую health/backup boundary. Отдельным read-only preflight доказать, что
   на весь ожидаемый smoke window нет due assignment finalizers/reminders,
   deliverable/retry/leased outbox rows и другого worker workload; ненулевой
   результат блокирует cutover.
2. Остановить только old bot/worker, оставив old PostgreSQL доступным для fresh
   consistent backup. Подтвердить отсутствие новых mutations.
3. Создать one-time fresh custom-format backup native `pg_dump` внутри old
   PostgreSQL container. До запуска сверить source `pg_dump` и target
   `pg_restore` versions; target должен поддерживать source dump. Вывод писать с
   restrictive umask во временный root-only regular file, проверить success,
   mode `0600`, ненулевой размер и checksum, затем atomic rename. Checksum
   фиксируется без пути или содержимого. Packaged
   `backup_postgres.py` здесь ещё неприменим: до initial activation нет
   `active.json=ready`. Команда остаётся единичной operator command, новый
   repository script не создаётся.
4. В exact staged package поднять только новый PostgreSQL/new volume проекта
   `community-mini-app-core` без worker/web.
5. Восстановить backup native `pg_restore` внутри new PostgreSQL container;
   использовать `--no-owner --no-privileges` и stop на любом nonzero exit.
   Подтвердить head `0020`, ledger reconciliation и exact counts `members`,
   `tasks`, `assignments`, account transactions, audit и outbox до migration;
   повторить те же checks после `0021`. Packaged
   `restore_drill.py` не подменяет initial production restore: он предназначен
   для isolated drill уже выбранного ready release.
6. Exact target image выполнить единственную migration `0020→0021`; подтвердить
   singleton head `0021`, наличие пустой `web_sessions` и сохранение старых
   данных/counts.
7. Повторить root-only `activate`: теперь target/image/live heads совпадают;
   activator запускает worker/web и завершает `active.json=ready`. Сразу после
   ready остановить new worker на smoke window: activator не умеет quiescent
   mode, а worker каждые две секунды может финализировать deadlines, писать
   outbox и отправлять Telegram.
8. Старый project и volume не удалять и не мигрировать: они остаются
   остановленным initial rollback snapshot до завершения read-only smoke и
   rollback rehearsal, но в любом случае только до первого mutating request,
   worker side effect или outbound attempt.

До activation снять privacy-safe business-state fingerprint/counts для tasks,
assignments, ledger, audit, outbox и delivery markers. После остановки new worker
сверить их повторно: разрешено только ожидаемое heartbeat обновление exact new
release; business/outbox/delivery state должен быть неизменен. Любое другое
изменение или outbound attempt закрывает old rollback и останавливает acceptance
на fix-forward. Уже выданный conditional owner gate разрешает Telegram delivery
и resume worker только после green public smoke и повторного zero-backlog check;
новый вопрос владельцу не требуется. После resume readiness проверяется ещё раз.

Quiescent smoke window time-bounded: после остановки worker `/readyz` закономерно
может стать stale/`503`, поэтому в этом окне отдельно проверяются web liveness,
PostgreSQL и public paths. Это не final ready state. Success/`Done` требует
conditional worker resume, zero-backlog recheck, Compose health и `/readyz=200`.

Любая production business mutation в новом project закрывает rollback на old
head `0020`; после неё допускается только compatible release tuple без schema
downgrade. В acceptance CB-57 mutation freeze сохраняется до smoke.

### 5. One-time HTTPS edge

- Снять exact backup изменяемых nginx/compose bytes и проверить rollback-команду.
- В существующем `/opt/app` Compose объявить уже существующую
  `community-mini-app-core_internal` как external network и постоянно подключить
  к ней только nginx; остальные services/config не менять.
- Сохранить существующую обработку `/` и static landing page.
- Добавить exact locations:
  - `/mini-app` → upstream `web` path `/`;
  - `/mini-assets/` → тот же path upstream;
  - `/api/v1/` → тот же path upstream с нужными proxy headers.
- Публичный health route не добавлять: внутренний `/readyz` проверяется на host.
- До reload через Docker network inspection доказать, что alias `web` на target
  network принадлежит ровно одному container с Compose labels project
  `community-mini-app-core`, service `web`; из nginx network namespace проверить
  expected `http://web:8000/healthz`. Ambiguous alias/endpoint блокирует edge.
- Сначала `nginx -t`, затем точечный reload/recreate nginx без остановки
  несвязанных `/opt/app` services.
- Edge rollback является отдельной частью stop plan: сначала закрыть Mini App
  traffic atomic restore exact nginx/Compose bytes без трёх locations, выполнить
  `nginx -t` и reload, доказать landing fingerprint/health unrelated services,
  затем убрать external network attachment. Только после этого исключить split
  brain и переключать runtime/data. Runtime rollback без edge teardown неполон.
- Возврат из rehearsal в new state не вызывает same-digest `activate`: при
  `active.json=ready` он только проверяет `_ready` и не поднимает остановленные
  services. После остановки old PostgreSQL оператор exact staged Compose
  package явно force-recreate/wait запускает new worker/web тем же lifecycle,
  доказывает ready, снова останавливает worker для quiescent window, затем
  повторяет unique-upstream preflight, external network attachment и atomic
  apply/`nginx -t`/reload path-scoped edge. Любой шаг failure оставляет traffic
  закрытым и блокирует public mutation.

Маршрут совместим с текущим frontend: index доступен через `/mini-app`, а JS
использует абсолютные `/mini-assets/...` и `/api/v1/...` на том же HTTPS origin.

### 6. Public acceptance и evidence

- До edge сохранить response/body fingerprint landing page `/`; после edge
  доказать, что status и content fingerprint не изменились.
- Проверить HTTPS `/mini-app`, статические assets, auth bootstrap/error boundary,
  catalog/task detail/accept exact retry, assignments list/detail и допустимую
  read-only moderation очередь по `test-plan.md`.
- Сначала выполнить landing/path/read-only UI и initial runtime+edge rollback
  rehearsal. Первый auth POST является mutating request и с момента его отправки
  old `0020` snapshot больше не допустим: дальнейший failure означает fix-forward
  плюс, при необходимости, edge rollback. Task accept выполняется последним
  functional gate; ambiguous request также немедленно закрывает old rollback,
  но на new DB обязан разрешаться exact same-key replay до детерминированного
  результата. Новый operation key при ambiguity запрещён.
- Не читать приватные чаты и не отправлять сообщения. Telegram launch/live
  interaction выполняется только при отдельном явном запросе на конкретное
  действие; HTTP/browser smoke не расширяет это разрешение.
- Записать Jira evidence: commit/run/artifact/manifest/image/migration identities,
  backup/restore status, readiness, path smoke, landing preservation, rollback
  boundary. Никаких secrets или raw user payload.

### 7. Постоянный process

После каждой merged задачи классифицировать diff:

- `deploy`: deployable runtime code, runtime config, migrations или frontend;
- `skip`: только docs, tests или `tasks/**` artifacts, без deployable bytes.

Для `deploy`: green main CI → exact immutable artifact → manual-first activation
на одном pilot → public smoke → Jira evidence. Migration-changing release требует
отдельного owner gate. Jira `Done` разрешён после green public smoke либо явного
owner-approved waiver. Документированный blocker оставляет задачу не в `Done`
до устранения или отдельного waiver. Для `skip` Jira evidence называет
классификацию и deployment не запускается. Один compatible rollback сохраняется
по ADR-0018.

Pilot delivery сериализуется. Если до activation предыдущей задачи в `main`
попал более новый deployable merge, stale artifact не активируется: выбирается
новейший green monotonic release, содержащий оба merge. Один public smoke может
закрыть несколько задач только с per-task scope evidence в каждой Jira issue.
Задача не получает `Done`, пока superseding artifact, содержащий её merge, не
прошёл smoke. Docs/tests/task-artifact-only merge не создаёт новую delivery
обязанность, но не разрешает активировать artifact, который не содержит уже
обязательный более новый deployable merge.

## Ключевые решения и альтернативы

- Выбран вариант A: новый project/volume, restore и migration. Он делает data
  boundary явной и сохраняет untouched initial rollback snapshot.
- Отклонён вариант B (`COMPOSE_PROJECT_NAME=community-bot`): скрытая host-only
  dependency подменяет project identity immutable package и не даёт безопасный
  rollback после migration `0021`.
- Отклонена подмена immutable Compose/package: ломает ADR-0018 provenance.
- Отклонён proxy всего `/`: уничтожил бы существующий landing page.
- Отклонены CD/SSH/framework: один pilot и manual-first contract уже закрывают
  задачу с меньшей privileged surface.
- Не добавляется initial-restore wrapper: два native PostgreSQL commands нужны
  один раз до появления ready state; после activation используются canonical
  Python backup/restore ops из selected release.

## Шаги реализации

1. После owner approval изменить статус ADR-0019 на `Принято` и обновить индекс.
2. Реализовать минимальный handshake и один fresh-session oracle; вне Telegram
   оставить fail-closed behavior.
3. Внести минимальный process diff и один deterministic architecture test для
   trigger/skip/owner-gate/Done contract.
4. Запустить targeted auth/browser/process tests, formatting/lint и secret scan;
   создать implementation report и independent final review.
5. Commit/push/PR/CI/merge task branch. CB-57 меняет frontend и поэтому сама
   классифицируется `deploy`; дождаться нового exact green release artifact.
6. После merge применить уже выданное conditional go-live разрешение и выполнить
   секции 2, 4–6 в строгом stop-on-failure порядке: resume/outbound допускаются
   только после green smoke и zero-backlog, без повторного вопроса владельцу.
7. Зафиксировать Jira evidence и только после public smoke предложить `Done`.

## Риски и меры снижения

- **Wrong DB/project:** exact names/head preflight; никакого прямого initial
  activation или пустой DB.
- **Data loss:** fresh backup + isolated restore + untouched old volume; freeze;
  root-only atomic dump, compatible tools, ledger/count/invariant checks до
  migration и после неё, explicit retention/cleanup после accepted smoke.
- **Split-brain mutations:** old bot/worker остановлены до new worker; freeze
  действует до smoke/rollback.
- **Worker side effects:** zero-workload preflight, before/after state fingerprint,
  немедленная остановка worker после activator readiness и отдельный owner gate
  перед resume/outbound processing.
- **Irreversible rollback:** old snapshot разрешён только до первой new mutation;
  затем fail-closed compatible tuple без downgrade.
- **Landing outage:** path-only locations, config backup, `nginx -t`, fingerprint
  before/after, explicit edge teardown rollback, unrelated-service check.
- **Artifact mismatch:** exact run/manifest/image/head verification ADR-0018.
- **Auth loop/proof leak:** один 401-triggered POST, один retry, no storage/logging,
  raw body с exact `Content-Type: text/plain; charset=utf-8`, same-origin
  credentials/origin, closed missing/invalid proof и existing-session no-POST
  oracle.
- **Privilege/secrets:** root-only existing tooling, bounded evidence, no new
  credential mechanism.
- **False parity claim:** acceptance ограничена перечисленным current UI slice.

## Проверки

Детальные ручные сценарии и stop conditions находятся в `test-plan.md`.
Implementation verification включает targeted test нового workflow contract,
fresh-session browser oracle, существующие release-contract/migration oracles,
`git diff --check`,
русскую языковую проверку и secret scan. Full regression не является per-task
gate; server acceptance заменяет её только для точно указанного текущего slice.

## Критерии готовности

- Plan review: `Status: approved`; owner отдельно принимает ADR и go-live gates.
- Exact current data восстановлены в new volume, migration head равен `0021`,
  worker/web ready, `active.json` ready.
- Fresh Telegram context получает server-validated session через exact один POST
  и успешный retry; outside-Telegram/invalid proof fail closed. Deploy identity
  относится к новому post-CB-57 release, не к release 71.
- Landing `/` сохранён; `/mini-app`, assets и API проходят public smoke.
- Old project+volume сохранён как evidence/initial snapshot; его rollback
  пригодность заканчивается с первым mutating request/side effect и честно
  записана.
- Process contract опубликован, протестирован и применён к CB-57.
- Jira содержит privacy-safe evidence. Blocker оставляет задачу не в `Done`;
  только green smoke или owner-approved waiver разрешает предложить `Done`.
