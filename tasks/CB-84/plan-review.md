# CB-84 — независимая проверка плана

`community_bot.plan_review.verdict.v1`

Status: approved

## reviewed_sources

- `tasks/CB-84/plan-source-context.md` и `tasks/CB-84/plan.md`.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` (§4.8), `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md` (D-032), `docs/adr/0017-lean-community-mini-app-core.md`.
- `src/community_bot/application/assignments.py:775`, `src/community_bot/transport/web.py:848`, `src/community_bot/transport/static/app.js:736`, `tests/unit/test_web_auth.py:252` и существующие integration/browser oracles.
- Live Jira read attempted read-only; connector returned `403 app not installed`, поэтому использован переданный локальный Jira snapshot.

## scope_findings

- Область соответствует частому завершённому сценарию MVP: участник может отказаться от принятого задания.
- План ограничен тремя существующими production-файлами и одной секцией текущей карточки; новые domain rules, schema, migration, model, repository, service, dependency, framework, generic UI abstraction и второй экран исключены.
- Templates/community publication и CB-76—CB-80 вместе с appeals, sanctions, alerts, pagination и косметикой явно вне области.

## design_findings

- Backend owner доказан: `AssignmentService.cancel` нормализует причину, проверяет owner и `accepted`, выполняет cancellation, slot/task/economy/outbox/receipt effects и commit в одной UoW.
- Actor-native ветка не вводит новый owner: в модуле уже есть fresh active member resolution и exact Web receipt/replay patterns.
- POST contract повторяет существующую закрытую Web boundary: origin → session actor → idempotency key → canonical UUID → bounded JSON → allowlisted error.
- UI использует текущую detail-карточку и существующий `submissionRequest`/204 handling. Ponytail: `Lean already. Ship.`

## verification_findings

- One-line route allowlist защищает закрытый набор ресурсов.
- Один integration API/domain oracle достаточен, если он доказывает persisted `cancelled`, один effect при exact replay и закрытый конфликт при несовпадающих reason/actor/assignment, не дублируя уже покрытые правила движка.
- Один Playwright happy path достаточен для формы на `accepted` detail, отправки причины и возврата через `loadAssignments(false)`.
- До runtime diff выполнены read-only source trace и `git diff --check` планового пакета.

## required_actions

- Нет.

## residual_risks

- На final review измерить production diff против ceiling и проверить сохранность Telegram call contract/receipt.
- Integration oracle должен считать persisted side effects, а не ограничиваться HTTP `204`.
