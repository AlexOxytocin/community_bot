# CB-71 — исходный контекст плана

## Точный baseline и Jira

- `origin/main`: `4af786dae39f3c89c97ebf1e97da355ad09aa964`, merge CB-69.
- Перед единственным owner-approved review ветка повторно обновлена на
  `bb543e978467882d90a323fdc9c180b0201a9629`, merge CB-72; исходный baseline
  поручения сохранён выше как provenance.
- Jira `CB-71`: статус при планировании — `В работе`; связей, подзадач и
  вложений нет.
- Прямое поручение владельца требует fail-closed boundary, отдельный видимый
  task-thread, successor/handoff вместо takeover и delivery ownership внутри
  task-thread. Каждая продуктовая задача, а также любая задача с runtime diff,
  после merge в `main` требует нового immutable release, production activation
  и public smoke до Jira `Done` без waiver; только process/docs-only задача без
  runtime diff получает deploy skip.

## Обязательные источники

- `AGENTS.md` и `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — active и
  канонические project instructions.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md` — Jira-first lifecycle,
  one-task branch, review, merge и terminal transition gates.
- `docs/AGENT_CONTEXT_AND_COST_POLICY.md`, `agents/README.md`,
  `agents/config.yaml`, `agents/workflow.yaml` — multi-thread routing, compact
  packets, continuation и project orchestration contract.
- `docs/adr/0015-cost-aware-multi-agent-orchestration.md` — существующее принятое
  решение по orchestration, continuation и handoff; это правильное место для
  durable boundary без нового ADR.
- `docs/release-2/README.md` и
  `docs/adr/0019-single-pilot-post-task-delivery-gate.md` — исходный delivery
  contract содержал owner waiver и широкий docs/tests/task-artifacts skip,
  которые противоречат новому strict standing rule и должны быть удалены.

## Проверенные факты

- Внутри репозитория нет отдельной исполняемой роли Оркестратора и нет
  достоверного сигнала identity текущего Codex-thread.
- Поэтому hook или test способен проверить только наличие policy, но не
  предотвратить выполнение команды не тем пользовательским потоком.
- Existing architecture test валидирует загрузку `agents/config.yaml`,
  `agents/workflow.yaml`, consumer references и точный ADR-0019 delivery gate.
  Task-thread owner кодируется отдельным workflow boundary; exact-tested
  `post_merge_delivery` mapping обновляется, потому что старые waiver и широкий
  diff-only skip делали strict rule неисполняемым.
- CB-71 меняет только process/docs/task artifacts и потому после merge требует
  явный `skip`, но не новый production release.

## Принятое сужение

Не создаются новая роль, orchestration framework, state registry, hook, daemon,
dependency, release automation или runtime code. Enforcement остаётся в
минимальном active/canonical/machine-readable/workflow наборе; role-specific
instructions не получают повторные копии одного правила. Оркестратор не
выполняет никакие code/docs/tests/repository/task/Git/PR/merge/release/deploy/
terminal Jira действия; любое действие вне allowlist считается execution и
блокируется.
