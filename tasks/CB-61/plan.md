# CB-61 — план реализации

## Цель

Сохранить полноценную многопоточную разработку, но убрать повторную загрузку
нерелевантной документации, неограниченные управляющие циклы и наследование
Sol/xhigh всеми ролями.

## Решение владельца после эскалации

Владелец 2026-08-16 явно решил: **глобальные бюджеты канонические**. Поэтому
execution budgets не копируются в репозиторий. Граница источников следующая:

- `codex.agent-budget.v1` в пользовательском Codex home — единственный
  исполняемый источник моделей, reasoning effort, concurrency, follow-up,
  polling, model-call/time checkpoints, progress extension и fresh-context
  handoff;
- `community_bot.orchestration.v2` в `agents/config.yaml` — единственный
  репозиторный источник document routing, карты project role → global profile,
  project review/process limits, packet и tool-output budgets;
- task plan хранит проверенное историческое решение, но не читается runtime.

Решение и точная цитата зафиксированы в `tasks/CB-61/owner-decision.md`.

## Область изменений

### Глобальная политика Codex

- `C:/Users/User/.codex/policies/agent-budget.yaml` — новый канонический
  `codex.agent-budget.v1`;
- `C:/Users/User/.codex/AGENTS.md` — ссылка на policy без числовых копий;
- четыре `C:/Users/User/.codex/agents/{luna-explorer,luna-worker,sol-developer,sol-reviewer}.toml`
  — ссылки на профиль policy без checkpoint/hard-limit копий;
- `C:/Users/User/.codex/tools/Get-CodexTokenAudit.ps1` — проверка согласованности
  policy, `config.toml`, AGENTS и профилей.

### Репозиторий Community Bot

- `AGENTS.md` — always-read ядро и условная таблица документов;
- `agents/config.yaml` — `community_bot.orchestration.v2`;
- `agents/workflow.yaml` — ссылки на центральные project/global policy keys;
- `agents/README.md` и четыре `agents/*/instruction.md` — compact packets и
  ссылки без числовых копий;
- `docs/AGENT_CONTEXT_AND_COST_POLICY.md`;
- `docs/AGENT_WORKFLOW.md` и `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`;
- ADR-0015 и индекс ADR;
- `tests/architecture/test_agent_orchestration_policy.py`;
- артефакты CB-61.

## Вне области изменений

- продуктовая логика, БД, Telegram runtime и deployment;
- рабочие файлы и ветки CB-49/50/58/59/60;
- выбранные пользователем числовые бюджеты: задача меняет место хранения и
  проверку, но не повышает их.

## Контракт глобальной политики

`agent-budget.yaml` содержит schema/policy id, defaults, profiles,
coordination, continuation, weekly-plan checkpoint и список consumers. Все
числовые поля имеют `{value, unit, min, max}`. Начальные значения:

| Ключ | Value | Unit | Bounds |
|---|---:|---|---|
| `coordination.max_child_agents` | 3 | `agents` | 1…3 |
| `coordination.max_total_threads_including_root` | 4 | `threads` | 2…4 |
| `coordination.max_followups_per_child` | 2 | `messages` | 0…2 |
| `coordination.max_unchanged_state_checks` | 4 | `checks` | 1…4 |
| `coordination.min_state_check_interval` | 300 | `seconds` | 60…3600 |
| `continuation.max_auto_extensions` | 1 | `extensions` | 0…1 |
| `continuation.max_fresh_context_handoffs` | 1 | `handoffs` | 0…1 |
| `weekly_plan.checkpoint_delta` | 2 | `percentage_points` | 1…2 |

| Профиль | Model/effort/mode | Checkpoint calls | Hard calls | Hard minutes |
|---|---|---:|---:|---:|
| `luna_explorer` | Luna/medium/read-only | 40 | 80 | 45 |
| `luna_worker` | Luna/low/bounded-write | 40 | 80 | 45 |
| `sol_reviewer` | Sol/high/read-only | 50 | 100 | 60 |
| `sol_developer` | Sol/medium/write | 60 и 120 | 180 | 120 |

Call bounds: `1..hard_calls`; minute bounds: `15..hard_minutes`. Descendant
agents — отдельный `bool: false`.

Глобальные AGENTS/profile TOML ссылаются на `policy_id` и profile key. Они не
повторяют эти числа. `config.toml` сохраняет нативный runtime concurrency key;
audit script проверяет его равенство canonical policy и падает в режиме
`-ValidatePolicy` при drift.

## Контракт проекта

`agents/config.yaml` повышается до `schema_version: 2` и получает:

- `external_execution_policy`: policy id, locator
  `user_codex_home/policies/agent-budget.yaml`, validation command и global
  profile ids; числовых execution limits здесь нет;
- `document_routing`: startup documents, estimator, startup limit и routes;
- `role_routing`: четыре project roles и ссылки на global profiles;
- `process_limits`: project review/technical/process budgets;
- `continuation`: state graph и `$ref` на пределы global policy;
- `packets`, `tool_output` и `consumers`.

### Карта ролей

| Роль | Default | Bounded | Escalation | Условие |
|---|---|---|---|---|
| `developer` | `sol_developer` | `luna_worker` | `sol_developer` | Luna только для механического слайса; несколько модулей, миграция, безопасность, конфликт контрактов или blocker возвращают работу Sol |
| `analyst-architect` | `luna_explorer` | — | `sol_reviewer` | Sol при структурном решении уровня 3, конфликте источников или высокой цене ошибки |
| `plan-reviewer` | `sol_reviewer` | — | — | Независимое read-only review полного пакета |
| `final-review` | `sol_reviewer` | — | — | Независимое read-only review готового результата |

### Project-specific budgets

| Ключ | Value | Unit | Bounds |
|---|---:|---|---|
| `document_routing.startup_estimated_tokens_limit` | 6000 | `estimated_tokens` | 1000…6000 |
| `process_limits.failed_reviews_before_escalation` | 2 | `reviews` | 1…2 |
| `process_limits.post_escalation_reviews` | 1 | `reviews` | 1…1 |
| `process_limits.technical_attempts_per_problem` | 3 | `attempts` | 1…3 |
| `process_limits.normal_overhead_target` | 25 | `percent` | 1…25 |
| `process_limits.level_1b_overhead_target` | 15 | `percent` | 1…15 |
| `process_limits.level_1b_max_overhead` | 10 | `minutes` | 1…10 |
| `packets.task.max_estimated_tokens` | 4000 | `estimated_tokens` | 500…4000 |
| `packets.review.max_estimated_tokens` | 6000 | `estimated_tokens` | 1000…6000 |
| `packets.jira_snapshot.max_estimated_tokens` | 2500 | `estimated_tokens` | 500…2500 |
| `tool_output.default_text` | 8000 | `characters` | 1000…8000 |
| `tool_output.search` | 4000 | `characters` | 500…4000 |
| `tool_output.test_failure` | 8000 | `characters` | 1000…8000 |
| `tool_output.web` | 8000 | `characters` | 1000…8000 |
| `tool_output.jira` | 6000 | `characters` | 1000…6000 |
| `tool_output.visual_artifacts_per_decision` | 1 | `artifacts` | 0…1 |
| `tool_output.visual_analysis_owners` | 1 | `agents` | 1…1 |

Task packet fields: `issue_key`, `objective`, `scope`, `acceptance`,
`relevant_paths`, `known_state`, `progress_evidence`, `next_action`.
Review packet fields: `issue_snapshot`, `acceptance`, `diff_summary`,
`verification`, `risks`, `source_links`. Jira snapshot fields: `issue_key`,
`status`, `acceptance`, `dependencies`, `updated_at`.

Conditional routes: `jira_work`, `product_behavior`, `domain_rules`,
`technology_or_architecture`, `multi_agent_work`, `telegram_live`,
`release_or_deployment`.

## Конечный continuation graph

- `running -> checkpoint_due`;
- progress evidence: `checkpoint_due -> progress_extension`;
- no progress: `checkpoint_due -> handoff_required`;
- `progress_extension -> completed|handoff_required`;
- valid compact packet и доступный global handoff:
  `handoff_required -> resumed`, иначе `blocked`;
- `resumed -> completed|blocked`;
- `completed` и `blocked` терминальны.

Пределы extension/handoff приходят `$ref` из `codex.agent-budget.v1`.
Progress evidence: tracked diff, новый прошедший тест, завершённый обязательный
артефакт или снятый blocker. Решение принимает корневой агент и фиксирует
evidence в task packet.

## Шаги реализации

1. Создать и провалидировать global `agent-budget.yaml`.
2. Перевести global AGENTS и profile TOML на ссылки без числовых копий.
3. Добавить `-ValidatePolicy` в token audit и проверить runtime consumers.
4. Реализовать project routing и `community_bot.orchestration.v2`.
5. Связать workflow, документы и четыре инструкции ролей с policy ids.
6. Добавить архитектурный тест позитивных/негативных project cases.
7. Выполнить target и full gates.
8. Перед merge проверить candidate-bound freeze CB-50.

## Проверки

- `powershell -NoProfile -File C:/Users/User/.codex/tools/Get-CodexTokenAudit.ps1 -ValidatePolicy -Hours 1 -Json`;
- `uv run pytest -o addopts='' tests/architecture/test_agent_orchestration_policy.py -q`;
- `uv run ruff check tests/architecture/test_agent_orchestration_policy.py`;
- `uv run pytest`;
- `uv run ruff check .`;
- `uv run ty check`;
- `git diff --check` и secret scan изменённой области.

Project test проверяет always-read budget, conditional paths, role mapping,
только Luna/Sol без default xhigh/Terra, отсутствие execution numbers в repo
YAML, external policy reference, конечность graph, project budgets и consumers.

Global validator проверяет YAML/bounds, TOML profile model/effort/key,
отсутствие checkpoint numbers в profile instructions, runtime concurrency из
`config.toml`, global AGENTS reference и drift.

## Риски и меры снижения

- Global policy недоступна в публичном CI: project CI проверяет symbolic
  contract, actual runtime — global validator; отчёт разделяет доказательства.
- Потеря доменного контекста: conditional routes указывают полные документы.
- Длинная работа: bounded extension и fresh handoff сохраняют progress, но
  graph остаётся конечным.
- Release 1: merge запрещён во время candidate-bound freeze CB-50.

## Критерии готовности

- plan review имеет `Status: approved`;
- ADR-0015 принят владельцем;
- global и project validators проходят;
- final review имеет `Status: approved`;
- ветка проходит CI и слита в `main` либо ожидает снятия CB-50 freeze.

