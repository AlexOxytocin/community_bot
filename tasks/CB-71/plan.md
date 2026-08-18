# CB-71 — fail-closed граница Оркестратора

**Статус:** одобрен единственной owner-approved post-escalation combined
plan/final проверкой; следующего review-цикла не требуется

**Jira:** `CB-71`

**Базовая версия:** `4af786dae39f3c89c97ebf1e97da355ad09aa964`
(`origin/main`, merge CB-69)

**Актуализированная база перед финальной проверкой:**
`bb543e978467882d90a323fdc9c180b0201a9629` (`origin/main`, merge CB-72); diff
CB-71 сохранён без захвата чужих изменений.

## Решение и граница

Закрепить одну абсолютную границу: пользовательский поток «Оркестратор» только
координирует портфель, но не исполняет работу конкретной Jira-задачи. Любое
действие вне закрытого allowlist считается execution; при неоднозначности оно
запрещается и требует отдельного видимого task-thread.

Allowlist Оркестратора:

- read-only анализ портфеля, зависимостей и состояния;
- создание и приоритизация Jira-задач;
- запуск, остановка и read-only monitoring видимых task-thread;
- передача compact handoff и создание successor-thread;
- запрос owner decision и сводный статус.

Оркестратору запрещены любой код, документация, тесты, repository/task artifacts,
любые Git-операции конкретной задачи, PR/merge, release/deploy, выполнение иной
работы Jira-задачи и перевод Jira-задачи в `Done` или другой terminal status.
Любое действие вне allowlist считается execution и блокируется. Внутренний
subagent не является видимым task-thread и может работать только внутри
task-thread соответствующего Jira key.

Если task-thread завершился, заблокирован или потерял контекст, Оркестратор
создаёт successor/handoff-thread для того же Jira key и не подхватывает работу.
Инвариант исполнения: один Jira key → один текущий видимый task-thread → одна
ветка `task/<KEY>`; successor продолжает ту же задачу и ветку после handoff.

Каждая продуктовая задача, а также любая задача с runtime diff, после merge в
`main` требует нового immutable release, production activation и public smoke;
Jira `Done` допустим только после green smoke без waiver. Только
process/docs-only задача без runtime diff получает явный deploy skip. Gate
исполняет user-visible task-thread этой Jira-задачи; Оркестратор лишь
контролирует gate и отражает сводный статус.

## Минимальный diff

| Файл | Правка |
|---|---|
| `AGENTS.md` | Добавить active fail-closed instruction, чтобы правило действовало при старте Оркестратора. |
| `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` | Зафиксировать канонический запрет, allowlist, recovery и delivery ownership. |
| `docs/adr/0015-cost-aware-multi-agent-orchestration.md` | Дополнить уже принятый orchestration ADR границей координации/исполнения; новый ADR не создавать. |
| `agents/config.yaml` | Добавить один machine-readable contract Оркестратора с allowlist, denylist и fail-closed recovery. |
| `agents/workflow.yaml` | Добавить отдельный orchestration execution boundary и отдельно обновить exact-tested `post_merge_delivery` mapping ADR-0019. |
| `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `docs/release-2/README.md`, ADR-0019 | Удалить старые waiver и широкий diff-only skip, чтобы strict standing delivery rule не имел противоречащего consumer. |
| `tests/architecture/test_agent_orchestration_policy.py` | Обновить exact contract на product-task delivery, узкий process/docs-only skip и запрет `Done` без smoke. |
| `tasks/CB-71/*` | План, source context, review, implementation report и final review. |

Role instructions, runtime code, product tests, release infrastructure и новый
orchestration framework не меняются. Exact architecture contract test
обновляется вместе с уже существующим delivery mapping.

## Acceptance и проверки

1. Абсолютный запрет любых code/docs/tests/repository/task/Git/PR/merge/release/
   deploy/terminal Jira действий и закрытый allowlist одинаково читаются в
   active instruction, каноническом guardrail и machine-readable policy.
2. `subagent != user-visible task thread`, successor/handoff и ambiguous→execution→blocked
   закреплены без takeover.
3. Один Jira key, один текущий видимый task-thread и одна `task/<KEY>` branch
   согласованы с существующим workflow.
4. Каждая продуктовая задача, а также любая задача с runtime diff, после merge
   в `main` получает в task-thread новый immutable release, production
   activation и public smoke до Jira `Done`; только process/docs-only задача без
   runtime diff получает skip; waiver и старый широкий docs/tests/task-artifacts
   skip отсутствуют во всех consumers.
5. YAML загружается, existing architecture policy tests проходят, Markdown/diff
   чисты, secret scan не находит credentials.
6. Ponytail review подтверждает отсутствие нового framework, роли, dependency,
   runtime guard и дублирования по role-файлам.

Команды проверки:

```powershell
uv run pytest --no-cov -q tests/architecture/test_agent_orchestration_policy.py
uv run python -c "import pathlib,yaml; [yaml.safe_load(pathlib.Path(p).read_text(encoding='utf-8')) for p in ('agents/config.yaml','agents/workflow.yaml')]"
git diff --check origin/main
```

Дополнительно выполнить точечный поиск обязательных deny/allow/recovery/delivery
формулировок и secret scan added lines.

## Риски и stop gates

- Расхождение prose и YAML: закрывается одной общей терминологией и точечной
  проверкой diff.
- Ложное ощущение runtime enforcement: deterministic guard не добавляется,
  потому что репозиторий не получает identity активного Codex-thread и не может
  надёжно различить Оркестратор и task-thread.
- Если enforcement потребует нового сервиса, hook, daemon, dependency или
  release framework, реализация останавливается и возвращается владельцу.
- Если выяснится runtime diff, post-merge deploy skip отменяется и применяется
  полный ADR-0019 gate.

## Ponytail audit

**KEEP:** существующие `AGENTS.md`, главный guardrail, ADR-0015,
`community_bot.orchestration.v2`, workflow и ADR-0019.

**DO NOT ADD:** новая роль Оркестратора, новый ADR, hook/daemon, thread registry,
policy engine, dependency, runtime code или копии правила во всех role-файлах.

**Минимальный результат:** перечисленные active/canonical consumers, один exact
contract test и обязательные артефакты CB-71; process/docs-only задача без
runtime diff классифицируется как `skip`.
