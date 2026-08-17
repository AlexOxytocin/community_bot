# CB-64 — план минимизации с полным функциональным parity

## Результат

До создания web UI переписать текущий backend в небольшой модульный монолит для
закрытого сообщества из 20–30 человек. Весь существующий бизнес-движок
сохраняется. Удаляются не функции, а дублирующие слои, transport старого бота,
избыточные таблицы, повторяющиеся тесты и историческая документация.

Уровень риска: `3`: меняются архитектура, схема и способ доставки UI.
ADR-0017 принят владельцем 2026-08-17; runtime изменяется только последующими
задачами CB-51—CB-57 через их собственные gates.

## Жёсткие границы

1. Ни одна текущая пользовательская, административная или доменная возможность
   не удаляется, не ослабляется и не откладывается ради LOC/table/test ceiling.
2. Удалять можно старый Telegram chat UI, long polling, callback/FSM transport и
   технические test-run сущности после data inventory. Telegram Mini App и Bot
   API notifications остаются.
3. Перед удалением старой реализации каждый capability и invariant обязан иметь
   строку `old evidence → new owner → scenario test` в parity matrix.
4. Непокрытая строка означает `stop`, а не молчаливое упрощение продукта.
5. Shared/production database не считается пустой. Старая БД не удаляется и не
   перезаписывается этим refactor.
6. Размеры ниже — ceilings. Если полный parity доказанно требует больше, владелец
   получает измеренный конфликт и принимает новую границу.

## Сохраняемый движок

### Участники и доступ

- одноразовые приглашения, отзыв и срок;
- регистрационная заявка, принятие правил, approve/reject;
- профиль, timezone, skills и правила видимости;
- роли member/moderator/administrator/superadministrator, granular permissions;
- статусы pending/active/paused/restricted/suspended/left/banned и effective
  status с истечением временных санкций;
- журналируемые административные изменения.

### Задания и каталог

- categories, admin-managed templates и создание без шаблона;
- member, group/multi-slot и community task origin;
- размеры времени, reward rules, criteria, materials, format и deadline;
- community publication approval и independent reviewer;
- open/accept/close-for-new/withdraw/cancel flows;
- cancellation requests/responses для занятых групповых слотов;
- версии результата, submit, full/partial accept, reject и revision;
- review deadline, dispute deadline, expiry, auto-finalization и no-show;
- история созданных/принятых заданий и фильтруемый каталог.

### Экономика и репутация

- immutable credit/experience ledger, starting grant, reserve, earn, refund,
  partial/community reward, penalty, adjustment и fraud reversal;
- ровно один settlement на слот, отсутствие двойных/отрицательных эффектов;
- experience, version-aware levels и leaderboard;
- karma eligibility после оплаченного взаимодействия, `+1/0/-1`, изменение,
  history, moderation exclusion/restoration и privacy;
- reliability events, no-show и append-only corrections.

### Модерация и эксплуатация

- disputes, evidence, seven resolution outcomes и post-payment fraud;
- одна appeal, conflict-of-interest и exact reversal без частичного эффекта;
- notice/warning/restriction/suspension/ban, срок и отмена;
- moderation risk signals без автоматического наказания;
- interaction alerts, pair window/threshold, private notes, outcomes и
  idempotent penalties;
- immutable versioned product config, validation, activation и level backfill;
- notifications, reminders, retries, deadlines/finalizers;
- audit, idempotency и восстановление после перезапуска.

## Что удаляется

- aiogram handlers, callback routing, menus, Telegram conversation FSM и long
  polling как старый UI transport;
- `processed_telegram_updates` после переноса exactly-once mutation semantics в
  общий HTTP operation receipt;
- production test-run runtime после inventory/archive; локальные test fixtures
  не становятся production entities;
- protocols, repositories, UnitOfWork, factories и adapters с одной
  реализацией и без самостоятельного правила;
- повторяющиеся DTO/domain/database представления одного состояния;
- таблицы, которые можно объединить с typed payload, сохранив историю,
  ограничения, индексы и проверяемый import;
- дублирующие тесты одного инварианта, global coverage percentage и docs-only
  тесты, проверяющие prose вместо поведения;
- superseded task artifacts, custom agent framework и исторические living docs
  после переноса актуальных правил;
- React/Vite/Node toolchain, пока нативный web UI укладывается в согласованный
  предел и проходит browser/accessibility gates.

## Целевая архитектура

Один Python application image содержит FastAPI API, статические файлы Mini App
и небольшой background loop. Одна PostgreSQL хранит authoritative state,
ledger, event history и outbox. Отдельные broker, cache, event bus, DI container
и microservices не вводятся.

```text
src/community_bot/
  config.py          # env и versioned product config validation
  db.py              # engine/session и небольшие SQL helpers
  models.py          # компактная схема
  auth.py            # Telegram initData и session cookie
  members.py         # registration, profiles, roles/status/invitations
  tasks.py           # catalog, tasks, assignments, deadlines, settlement
  reputation.py      # levels, karma, reliability, leaderboard
  moderation.py      # cases, disputes, appeals, sanctions, alerts
  notifications.py   # outbox, reminders, retries, finalizers
  api.py             # HTTP routes и static Mini App
  admin.py           # те же use cases для admin UI/CLI
web/
  index.html
  app.js
  styles.css
```

Use case принимает `AsyncSession`; транзакция — `async with session.begin()`.
Feature function содержит правило рядом с запросом. Общий helper появляется
только после второго реального use case. Деньги, status transitions,
idempotency receipt, audit и outbox intent коммитятся одной транзакцией.

Background loop в том же image забирает PostgreSQL outbox через
`FOR UPDATE SKIP LOCKED`, обрабатывает notifications, reminders и due
finalizers, сохраняет attempts/next retry. Его можно запустить вторым process
того же image только если deploy probe докажет, что web lifecycle недостаточен;
новой очереди или worker framework для этого не добавляется.

Frontend — semantic HTML, CSS и ES modules. Он не вычисляет деньги, права,
eligibility или transitions: только отображает server state и вызывает API.

## Кандидат компактной схемы

Это design target, а не разрешение потерять данные. Финальный DDL принимается
только после parity/import spike.

1. `members` — Telegram identity, registration application, profile, role,
   permissions, status и cached derived totals.
2. `invitations` — hash, creator, expiry, revoke и redemption/application link.
3. `sessions` — opaque digest, member, expiry и revoke.
4. `product_config_versions` — immutable validated JSON с categories, templates,
   levels, economy/deadline/alert parameters и activation metadata.
5. `tasks` — origin, author, publication approval, reviewer, template/config
   snapshots, slots, reward, content, lifecycle и deadlines.
6. `assignments` — performer slot, state, result versions, cancellation flow,
   reviewer generation, settlement and deadline fields.
7. `account_transactions` — immutable credit/experience delta, source,
   reversal link и stable business key.
8. `reputation_events` — typed append-only karma vote/history/moderation и
   reliability/correction events.
9. `moderation_cases` — typed disputes/evidence/resolutions/appeals, sanctions,
   risk signals, interaction alerts/outcomes/private notes and relations.
10. `operations` — idempotency receipt и audit для mutation/read-audit events.
11. `outbox_events` — notifications, reminders/finalizers, dedupe, schedule,
    attempts и delivery outcome.

Допускается двенадцатая таблица только при доказанном invariant или запросе,
который JSON/event consolidation делает менее надёжным либо заметно сложнее.
Typed event payloads валидируются Pydantic-моделями; discriminator/version
обязательны. Динамические input/result schemas шаблонов продолжают исполняться
`jsonschema.Draft202012Validator`: Pydantic не является их заменой. Часто
используемые state, actor, subject, timestamps и business keys остаются
обычными колонками с constraints/indexes, а не прячутся в JSON.

Constraint spike уже зафиксирован в `parity-map.json`: append-only triggers,
partial unique active config/open pair alert, unique appeal/business key/slot,
monotonic revisions/corrections, immutable history prefixes, private payload
boundary и outbox lease CAS. Если любой из этих инвариантов нельзя доказать в
11–12 таблицах без сложного generic framework, ceiling поднимается до изменения
функции.

## Parity matrix и минимальные tests

Machine-checkable `parity-map.json` входит в пакет CB-64 уже до принятия ADR. Он
классифицирует все 43 legacy tables и для каждого capability фиксирует точный
old rule/test node, new owner/table/constraint, transformation, exact planned
scenario node и oracle. CB-51 заменяет `planned_test` на реально собранный node
ID и статус `passing`; неизвестный source path/table или непрошедший oracle
блокирует удаление старого owner.

| Пакет сценариев | Что доказывает | Бюджет |
|---|---|---:|
| Auth/registration/member | invite, application, approve/reject, sessions, roles/status/profile visibility | 6–8 |
| Tasks/catalog | templates, free/group/community tasks, slots, publication, cancellation, results, deadlines | 12–16 |
| Economy | reserve/pay/refund/partial/community, idempotency, reversal и races | 7–9 |
| Reputation/config | versions/activation/levels, karma/history/privacy, reliability, leaderboard | 7–9 |
| Moderation | disputes/evidence/resolution/appeal, sanctions, risk и interaction alerts | 8–10 |
| Notifications/operations | audit, outbox retry/dedupe, reminders/finalizers/restart | 4–6 |
| Durable drafts | task creation, assignment submission и moderation decision: owner/revision/restart/exact confirm | 3 |
| Migration/browser | isolated full-data import и критические Mini App journeys | 6–8 |

Итого: целевые `53–68`, ceiling `80` tests и `5 000` test LOC. Parametrization
считает набор примеров одним сценарием, но отчёт показывает каждый case.
Property tests остаются только для ledger/reversal arithmetic. Глобальный
coverage threshold удаляется. Для каждого slice сначала печатается targeted
coverage только изменённых runtime-модулей и проверяется, что у каждой
непокрытой business branch есть объяснение либо добавлен exact case; затем
запускается полный suite. Критерий — ноль строк parity matrix без passing exact
case, сохранённый per-slice coverage report и зелёный полный gate.

Обязательные concurrency tests:

- конкурентное принятие последнего slot;
- approve против cancel/expiry/dispute;
- две активации product config;
- exact replay и conflicting replay одной operation;
- один terminal settlement/outbox intent при повторной доставке;
- penalty/reversal не создаёт отрицательный доступный баланс или опыт.

## Auth и transport

- Telegram `initData` проверяется через `hmac`/`hashlib`: signature,
  `auth_date`, допустимый возраст и обязательные поля;
- raw `initData`, cookies, private moderation notes и секреты не логируются;
- session token — random `32` bytes, в БД keyed digest;
- cookie: `__Host-community_session`, `Secure`, `HttpOnly`, `SameSite=Strict`,
  `Path=/`, без `Domain`; TTL и revoke заданы явно;
- unsafe methods требуют точного allowlisted `Origin`; CORS выключен для
  same-origin Mini App;
- status, permissions, task ownership и conflict-of-interest перечитываются на
  каждый защищённый use case;
- request/text/list limits заданы явно; client claims не являются authority;
- mutation принимает `Idempotency-Key`; scope — `(namespace, actor_id, key)`.

Server сам строит canonical fingerprint из validated command. Exact replay
возвращает сохранённый outcome; иной command/payload с тем же ключом — `409`.
State, ledger, audit и outbox intent фиксируются одной транзакцией.

## Зависимости и размер

Целевые direct runtime dependencies: SQLAlchemy, asyncpg, Alembic, Pydantic,
jsonschema, FastAPI, Uvicorn и tzdata. `jsonschema` сохраняется для точной Draft
2020-12 validation динамических и исторических шаблонов. Bot API, logging и env
используют stdlib. Удаление каждой зависимости происходит только после
`rg`/import gate и прохождения полного suite.

Общие ceilings готового дерева:

- backend/API: `≤10 000` Python LOC;
- tests: `≤80` сценариев и `≤5 000` LOC;
- schema: `≤12` tables, если parity доказан;
- frontend: `≤3 000` LOC, без npm/runtime dependencies;
- direct runtime dependencies: `≤8`; снижение до `7` допустимо только после
  доказанной old/new validation equivalence всех сохранённых template schemas;
- living docs: ровно `6` Markdown files и `≤1 500` LOC;
- net deletion от baseline: минимум `18 000` строк до lockfile.

`ops/check_size.py` стандартной библиотекой считает tracked paths, tests,
tables, dependencies, docs и net diff от commit baseline. Metric failure
останавливает merge, но не разрешает удалять capability.

## Документация

После принятия ADR актуальные правила консолидируются в:

1. `README.md` — назначение, локальный запуск и ссылки.
2. `AGENTS.md` — Jira/Git/Ponytail и правила разработки.
3. `docs/PRODUCT.md` — полный пользовательский и доменный контракт.
4. `docs/ARCHITECTURE.md` — code/data/auth/transaction contracts.
5. `docs/OPERATIONS.md` — deploy, backup, restore, monitoring и rollback.
6. `docs/DECISIONS.md` — актуальные решения и список заменённых ADR.

Git history остаётся архивом. Accepted ADR удаляются из tree только после
принятия ADR-0017, который явно меняет текущую политику. До этого существующие
документы не удаляются. Path-level keep/merge/delete inventory обязателен;
неclassified tracked path блокирует merge.

## Evidence-first migration

1. Read-only inventory каждой shared/production DB: identity, Alembic heads,
   row counts, state aggregates, member counts, ledger/config/case/outbox
   checksums без PII. Недоступность или неоднозначный head — `stop`.
2. Encrypted backup и доказанный isolated restore до любого cutover.
3. Новая компактная схема создаётся в отдельной database/volume. Старую БД
   refactor не изменяет и не удаляет.
4. Importer переносит весь бизнес-функционал и историю: members/invitations/
   applications, catalog/templates/config/levels, tasks/slots/results/
   cancellations/deadlines, ledger/experience, karma/reliability, disputes/
   appeals/sanctions/alerts, audit/operations/outbox.
5. Sessions не импортируются: все пользователи проходят новую auth session.
   Старый runtime выключается до cutover, новый operation namespace не
   пересекается с Telegram receipts. Test-run и conversation-state rows
   остаются в восстановимом архиве, если inventory не докажет business value.
6. Import gate: source/target counts по capability, per-member balance и
   experience, aggregate checksums, active task/assignment state, terminal
   settlement uniqueness, config hash, case chains, notification dedupe и
   deterministic rerun. Любое расхождение — `stop`.
7. Cutover проходит в maintenance window с полным запретом mutations. После
   import выполняются read-only и synthetic rollback-able probes, reconciliation
   и окончательный go/no-go. До первой реальной mutation rollback возвращает
   старые image/database.
8. Первая реальная mutation является явной точкой смены rollback boundary.
   После неё старая БД остаётся только read-only архивом: rollback меняет app
   image на предыдущий совместимый compact-schema image, но никогда не
   переключает записи назад в legacy DB. Новые ledger/state/audit/outbox остаются
   в compact DB. Emergency recovery использует её backup/WAL и fix-forward.
9. Если нужен возврат к legacy runtime после первой mutation, writes замораживаются,
   delta всех новых operations сначала переносится обратным проверенным
   converter и сверяется по тем же checksums. Без равенства switch запрещён.
   Удаление старой БД не входит в CB-64 и требует отдельного destructive решения.

## Пошаговая реализация через существующие задачи

### Шаг 0 — CB-64: принять контракт

- Завершить source audit, полную `parity-map.json`, ADR и независимый plan review.
- Получить явное решение владельца по ADR-0017.
- Зафиксировать path/hash inventory незакоммиченных CB-51/CB-52 artifacts,
  удалить только эти superseded worktrees и пересоздать их от `main`.

Gate: plan review `approved`, ADR принят, Jira CB-51—CB-57 переписаны под карту
ниже. Rollback: документов/веток runtime нет; при отказе ADR сохраняется текущий
`main`.

### CB-51 — компактное ядро и data migration

- Реализовать уже принятую parity matrix и compact schema constraints.
- Реализовать session/operations/outbox primitives и importer.
- Переносить feature slices только за characterization test: members → tasks →
  ledger → reputation/config → moderation.
- Старый код удалять сразу после parity gate конкретного slice.

Precondition: ADR-0017 принят; CB-51 создана от merged CB-64 `main`; production
inventory/backup/isolated restore доступны. Gate: ноль unmapped capabilities;
каждый реализованный planned node реально собирается и проходит; новая пустая
migration и full isolated import
проходят; old/new scenario outcomes совпадают; schema `≤12`; старая БД не
изменена. Stop: первая divergence, недоказанный constraint или необходимость
урезать behavior. Rollback: до cutover — legacy image/database; внутри ветки —
последний зелёный slice commit. После review/CI CB-51 merge в `main` до CB-52.

### CB-52 — Telegram Mini App auth и API foundation

- Проверка initData, session lifecycle, Origin/permissions и idempotency.
- Тонкие HTTP routes над функциями CB-51; OpenAPI только как генерируемый
  контракт, без отдельного schema framework.

Precondition: CB-51 уже merged, ветка CB-52 создана от обновлённого `main`.
Gate: auth/security scenarios, API contract smoke, secret/log scan, restart
probe и targeted coverage `auth/members/api`. Stop: identity/Origin/status
authority может быть обойдена или API требует новый generic слой. Rollback:
предыдущий `main` image; пользователей ещё нет. После review/CI CB-52 merge.

### CB-53 — профили, каталог и репутация в Mini App

- Registration/profile/member cards, balances/history, levels, karma,
  reliability summary и leaderboard.
- Catalog filters и read-only task cards.

Precondition: CB-52 merged и стабильный API contract доступен. Gate: browser
paths для member/admin visibility, accessibility/keyboard/contrast,
соответствующие API scenarios и targeted coverage `members/reputation`.
Frontend cumulative `≤3 000` LOC. Stop: capability недоступен без изменения
backend contract либо UI требует бизнес-правило в JS. Rollback: удалить только
новые static assets/routes до последнего merged API; после review/CI CB-53 merge.

### CB-54 — полный task engine в Mini App

- Free/template create, member/group/community tasks, slots and publication.
- Accept/withdraw/cancel, result versions, full/partial/reject, deadlines,
  disputes entry и history.

Precondition: CB-53 merged; task/economy planned nodes CB-51 green. Gate: все
task/economy exact cases, targeted coverage и concurrency/browser journeys;
ни одно правило settlement не вычисляется в JS. Stop: расходится любой slot,
ledger, deadline или legacy outcome. Rollback: предыдущий merged UI/API image и
compact DB migration down только до первой реальной mutation; после review/CI
CB-54 merge.

### CB-55 — полный admin/moderation UI

- Invitations/applications/members, categories/templates/config activation.
- Community review, disputes/evidence/resolution/appeal, sanctions, karma review,
  risk signals, interaction alerts/outcomes/penalties и audit views.

Precondition: CB-54 merged; moderation data/import rows reconciled. Gate:
permission/conflict/privacy/reversal exact cases, targeted coverage и browser
admin journeys; private notes отсутствуют в logs/notifications/member responses.
Stop: DB constraint/privacy boundary или old/new outcome не доказан. Rollback:
предыдущий compatible compact image/schema; после review/CI CB-55 merge.

### CB-56 — HTTPS deploy

- Один app image, private PostgreSQL, migration/import job, health/readiness,
  scheduled loop, backup/restore и immutable rollback.

Precondition: CB-55 merged; immutable reviewed commit записан как release
candidate; mutation freeze активен. Gate: deployment именно этого commit,
HTTPS/auth, restart/retry, isolated restore, pre-write legacy rollback и
post-write compatible-image rollback drill. Stop: commit mismatch, backup/
reconciliation failure или потеря synthetic delta. Rollback: до первой реальной
mutation — legacy image/database; после неё — только предыдущий compatible
compact image с той же compact DB. После review/CI CB-56 merge.

### CB-57 — release acceptance

- Controlled Mini App E2E полного member и admin цикла на test accounts.
- Проверка reminders/notifications и одного безопасного moderation journey.
- Финальная проверка parity matrix, sizes, docs и отсутствие старого bot UI.

Precondition: CB-56 merged и тот же reviewed commit deployed; backup и rollback
boundary записаны. Gate: все строки parity matrix green, targeted/full CI green,
production deploy и E2E проверены, compact backup/rollback доказаны. Stop: любая
строка parity/route inventory красная или deployed commit отличается. Rollback:
до owner go-live — CB-56 release candidate и mutation freeze; после первой
реальной mutation — предыдущий compatible compact image без смены DB. CB-57
merge после acceptance; задачи не удаляются, потому что относятся к Mini App.

## Проверяемые команды

- `uv run python ops/check_size.py --baseline 019850c`
- `uv run pytest tests -q --no-cov`
- `uv run pytest <slice-tests> --cov=<changed-runtime-modules> --cov-report=term-missing`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run ty check`
- `docker compose config`
- migration/import/restore commands из `docs/OPERATIONS.md`.

## Stop conditions

- хотя бы одна business capability или invariant не имеет нового owner/test;
- source database недоступна, backup не восстанавливается или import расходится;
- race создаёт двойной settlement, потерю outbox intent или две config activation;
- приватные данные попадают в API/log/notification;
- сокращение требует изменить продуктовый исход;
- schema/LOC/test ceiling не достигнут без потери parity — останавливаемся и
  пересматриваем ceiling, а не функцию.

## Критерии CB-64

| Критерий | Доказательство |
|---|---|
| Baseline измерен | `plan-source-context.md` |
| Полный функциональный scope сохранён | разделы «Жёсткие границы» и «Сохраняемый движок» |
| Удаляется реализация, не продукт | точный список удаления и Ponytail audit |
| Parity проверяем | machine-checkable matrix и scenario node IDs |
| Data safety/rollback явны | evidence-first migration и step gates |
| CB-51—CB-57 без потерь сопоставлены | семь существующих задач, без нового backlog |
| Структурное решение оформлено | ADR-0017 `Принято` владельцем 2026-08-17 |
| Начало runtime защищено | independent review + explicit owner acceptance |
