# CB-75 — исходный контекст плана

## Снимок Jira на 2026-08-18

- `CB-75`, история «Mini App: решение модератора по спору», статус
  `К выполнению`, приоритет `Medium`, родитель `CB-48` (`В работе`).
- Комментарии, attachments и issue links отсутствуют.
- Описание разрешает только read-only mapping, Ponytail audit, `plan.md` и
  независимый review до merge и production smoke CB-73/CB-74.
- `CB-73` и `CB-74` сейчас имеют status/resolution `Готово`; dependency gate
  снят. CB-74: merge commit
  `a62ed11c9f1f0fa98b0d42f440aa591cac9a4059`, release `82/1`, public smoke green.
- Fresh fetch подтвердил, что этот commit является точным `origin/main`; ветка
  `task/CB-75` создана от него. Jira CB-75 пока `К выполнению`.

## Уровень и архитектурное решение

Уровень `3` выбран по ADR-0004: web security/privacy, financial-like effects,
authorization, exact replay/concurrency и большой source set. Нужны
`plan-source-context.md` и независимый `plan-review.md`.

Новый ADR не нужен. План сохраняет принятые ADR-0013/0016/0017/0019: Mini
App-only, existing domain/application engine, PostgreSQL-authoritative
transaction, native HTML/CSS/ES modules, test-run isolation и post-task
delivery gate. Любая необходимость новой schema/transition/receipt subsystem
является stop, а не основанием писать ADR в CB-75.

## Канонические источники

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira-first, русский язык,
  Ponytail full, immutable effects, уровень 3 и delivery gate.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` — moderator/admin рассматривают споры;
  significant actions аудируются; финансовые операции атомарны и идемпотентны.
- `docs/mvp/02_DOMAIN_RULES.md` — reserve/system issuance, reliability,
  rejection/dispute windows, community origin и test-run isolation.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`, D-015/D-018/D-023/D-030/D-033 —
  partial rounding, community economy/conflict, resolution roles/codes/appeal,
  live smoke scope и HTTP operation identity.
- `docs/mvp/06_DATA_MODEL.md` — immutable dispute opening/evidence/resolutions,
  appeal, reliability corrections и private data boundary.
- ADR-0013 — `test_run_id` как access boundary, не UI marker.
- ADR-0017 — сохранить disputes/resolutions/ledger/audit/outbox; web только
  feature slice; без новых layers/dependencies.
- `docs/release-2/README.md` — backend единственный владелец правил;
  mutation replay/conflict и state/ledger/audit/outbox consistency.
- ADR-0019 — после будущего merge нужен exact immutable release, activation и
  public smoke до Jira `Done`.

## Read-only mapping фактического backend

### Domain и application

- `src/community_bot/domain/moderation.py`:
  `ResolutionCode` содержит семь кодов; `_RESOLUTION_EFFECTS` задаёт status,
  payout fraction, reliability и risk target; `resolution_effect` запрещает
  `creator_abuse|cancel_without_fault` для `origin=community`.
- `src/community_bot/application/moderation.py`:
  `ModerationService.queue` заново читает internal actor и допускает только
  active moderator/administrator; moderator не получает fraud-review cases.
  `resolve` вызывает существующий `ResolveCaseCommand` через единый `_mutate`.
- `_mutate` использует transaction update gate, stored receipt replay,
  server-side current actor/role, mutation owner, receipt и commit.
- Текущая application `ModerationCase` — intentionally narrow queue DTO; detail
  projection и web resolve route отсутствуют.

### Persistence и effects

- `src/community_bot/infrastructure/db/moderation.py::resolve_case`:
  locks case/assignment, проверяет expected revision/status/role/conflict,
  применяет `resolution_effect`, economy, reliability, immutable resolution,
  risk signal, outbox, audit и interaction-alert recompute в одной transaction.
- Initial `open` case создаёт resolution version 1. Appealed version 2 доступна
  только administrator и не входит в CB-75.
- Fraud case либо code доступны только administrator.
- `_reject_conflict` запрещает case party, inviter стороны, author prior
  sanction; appeal запрещён прежнему decision actor.
- `_apply_resolution_economy` переиспользует existing ledger commands:
  full/partial payout, member refund/remainder и community issuance.
- `DisputeResolutionModel` append-only: unique `(case_id, version)`, unique
  `command_id`, payload hash, effect links и conflict snapshot.
- Outbox business key — `moderation-case:{case_id}:resolution:{version}`;
  audit action — `moderation_case_resolved`.

### Current web и UI

- `src/community_bot/transport/web.py` уже имеет
  `GET /api/v1/moderation/cases`, whitelist DTO, current actor, `no-store` и
  bounded `limit`.
- `src/community_bot/transport/static/app.js` уже имеет moderation navigation,
  loading/empty/error queue и native DOM helpers. Cards ещё не открываются.
- `tests/integration/test_web_api.py` уже доказывает staff authorization,
  moderator fraud filtering, private queue whitelist и zero read effects.
- `tests/unit/test_moderation_domain.py` доказывает origin applicability;
  `tests/integration/test_moderation.py` отдельно доказывает четыре базовых
  member outcomes, administrator fraud, ledger/reliability/audit, conflict,
  rollback и concurrent one-winner.
- `tests/browser/test_mini_app.py` — существующий owner moderation UI/focus/back.

## Зафиксированные gaps

1. Queue/detail не применяют `active_scope` к moderation cases. Это исправляется
   reuse существующего test-run owner, без новой policy.
2. Нет safe moderator detail, поэтому web пока не может показать данные и
   допустимые коды без риска копирования правил.
3. Нет web resolution route. Текущий service contract исторически использует
   Telegram-shaped `update_id`/identity; CB-75 обязан переиспользовать общий
   HTTP mutation bridge после CB-73/CB-74, а не создавать второй.
4. Same-receipt replay текущего moderation service возвращает stored outcome
   до сравнения payload. Поэтому доказанный payload-bound HTTP owner на свежем
   main — hard gate. Domain `command_id + payload_hash` и stale revision дают
   дополнительную защиту, но не заменяют transport receipt conflict contract.
5. Current `moderation_case` outbox recipient branch не применяет
   `participant_ids`; reuse уже существующего filter owner в том же модуле
   требуется для closed test-run boundary.
6. Current UI не имеет detail/confirm state, но его существующие native helpers
   достаточны; новый frontend layer не нужен.
7. Точный `result_summary` owner зависит от CB-73. После remap разрешён только
   reuse её nullable allowlisted projection; arbitrary `payload_json` закрыт.

## Fresh remap после CB-73/CB-74

- CB-73 добавила allowlisted `AssignmentReviewDto` и assignment-card projection
  для safe `result_summary`; moderation detail переиспользует этот owner и не
  сериализует raw template payload.
- CB-74 добавила actor-native dispute mutation: internal actor проверяется до
  update receipt, identity gate сериализует actor/key, stored marker связывает
  actor и canonical payload fingerprint. Это точный ordering/replay образец для
  web resolution без новой receipt subsystem.
- Текущий route set содержит dispute creation и creator review list/detail/
  decision, но moderation по-прежнему имеет только list. CB-75 добавляет ровно
  `GET /api/v1/moderation/cases/{case_id}` и
  `POST /api/v1/moderation/cases/{case_id}/resolution`; exact inventory test
  обновляется синхронно.
- `app.js` уже содержит performer dispute и creator review states, native
  history/focus/back/idempotency helpers. Moderation queue остаётся последним
  неинтерактивным списком; новый router/state layer не нужен.
- Source ceiling не изменился: пять production owners (`application/moderation`,
  `db/moderation`, `web.py`, `app.js`, existing outbox branch) и три existing
  test owners. Schema/migration/dependency/service/repository/framework — ноль.

Ни один gap не требует новой domain transition, таблицы, migration, dependency,
service или repository. Если fresh remap опровергнет это, задача получает один
terminal blocker.

## Ponytail full audit

- `reuse:` current moderation service, storage owner, queue, auth, DTO/error
  conventions, native UI helpers и existing tests.
- `delete from scope:` appeals, sanctions, fraud UI, evidence UI, admin panel,
  generic operation framework and schema work.
- `native:` existing FastAPI/Pydantic route and HTML/CSS/ES modules.
- `new layers/dependencies/schema/migrations/services/repositories: 0`.
- Planning-only diff содержит только `tasks/CB-75/plan.md`,
  `plan-source-context.md` и после review `plan-review.md`.

## Fresh remap packet после снятия dependency gate

Перед runtime owner обязан повторно прочитать Jira CB-73/CB-74/CB-75, получить
fresh `origin/main`, проверить current HTTP operation identity owner, exact
routes/static navigation/test inventory и повторно трассировать `ResolutionCode`,
`resolve_case`, conflict, `active_scope`, receipts и effects. Любое изменение
владельца обновляет план до создания `task/CB-75`.
