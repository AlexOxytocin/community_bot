# CB-64 — терминальное независимое ревью плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- Полностью перечитаны актуальные `tasks/CB-64/plan-source-context.md`,
  `tasks/CB-64/plan.md`, `tasks/CB-64/parity-map.json`, предыдущий terminal
  verdict и proposed ADR-0017.
- Сверены Jira snapshot и проверенная Jira-сводка предыдущего review,
  baseline `019850ce05e5e98c23c566dc491fee473892b33f`, фактические SQLAlchemy
  tables, application semantics durable drafts и текущий worktree diff.
- Live Jira read в предыдущем проходе был недоступен из-за `403: The app is
  not installed on this instance`; этот review не выдаёт snapshot за свежую
  внешнюю проверку и не изменяет Jira.
- ADR-0017 корректно остаётся `Предложено`; принять его до реализации может
  только владелец.

## Замечания по области (`scope_findings`)

Обязательных замечаний нет.

Последний semantic blocker закрыт полностью:

- `task_creation_drafts` связан с отдельным `TASK_CREATION_DRAFT`, C11 и exact
  planned node; oracle явно проверяет owner/payload/revision после restart,
  foreign/stale/cancelled zero effects и единственный publish/reserve effect
  при concurrent/exact replay;
- `assignment_submission_drafts` связан с `SUBMISSION_DRAFT`, C11 и exact
  planned node; oracle проверяет performer ownership, revision, restart,
  foreign/stale zero effects и один immutable result/confirmed target;
- `moderation_decision_drafts` связан с `MODERATION_DRAFT`, C11 и exact planned
  node; oracle проверяет actor/case/revision, restart, foreign/stale zero
  effects и один полный resolution effect set;
- C11 задаёт constrained owner/subject/revision/status/confirmed target,
  locked compare-and-swap и unique exact confirmation для трёх target owners.

Это уже не формальная связь с общим import oracle: каждый старый draft contract
имеет собственные old evidence, new owner, constraint, planned scenario и
проверяемый outcome.

## Замечания по дизайну (`design_findings`)

Обязательных замечаний нет.

- Полный функциональный parity имеет приоритет над schema/LOC/test ceilings;
  недоказанный constraint поднимает ceiling, а не урезает функцию.
- Historical/shared data защищены read-only inventory, encrypted backup,
  isolated restore, separate compact database, deterministic importer и
  явной границей первой реальной mutation.
- C01—C11 покрывают ledger, audit, idempotency, history, privacy, outbox lease,
  config activation, concurrency и durable drafts без нового generic
  repository, broker или schema framework.
- CB-51—CB-57 сохраняют последовательные precondition/gate/stop/rollback и не
  начинают runtime до принятия ADR-0017 владельцем.

Ponytail-only result: `Lean already. Ship.`

## Замечания по проверке (`verification_findings`)

Независимо воспроизведено:

- `TABLES=43`, `LINKS=43`, `CAPS=26`, `CONSTRAINTS=11`;
- `TABLE_DIFF=0`, `BAD_CAP=0`, `BAD_CON=0`, duplicate capability/planned IDs
  `=0`;
- все `old_evidence` paths, pytest node IDs и class method symbols разрешаются:
  `OLD_EVIDENCE_MISSING=0`;
- три exact legacy evidence nodes, включая restore evidence: `3 passed`;
- `tests/architecture` и `tests/documentation`: `22 passed`;
- `git diff --check` проходит.

## Обязательные исправления (`required_actions`)

Нет.

## Остаточные риски (`residual_risks`)

- Фактическое содержимое production DB остаётся неизвестным до запланированного
  read-only inventory. План корректно делает недоступность, неоднозначный head,
  невосстановимый backup или import divergence условием `stop`.
- Live Jira state в этом проходе не подтверждён из-за недоступного Atlassian
  connector; approval относится к полному локальному пакету и сохранённому Jira
  snapshot, а не к возможным внешним изменениям после snapshot.
- Approval разрешает передачу ADR владельцу, но не принимает ADR и не начинает
  CB-51/runtime migration автоматически.
