# CB-23 — независимое повторное ревью плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-23`, повторно прочитанная через Atlassian Rovo JQL API 11 августа
  2026 года: шесть критериев приёмки, статус `В работе`, labels, комментарий и
  связи с `CB-16`/`CB-2`; требования не изменились.
- Актуальные `tasks/CB-23/plan-source-context.md`, `plan.md`, `test-plan.md`.
- Ранее проверенные project workflow/rules, `tasks/CB-16/plan.md`,
  `test-plan.md`, `final-review.md`, migrations `0007`–`0010`, SQLAlchemy
  models и `tests/integration/test_pilot_readiness.py` на базе
  `9f6f197ea26f069401911d3067622374a6d0f203`.

Jira, код, Git index/remote и внешнее состояние не изменялись.

## scope_findings

- Область остаётся строгим MVP bug-fix: меняются fixture/oracle и связанные
  отчётные артефакты, но не production migration, runtime или schema.
- Direct SQL на exact revision `0009`, отдельная PostgreSQL DB и cleanup в
  `finally` дают независимое доказательство поддерживаемой схемы без зависимости
  от ORM `0010` и порядка suite.
- Существующие outbox backfill, operational guards и повтор `upgrade head` не
  ослаблены. Полная регрессия для локального migration-test fix не требуется.

## design_findings

- Единственный P-001 закрыт. Reputation и moderation теперь представлены двумя
  реальными независимыми цепочками schema `0009`:
  `karma_votes → karma_vote_history` и
  `assignment → moderation_cases → dispute_resolutions`.
- Moderation fixture исполним при циклических FK: сначала вставляется
  `moderation_cases(case_type=fraud_review,current_resolution_id=NULL)`, затем
  immutable resolution version 1, после чего current case получает exact
  `current_resolution_id`, `status=resolved`, `revision=1` и фиксированный
  `resolved_at`. Несуществующий karma case/`moderation_case_history` больше не
  используется.
- Два members, reserve/reward ledger, published task, accepted assignment,
  result, две karma revisions, moderation current/history и две legacy outbox
  rows образуют минимальную, но достаточную representative chain. Все UUID,
  deltas, keys, revisions, payload и timestamps фиксируются manifest, поэтому
  oracle не сводится к одним counts.

## verification_findings

- Exact FK oracle проверяет ledger → member/task/assignment, assignment →
  task/member, history → vote/actor, case → assignment/opener/current resolution
  и resolution → ту же case/actor. Отдельное равенство case IDs закрывает то,
  чего один FK `current_resolution_id` сам по себе не гарантирует.
- После `0010` counts, identities, values, business/idempotency keys и времена
  сверяются с manifest; это прямо закрывает первые два Jira AC и M-004 CB-16.
- Published/unpublished outbox сохраняют прежние payload/business key/timestamps
  и получают `materialized`/`pending`; constraints/indexes и invalid states
  остаются в том же тесте.
- Второй `upgrade head` повторяет полный oracle, а отдельная DB и `finally`
  доказывают независимость suite. Implementation report ограничен фактическими
  assertions.
- Один targeted PostgreSQL migration test, Ruff, ty и diff-check полностью
  покрывают область CB-23; full `pytest`/регрессия обоснованно не запускаются.

## required_actions

Обязательных исправлений нет.

## residual_risks

- Fixture намеренно привязан к exact supported revision `0009`; при смене
  поддерживаемой исходной схемы manifest/oracle потребуется явное обновление.
- Representative preservation test не заменяет доменную регрессию, но для
  дефекта CB-23 это правильная и достаточная граница.
