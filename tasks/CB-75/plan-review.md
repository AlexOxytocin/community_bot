# CB-75 — независимая повторная проверка плана

Schema: `community_bot.plan_review.verdict.v1`  
Status: `approved`

## Reviewed sources

- актуальные Jira `CB-75`, `CB-73`, `CB-74` через Atlassian Rovo MCP без
  изменений;
- `tasks/CB-75/plan.md`, `tasks/CB-75/plan-source-context.md` и предыдущий
  `changes_requested` verdict;
- канонические product/domain/data документы, D-015, D-018, D-023, D-030,
  D-033, ADR-0004, ADR-0013, ADR-0017, ADR-0019 и
  `docs/release-2/README.md`;
- фактические owners moderation domain/application/storage, `active_scope`,
  outbox recipients, web/static transport и существующие unit/integration/browser
  tests, перечисленные в source context.

## Scope findings

- Обязательное замечание по test-run outbox закрыто: план больше не приписывает
  текущему `moderation_case` branch отсутствующее правило, включает точечный
  reuse `participant_ids` в существующем owner и negative oracle для active
  бывшего участника (`plan.md:119-126`, `:182-187`, `:214-216`).
- Privacy-контракт `result_summary` теперь точный и минимальный: разрешена только
  nullable allowlisted projection CB-73 после fresh remap; произвольный
  `AssignmentResultVersionModel.payload_json` закрыт (`plan.md:63-67`,
  `:105-109`).
- Матрица member/community resolution codes, роли, конфликт интересов,
  initial-only scope, ledger/reliability/risk/audit/outbox effects и
  payload-bound exact replay/conflict соответствуют фактическим owners.

## Design findings

- Новый ADR не нужен: задача сохраняет существующие domain/application owners,
  PostgreSQL transaction boundary, test-run policy, native Mini App и delivery
  gate.
- Stop conditions корректно блокируют runtime при отсутствии общего HTTP
  operation-identity owner, safe projection, test-run isolation либо при
  overlap после CB-73/CB-74.
- Ponytail review: `Lean already. Ship.` Новых schema, migration, dependency,
  service, repository, framework или дублирующих правил не запланировано.

## Verification findings

- Предыдущее смешение разных oracles устранено. Один compact web/PostgreSQL
  scenario доказывает detail/mutation/effects/replay/scope; существующие
  moderation rollback и concurrency scenarios не дублируются; текущий
  `tests/browser/test_mini_app.py` отдельно владеет confirmation/409/focus/
  keyboard/back (`plan.md:201-224`).
- Source context теперь ссылается на существующие D-030/D-033 и точно разделяет
  coverage owners для applicability, fraud, effects, rollback, concurrency и UI
  (`plan-source-context.md:34-36`, `:89-95`).
- `git diff --check` прошёл. Runtime и test suites не запускались: текущий этап
  явно planning-only.

## Required actions

Обязательных исправлений нет. Плановый пакет допущен к terminal state
`approved plan / runtime blocked by CB-73 and CB-74`.

## Residual risks

- Jira refresh показал `CB-73 = На проверке` вместо исторического снимка
  `В работе`; `CB-75 = К выполнению`, `CB-74 = К выполнению`, resolution у
  зависимостей отсутствует. Это не ослабляет gate: до production completion
  обеих задач runtime CB-75 запрещён.
- После completion зависимостей обязателен предусмотренный планом fresh
  `origin/main` remap operation identity, safe result projection, shared
  web/static seams, `active_scope`, recipients и эффектов. Изменение owner
  возвращает план на обновление до ветки или runtime diff.
- Внешнее состояние, runtime, тесты, Git и Jira не изменялись.
