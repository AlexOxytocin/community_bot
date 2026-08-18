# CB-71 — ревью плана

Status: changes_requested

## Проверенные источники

- live snapshot поручения CB-71;
- `tasks/CB-71/plan.md` и `tasks/CB-71/plan-source-context.md`;
- active и канонические project/workflow/orchestration/release документы;
- ADR-0015, ADR-0019 и `tests/architecture/test_agent_orchestration_policy.py`.

Baseline подтверждён: `origin/main` =
`4af786dae39f3c89c97ebf1e97da355ad09aa964`.

## Итог повторной проверки

Закрытый allowlist и абсолютный denylist однозначно задают
`ambiguous => execution => blocked`. Явно закрыты любые
code/docs/tests/repository/task/Git/PR/merge/release/deploy и terminal Jira
actions. `subagent != user-visible task-thread`, successor/handoff вместо
takeover и one Jira/current visible thread/branch закреплены.

Каждая продуктовая задача после merge в `main` требует нового immutable
release, production activation и public smoke до Jira `Done`; skip разрешён
только process/docs-only задаче без runtime diff. Gate исполняет task-thread,
Оркестратор только контролирует.

## Проверки

- `uv run pytest --no-cov -q tests/architecture/test_agent_orchestration_policy.py`
  → `11 passed`;
- YAML contract → `yaml-ok`;
- `git diff --check origin/main` → без ошибок.

## Ponytail

Lean already. Ship. Новый framework или декоративный deterministic guard не
нужен: repository не имеет надёжного identity-сигнала активного Codex-thread.

## Review escalation

После изменения delivery scope второй failed verdict выявил три устаревшие
формулировки plan: противоречие по exact mapping, неполный predicate без
non-product runtime diff и старый счётчик «пять файлов». Попытки сохранены в
`reviews/plan/`; выполнена одна консолидированная правка. Требуется единственная
post-escalation проверка.

## Терминальный post-escalation verdict

Status: changes_requested

Фактические active/canonical/machine-readable consumers не везде реализуют
положительный predicate `product_task OR any_runtime_diff`: часть prose и
`orchestrator_boundary` называет только product task, а exact delivery mapping
перечисляет конечный набор runtime-категорий вместо `any_runtime_diff`.

По process limit дальнейшая правка и review требуют owner decision.

## Остаточный риск

Enforcement остаётся instruction-level и зависит от fail-closed соблюдения
активным агентом; технической identity-блокировки нет, и план честно фиксирует
этот предел.
