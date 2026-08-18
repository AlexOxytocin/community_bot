# CB-75 — независимая fresh-remap проверка плана

Schema: `community_bot.plan_review.verdict.v1`  
Status: `approved`

## Reviewed sources

- актуальные Jira `CB-75`, `CB-73`, `CB-74` через Atlassian Rovo MCP без
  изменений: `CB-73` и `CB-74` имеют status/resolution `Готово`, `CB-75`
  остаётся `К выполнению`;
- `tasks/CB-75/plan.md` и `tasks/CB-75/plan-source-context.md`;
- точный `origin/main` и `HEAD`
  `a62ed11c9f1f0fa98b0d42f440aa591cac9a4059`, включая фактические изменения
  CB-73 и CB-74;
- фактические owners в `application/assignments.py`,
  `infrastructure/db/assignments.py`, `infrastructure/db/moderation.py`,
  `infrastructure/outbox/postgres.py`, `transport/web.py`,
  `transport/static/app.js` и релевантные unit/integration/browser tests.

## Scope findings

- Fresh dependency gate закрыт: CB-73/CB-74 завершены, task branch находится на
  точном актуальном `origin/main`.
- Route inventory точен: сейчас moderation transport имеет только
  `GET /api/v1/moderation/cases`; план добавляет ровно два route — detail и
  resolution mutation — и обновляет закрытый inventory test.
- `active_scope` для queue/detail/mutation и existing `participant_ids` для
  test-run outbox recipients зафиксированы в правильных существующих owners.
- Nullable `result_summary` ограничен существующей allowlisted assignment-card
  projection CB-73; чтение или сериализация произвольного
  `AssignmentResultVersionModel.payload_json` запрещены.
- `app.js` переиспользует существующие moderation card, native history/focus/
  back и idempotency helpers; новых router/state/CSS owners не запланировано.

## Design findings

- Receipt scope приведён к native owner CB-74. Исправленный `plan.md:136-143`
  задаёт identity как namespace + command + actor + case ID + external key,
  проверяет payload conflict только для того же case и явно фиксирует, что тот
  же внешний key на другом case образует отдельную resource-scoped identity.
  Это соответствует `_submission_update_id` (`transport/web.py:1088-1104`),
  `_submission_fingerprint` (`transport/web.py:1107-1115`) и same-resource
  replay/conflict oracle CB-74 (`tests/integration/test_web_api.py:1242-1262`).
- Actor-native ordering остальной части плана подтверждён: web actor загружается
  и проверяется до receipt lookup, identity gate сериализует actor scope, а
  stored replay marker сверяет actor и canonical payload fingerprint.
- Новый ADR не нужен. Ponytail verdict:
  `Lean already. Ship.` Source ceiling остаётся пять production owners и три
  существующих test owners; новые schema/migration/dependency/service/
  repository/framework не нужны.

## Verification findings

- Compact web/PostgreSQL scenario, существующие moderation rollback/concurrency
  tests и отдельный browser UI oracle распределены без смешения ответственности.
- План покрывает exact replay, payload conflict, stale revision, rollback,
  один concurrency winner, private reason, conflict-of-interest, test-run
  isolation и отсутствие duplicate ledger/reliability/risk/audit/outbox effects.
- `git diff --check` прошёл. Runtime/test suites не запускались: это
  pre-runtime review.

## Required actions

Обязательных исправлений нет. Fresh-remapped план допущен к runtime stage.

## Residual risks

- Safe result projection сейчас принадлежит private assignment-card query;
  реализация должна переиспользовать её без копирования payload rules. Если это
  потребует нового owner или шестого production файла, сработает зафиксированный
  source-ceiling stop condition.
- Внешнее состояние, runtime, tests, Git и Jira в ходе review не изменялись.
