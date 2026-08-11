# CB-22 — независимое ревью плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-22`, свежо прочитанная через Atlassian Rovo JQL API 11 августа
  2026 года: контекст дефекта, семь критериев приёмки, статус `В работе`, labels,
  комментарий и связи с `CB-16`/`CB-2`.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md` и правила plan/final review уровня 3.
- Актуальные `tasks/CB-22/plan-source-context.md`, `plan.md`, `test-plan.md`.
- Утверждённый `tasks/CB-16/plan.md`, фактический
  `tasks/CB-16/final-review.md` с M-001–M-003 и соответствующие разделы
  `implementation-report.md`, `PILOT_RUNBOOK.md`, `PILOT_CHECKLIST.md`,
  `PILOT_RETROSPECTIVE.md`.
- Фактические `application/pilot.py`, PostgreSQL pilot adapter,
  `KarmaVoteModel`/`KarmaVoteHistoryModel`, текущие unit/integration metrics
  tests на frozen base `c8bc6d8e04af509a8b9892670f4258db45923816`.

Jira, код, Git index/remote и внешнее состояние не изменялись.

## scope_findings

- CB-22 точно соответствует regression Bug: исправляет public JSON names,
  immutable karma activity и завышенную evidence matrix, не меняя формулы,
  Telegram flows, ledger или схему БД.
- Сохранение `community_bot.pilot_metrics.v1` корректно: исправляется ещё не
  опубликованная реализация уже утверждённого v1-контракта, а не вводится новый
  внешний формат.
- Representative migration oracle обоснованно остаётся CB-23. Дублировать его,
  новый ADR или полную регрессию в CB-22 не требуется.

## design_findings

- Public DTO получает exact approved rate keys:
  `invite_conversion_rate`, `onboarding_completion_rate`, `task_fill_rate`,
  `task_fill_rate_48h`, `assignment_completion_rate`, `repeat_action_rate`,
  `weekly_retention_rate`. Nested success thresholds используют те же три
  согласованных имена, поэтому runbook/checklist и runtime снова имеют один
  машинно-проверяемый contract.
- Retention source выбран правильно: каждая строка immutable
  `karma_vote_history` даёт `(actor_member_id, created_at)` при
  `created_at < to_at`. Mutable current `karma_votes.updated_at` больше не
  стирает факт предыдущей mutation; новая таблица или миграция не нужны.
- Остальные формулы и privacy boundary сохраняются. Переименование DTO не
  меняет numerator/denominator, а adapter читает только actor UUID и event time,
  не извлекая karma value/comment или participant-shaped output.

## verification_findings

- Exact `model_dump()` oracle проверяет полный верхнеуровневый key set и
  отсутствие старых сокращённых rate names; отдельный assertion связывает
  success booleans с `task_fill_rate`, `assignment_completion_rate` и
  `repeat_action_rate`.
- PostgreSQL case «create в предыдущей неделе → revision в текущей» напрямую
  доказывает две history rows и retention `1/1`, закрывая дефект adapter, а не
  только чистую функцию.
- Targeted matrix закрывает все заявленные M-003 разрывы: positive partial,
  исключение reversed/rejected reward, deterministic multi-performer top tie,
  невозможный safe merge с suppression, community published/paid/credits и
  единый representative A–D report dataset.
- Privacy/docs case проверяет отсутствие member/Telegram/private text и exact
  contract в runbook/checklist/retrospective. Implementation report должен
  перечислить только реально выполненные assertions, что прямо закрывает Jira
  AC о доказательности.
- Targeted unit/PostgreSQL pytest, Ruff, ty, build и diff-check соразмерны этому
  локальному read-only исправлению. Повтор полного `pytest`/регрессии не нужен и
  план его не требует.

## required_actions

Обязательных исправлений нет.

## residual_risks

- CB-16 останется незавершённой до отдельного CB-23 и повторного final review;
  план CB-22 честно не выдаёт исправление метрик за закрытие migration finding.
- Любое будущее опубликованное изменение ключей после пилота потребует новой
  schema version; текущий fix остаётся внутри ещё не опубликованного v1.
