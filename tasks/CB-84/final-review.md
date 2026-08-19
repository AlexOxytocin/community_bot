# CB-84 — независимое финальное ревью

`community_bot.final_review.verdict.v1`

Status: approved

## reviewed_scope

- Процесс: уровень 2 по ADR-0004; новая product/runtime mutation поверх
  существующего owner, не fast lane `1B`.
- Baseline и ветка: `task/CB-84`; `HEAD`, `origin/main` и merge-base до diff —
  `ae42e5477998b67cc46b02187fe5807af35a6b17`.
- Проверены Jira snapshot, plan package, implementation report, фактический diff
  шести runtime/test файлов, legacy Telegram contract, actor-native Web path,
  exact replay, UI navigation и независимые проверки.
- Production diff: три существующих файла, `+166/-5`, net `+161`. Новые domain
  rules, schema, migration, model, repository, service, dependency, framework,
  generic UI abstraction и второй экран отсутствуют. Templates/community
  publication, CB-76—CB-80, appeals, sanctions, alerts, pagination и rare admin
  edge cases не затронуты.

## critical_findings

- Нет.

## major_findings

- Нет.

## minor_findings

- Нет.

## acceptance_matrix_result

- Existing owner сохранён: Web transport передаёт session-owned
  `actor_member_id`, assignment и нормализованную причину в
  `AssignmentService.cancel`; ownership, `accepted` status, cancellation,
  slot/task/economy/outbox/receipt effects остаются внутри прежней UoW.
- Active actor и test scope проверяются заново. Fresh actor-native path вызывает
  `ensure_task_test_access` до эффекта; exact-replay helper вызывает ту же
  проверку до возврата. Integration oracle доказывает direct-UUID denial вне
  scope без cancellation/receipt/outbox, success внутри active scope и denial
  replay после деактивации participant.
- Legacy Telegram call/receipt сохранён: ветка без `actor_member_id` продолжает
  разрешать actor по `actor_telegram_user_id`, записывает прежний outcome
  `assignment:<id>` и воспроизводится через `_assignment_replay`.
- Exact Web replay связывает update identity с actor, assignment, operation и
  operation key; receipt дополнительно хранит actor/assignment и fingerprint
  уже нормализованной причины. Exact replay возвращает `204`, тот же key с иной
  причиной закрывается `409`, persistent cancellation effect остаётся один.
- Trust boundary закрыта существующими primitives: same-origin, Web session,
  обязательный decimal idempotency key, canonical UUID, JSON body до `4096`
  bytes, `extra="forbid"`, stripped reason `1..1000` и public error allowlist.
- UI показывает одну форму только для `accepted`, сохраняет operation key после
  retryable failure, после `204` заменяет terminal history entry на
  `{screen: "assignments"}` / `#assignments` и загружает актуальный active list.
- Route присутствует в закрытом allowlist. Jira snapshot фиксирует status,
  exact acceptance, parent, отсутствие dependencies и `updated_at`; его scope
  совпадает с plan и diff.

## test_matrix_result

- Независимый targeted gate:
  `test_web_config_and_route_set_are_closed`,
  `test_catalog_detail_projection_accept_and_cancel_path`,
  `test_assignment_cancellation_returns_to_active_list` — `3 passed`.
- Независимый combined application/API gate:
  `tests/integration/test_assignments.py`,
  `tests/integration/test_web_api.py`,
  `tests/unit/test_web_auth.py` с `--no-cov` — `49 passed`.
- Targeted oracle исполняет API/domain negative и exact-replay checks, а
  Playwright happy path проверяет request payload, single operation key,
  актуальный список, URL и `history.state`.
- `ruff format --check`, `ruff check`, `ty check`, `node --check` и
  `git diff --check ae42e547` — green.
- Secret-pattern scan added diff и всех `tasks/CB-84` artifacts — `PASS`.
- Заявленный coverage-run исполнил все `49` selected tests; общий coverage
  выбранного поднабора `54.13%` ниже project-wide threshold по ожидаемой причине
  неполного набора. Это не заменяет full-suite CI, но owner coverage
  `assignments.py 71%` и `web.py 91%` вместе с исполненными targeted oracles
  достаточны для локального level-2 gate.

## security_and_secret_result

- Actor identity не принимается от клиента; fresh active-member resolution,
  ownership, status и test-scope checks находятся в application boundary.
- Предыдущий test-scope authorization bypass закрыт и защищён negative oracle
  как на fresh, так и на exact-replay path.
- Public responses не раскрывают application/domain errors; cancellation reason
  не попадает в response и не добавляет нового logging path.
- Секреты, Telegram session data, private identifiers и credentials не найдены.
  Реальных Telegram отправок и внешних mutation reviewer не выполнял.

## workflow_result

- Jira-first, ветка `task/CB-84`, baseline, risk tier, plan, approved plan
  review, Jira snapshot, implementation report, language gate, ceiling и
  независимые локальные проверки подтверждены.
- Scope ограничен одним existing-service exposure и одной формой текущего UI;
  несвязанных или сгенерированных runtime изменений и Jira key в исполняемых
  именах нет.
- Локальный gate допускает commit/push/PR/CI/merge. Immutable release,
  production activation, public smoke и Jira `Done` остаются обязательными
  последующими gates и этим verdict не объявляются выполненными.

## required_actions

- Нет.

## residual_risks

- Reviewer проверил локальный snapshot Jira с `updated_at`
  `2026-08-19T01:13:07.445-0300`, но не выполнял отдельный повторный live-read;
  внешний drift после этого timestamp остаётся возможным до PR/merge handoff.
- Project-wide `80%` coverage не доказывается selected-files прогоном; этот gate
  остаётся за полным CI. Локально все требуемые targeted и combined tests green.
- Release artifact, production activation и public smoke возможны только после
  merge и остаются residual delivery risk до отдельного подтверждения.

## ponytail-review

Lean already. Ship.

Ponytail-only проход не нашёл удаляемой сложности (`net: -0 lines possible`).
