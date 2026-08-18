# CB-70 — исходный контекст плана

## Точный baseline

- `origin/main`: `49e8a7a360f1f8f8d5e5c5a5d827c17511ba6a05`.
- Jira: `CB-70`, эпик `CB-48`, статус планирования — «В работе».

## Обязательные источники

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Mini App-only, Jira gates,
  server-side authority, test-run isolation и Ponytail.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md` — Level 3 plan/review и
  post-task delivery.
- `docs/adr/0017-lean-community-mini-app-core.md` — durable owner/revision/
  restart/resume/exact-confirm semantics без восстановления старого UI.
- `docs/adr/0019-single-pilot-post-task-delivery-gate.md` — exact release,
  текущий activator и public smoke после merge.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` — активный участник создаёт задание без
  шаблона; task creation входит в основной пользовательский цикл.
- `docs/mvp/02_DOMAIN_RULES.md` — reserve, solo/group, reward, публикация,
  test-run и community-task инварианты.
- `src/community_bot/application/tasks.py` — существующие `TaskService.start`,
  `advance`, `preview`, `publish`, `TaskDraft`, `TaskPreview` и validators.
- `src/community_bot/infrastructure/db/tasks.py`, `database.py`, `models.py` —
  существующий durable `task_creation_drafts`, current-draft, receipt, ledger,
  audit и publish owners; новая persistence schema не нужна.
- `src/community_bot/domain/tasks.py`, `domain/catalog.py` — конечный free-form
  step/value contract и limits.
- `src/community_bot/transport/web.py`, `transport/static/app.js` — текущие
  session/Origin/bounded body/idempotency/static client boundaries.
- `tests/integration/test_task_creation.py` — уже принятые restart, revision,
  reserve, publish и replay invariants.

## Сужение

Первый web slice создаёт только member-owned free-form task:
`template_id is None`, `origin=member`, с существующими solo/group ветками.
Template и admin community-task flows остаются в backend и fail closed на этих
routes. Это не generic form/schema renderer и не второй task engine.

CB-69 владеет общими `web.py`/static assets до merge. До этого CB-70 меняет
только плановый пакет; runtime ownership не пересекается.
