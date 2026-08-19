# CB-81 — post-escalation независимое ревью плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники

- Jira `CB-81` повторно прочитана read-only через Atlassian Rovo, cloud `c5d6d202-cdba-4d4e-88be-a3f927b6fc5b`; task scope, exclusions и delivery gate подтверждены. Owner decision сверена с полным локальным package: `plan.md`, `plan-source-context.md` и `problem-escalation.md`.
- Полностью прочитаны `tasks/CB-81/reviews/plan/{attempt-01.md,attempt-02.md}`, текущий `plan-review.md` до перезаписи и post-escalation policy из `agents/workflow.yaml#/review_retry_policy`.
- Сверена фактическая база `7981d5b222843c9e8eda219b0244be2077f55635`, равная `origin/main`: `RegistrationService`/UoW, receipt, locks, DB profile setter, `web.py`, existing profile UI и четыре named test modules.

## Замечания по области

Обязательных замечаний нет.

- Новый one-shot command изолирован от `conversation_states`: existing staged Telegram methods не меняются, а reusable `_set_member_profile_field` устанавливает только выбранную ORM column (`src/community_bot/infrastructure/db/registration.py:580-590`). Это закрывает P1 attempt-01 о потере active text flow.
- План остаётся в минимальной области: пять existing production files, никаких новых files, dependencies, schema, migration, domain rule, repository или service. Новый ADR не нужен, потому что structural/integration boundary не меняется.

## Замечания по логике решения

Обязательных замечаний нет.

- Existing `acquire_update_gate`, durable `outcome_code` receipt, `get_member`, registration identity gate, `lock_members`, audit и commit покрывают one-shot command (`src/community_bot/infrastructure/db/database.py:277-289`, `:964-990`, `:1173-1181`, `:1291-1307`, `:1366-1454`).
- Typed marker `web_profile_update:<actor>:<field>:<fingerprint>` реализуем в existing receipt без schema change; current `_web_draft_replay` уже доказывает этот marker/fingerprint pattern (`src/community_bot/application/tasks.py:2234-2244`). Exact replay and mismatch conflict сформулированы до mutation.
- Identity gate по persisted Telegram identity и member lock serialise concurrent distinct update IDs одного actor; single-field setter не перезаписывает другие fields. Fresh `registration.own_profile(actor)` after commit — корректный authoritative reread (`src/community_bot/application/registration.py:778-799`).
- Telegram path сохраняет public signatures/outcomes `profile_edit:<field>` и `profile_updated`; plan требует их exact compatibility oracle.

## Замечания по стратегии проверки

Обязательных замечаний нет.

- Named tests закрывают owner, invalid input, exact replay, mismatched key/marker, audit/receipt cardinality, unchanged foreign conversation, concurrent different-field updates, Telegram compatibility, browser retry/focus/safe DOM и closed route set.
- Consolidated fix честно перечисляет четыре existing test modules: `test_web_api.py`, `test_mini_app.py`, `test_registration.py`, `test_web_auth.py`. Owner trigger `>5` применяется отдельно к production и test categories; фактические 5 и 4 соответственно в предел не выходят. Отказ от искусственного объединения разных test scopes соответствует Ponytail.

## Обязательные исправления

Нет.

## Остаточные риски

- План допускает implementation только внутри описанного stop gate: выход за пять files в любой категории, около 300 net production LOC, новая persistence/schema/domain mechanism или невозможность exact typed replay требует остановки и owner decision.
- Approval относится к плану и current source contracts. До завершения остаются implementation, targeted verification, independent final review, PR/CI/merge и delivery gate ADR-0019 с public smoke.
