# CB-74 — финальная повторная проверка amended plan

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- amended `tasks/CB-74/plan.md` и
  `tasks/CB-74/plan-source-context.md`;
- exact `origin/main`
  `95b0da6917c0ba41770be700e12195d50f21a34b` и фактический CB-73 diff
  `d1733cb49ff59a74e893320c19c15d58102b2045..95b0da6917c0ba41770be700e12195d50f21a34b`;
- exact owners и seams в
  `src/community_bot/domain/assignments.py`,
  `src/community_bot/application/assignments.py`,
  `src/community_bot/application/tasks.py`,
  `src/community_bot/infrastructure/db/assignments.py`,
  `src/community_bot/infrastructure/db/tasks.py`,
  `src/community_bot/transport/web.py`,
  `src/community_bot/transport/static/app.js` и связанных
  web/browser/unit tests;
- предыдущий `changes_requested` verdict и все три его
  `required_actions`;
- переданный Jira scope и dependency handoff, канонические правила проекта,
  инструкция `plan-reviewer` и Ponytail full.

`git rev-parse origin/main` повторно вернул exact `95b0da6`. Проверка была
read-only: тесты не запускались, runtime/tests/Git/Jira/Telegram не изменялись.
Единственная запись этого review — данный файл.

## Findings по области (`scope_findings`)

Обязательных замечаний нет.

- План теперь включает обязательный
  `tests/unit/test_web_auth.py::test_web_config_and_route_set_are_closed`,
  который должен принять новый
  `POST /api/v1/assignments/{assignment_id}/disputes`. Это закрывает точный
  closed route-set contract, фактически подтверждённый CB-73 diff.
- Ceiling честно расширен до семи runtime/test файлов. Покомпонентная allocation
  равна общему пределу: `80 + 60 + 70 + 125 + 45 + 10 + 10 = 400`
  additions; deletion ceiling остаётся `40`. Превышение по-прежнему является
  stop gate, а не разрешением механически уплотнить проверки.
- Exact paths достаточны: application owner, HTTP DTO/route, static performer
  detail и четыре test files. Изменения
  `infrastructure/db/assignments.py` или `database.py` не требуются, потому
  что dispute/case persistence, receipt adapter, test-scope guard и outbox уже
  существуют.
- Новые schema, migration, table, model, repository, service, framework,
  dependency или ADR не нужны.

## Findings по дизайну (`design_findings`)

Обязательных замечаний нет.

1. **Concurrent exact replay закрыт существующим gate.** Для web path amended
   application step задаёт точный порядок: разрешить active actor → взять
   transaction-scoped
   `acquire_task_identity_gate(actor.telegram_user_id)` → под gate вызвать
   receipt `_begin()`. Поэтому конкурирующие запросы одного actor не читают
   отсутствие receipt одновременно. Telegram-compatible early replay/order не
   меняется. До возврата stored outcome обязательны active actor, performer
   ownership, current `ensure_task_test_access()` и fingerprint checks.
   Это переиспользует уже существующий gated web pattern из
   `_submission_start()`/`TaskService.publish()`, без нового helper.
2. **HTTP contracts стали точными.** Missing, empty и whitespace-only
   `comment` нормализуются на DTO boundary и дают
   `422 {"code":"invalid_request"}` до application owner. Все
   foreign/hidden/closed/expired/already-disputed/conflict mutations дают
   `409 {"code":"assignment_unavailable"}`; performer detail GET сохраняет
   отдельный `404 {"code":"not_found"}`. Исполнителю не оставлен выбор между
   `404/409`.
3. **Domain ownership сохранён.** `can_dispute` вычисляется server-side через
   existing application/domain owner; status и полуоткрытое 24h-окно остаются
   только в `require_dispute_allowed()`. Frontend использует bool вместе с
   existing status/case/deadline и не сравнивает deadline самостоятельно.
4. **Effect/privacy boundary сохранена.** Existing
   `AssignmentService.dispute()`/`open_assignment_dispute()` остаются
   единственным owner для одного dispute, одного moderation case, перехода
   `DISPUTED`, privacy-minimal outbox и receipt. Opening не получает новых
   ledger, reliability или audit effects; private comment не входит в DTO,
   response или outbox.

## Findings по проверке (`verification_findings`)

Обязательных замечаний нет.

- Concurrent exact pair имеет точный oracle `204/204`; concurrent
  same-key/different-comment pair — один `204` и один `409`.
- Для sequential replay и обеих concurrent веток проверяются итоговые counts
  `1 dispute + 1 case + 1 outbox + 1 receipt`, отсутствие duplicate effects и
  нулевые opening deltas ledger/reliability/audit.
- Missing/empty/whitespace-only comment проверяются на точный `422` и zero
  receipt/domain/outbox effects; foreign/test-run-hidden mutation — на точный
  `409 assignment_unavailable`.
- Exact replay после смены active test-run scope повторно проверяет active actor,
  ownership и current scope до stored outcome и не создаёт эффектов.
- Web/browser oracles совместно закрывают deadline boundary, expired, opened,
  terminal `404/not active`, foreign, hidden и conflict; private comment
  проверяется denylist-оракулами.
- Existing dispute→resolution scenario получает точный audit oracle по
  `action`, `entity_type`, `entity_id`, count и replay invariance, не
  добавляя нового runtime effect.

## Обязательные действия (`required_actions`)

Нет. Все обязательные действия предыдущего verdict закрыты amended plan.

## Остаточные риски (`residual_risks`)

- Concurrent ordering, transaction-local effect counts и exact HTTP responses
  остаются доказательствами будущей реализации; в этом read-only plan review
  тесты по условию не запускались.
- Реализация должна сохранить gate до receipt read именно для web path и не
  ослабить replay checks после обнаружения stored outcome.
- Любое сравнение dispute deadline в `web.py` или `app.js`, private comment
  в response/outbox/browser fixture либо выход за `7 files / 400 additions`
  активирует уже записанный stop gate и требует остановки.

Ponytail full: amended plan использует существующие domain, gate, receipt,
request/retry и detail seams; новая архитектура не нужна. Минимальная
реализация и минимальные исполняемые проверки описаны достаточно точно.
