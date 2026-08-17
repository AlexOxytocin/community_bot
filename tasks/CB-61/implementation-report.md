# CB-61 — отчёт о реализации

## Итог

Реализована двухуровневая политика агентской разработки:

- глобальная `codex.agent-budget.v1` стала единственным исполняемым источником
  моделей, reasoning effort, concurrency, follow-up, ожиданий, checkpoint,
  hard limit и continuation;
- проектная `community_bot.orchestration.v2` хранит только document routing,
  project role → global profile, process/review limits, compact packets и
  tool-output budgets.

Многопоточная разработка сохранена: независимые механические слайсы могут идти
через Luna, сложная реализация и независимые reviews — через Sol. Длительная
задача может продолжиться только по конечному continuation graph при наличии
измеримого progress evidence.

## Выполненные критерии

| Критерий | Статус | Доказательство |
|---|---|---|
| Канонические глобальные бюджеты | выполнено | `C:/Users/User/.codex/policies/agent-budget.yaml`, успешный `-ValidatePolicy` |
| Только Luna и Sol в основных маршрутах | выполнено | `agents/config.yaml#/orchestration_policy/role_routing`, архитектурный тест |
| Сложные слайсы субагентов могут завершаться | выполнено | bounded progress extension и fresh-context handoff; graph и evidence канонически определены в global policy, проект хранит точные refs |
| Нет локальных копий execution budgets | выполнено | global profile TOML ссылаются на policy; отрицательный project test отвергает локальный budget |
| Компактный стартовый контекст | выполнено | `AGENTS.md`, `document_routing`, проверка оценки startup tokens |
| Compact task/review/Jira packets | выполнено | схемы и bounds в `agents/config.yaml`, потребители в role instructions |
| Ограниченный вывод инструментов | выполнено | `tool_output` и правило file + summary в project policy |
| Drift обнаруживается автоматически | выполнено | global audit проверяет policy/config/AGENTS/profiles/script; project architecture test проверяет routes, roles, graph, budgets и consumers |
| Процессные повторы централизованы | выполнено | `agents/workflow.yaml` ссылается на `process_limits`; числовые копии удалены из operational docs |

## Изменения

### Глобально

- создан `C:/Users/User/.codex/policies/agent-budget.yaml`;
- обновлены `C:/Users/User/.codex/AGENTS.md` и четыре profile TOML;
- `Get-CodexTokenAudit.ps1` читает canonical values и поддерживает
  `-ValidatePolicy`.

### В Community Bot

- добавлены conditional document routing, role routing, process limits,
  точные ссылки на global continuation, packets и tool-output policy;
- обновлены workspace instructions, workflow, четыре role instruction и
  operational docs;
- принят ADR-0015;
- добавлен `tests/architecture/test_agent_orchestration_policy.py` с позитивным
  и отрицательными сценариями.

## Проверки

| Проверка | Результат |
|---|---|
| Global policy validation | valid; policy `codex.agent-budget.v1`; проверено 21 budget node, 7 consumers, canonical continuation и 3 negative mutations |
| Profile TOML parse | valid |
| Target project policy tests | 10 passed |
| `uv run ruff format --check .` | passed |
| `uv run ruff check .` | passed |
| `uv run ty check` | passed |
| `uv run pytest` | 605 passed, 1 skipped; coverage 80.32% |
| `git diff --check` | passed |
| Secret-like value scan изменённой области | совпадений нет |

## Отклонения от плана

После final review граф и progress evidence удалены из project policy как
избыточная копия: теперь они тоже каноничны только в глобальной policy. Публичный
CI проверяет точные symbolic refs, а фактический graph и runtime consumers —
локальный global validator.

Первый PR run выявил пропущенный локально formatting gate в одном тесте.
`ruff format` изменил только перенос строки без изменения поведения; после этого
format, lint, type check и target policy tests повторно прошли.

## Остаточные риски

- Уже запущенные до изменения сессии не получают новую policy задним числом.
- Project CI не имеет доступа к пользовательскому Codex home и поэтому не может
  проверить фактические глобальные значения; он проверяет точные refs, а drift
  фактического graph ловится локальной исполняемой командой `-ValidatePolicy`.
- Merge зависит от проверки candidate-bound freeze задачи CB-50.
