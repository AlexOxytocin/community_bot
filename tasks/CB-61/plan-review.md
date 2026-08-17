# CB-61 — review нового решения после решения владельца

Status: approved

Схема результата: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- Полностью прочитаны `AGENTS.md`,
  `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`,
  `agents/plan-reviewer/instruction.md`,
  `tasks/CB-61/plan-source-context.md`,
  `tasks/CB-61/owner-decision.md`,
  `tasks/CB-61/problem-escalation.md`, актуальный `tasks/CB-61/plan.md` и
  предыдущий `tasks/CB-61/plan-review.md`.
- Вместе с планом проверен предложенный
  `docs/adr/0015-cost-aware-multi-agent-orchestration.md`, а также принятые
  ADR-0003, ADR-0004 и ADR-0007.
- Для сверки действующего процесса прочитаны `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md`, `agents/config.yaml`, `agents/workflow.yaml` и
  `agents/README.md`; история двух обычных попыток сохранена в
  `tasks/CB-61/reviews/plan/attempt-01.md` и `attempt-02.md`.
- Фактические глобальные consumers сверены read-only по
  `C:/Users/User/.codex/AGENTS.md`, `C:/Users/User/.codex/config.toml`, четырём
  Luna/Sol profile TOML и `Get-CodexTokenAudit.ps1`. Секретные данные не
  читались и не фиксировались.
- Jira-цель, критерии, отсутствие родителя, комментариев и blockers проверены
  по сохранённому Jira snapshot в `plan-source-context.md`. Прямая read-only
  загрузка через Atlassian недоступна: connector вернул `403` с указанием, что
  приложение не установлено на instance; для данного явно назначенного
  owner-approved review это не создаёт смыслового пробела в предоставленном
  пакете источников.

## Область задачи

Новое решение соответствует явной границе владельца «глобальные бюджеты
канонические» и устраняет причину остановки прошлого цикла:

- `codex.agent-budget.v1` становится единственным исполняемым источником
  моделей, reasoning effort, concurrency, follow-up, polling, model-call/time
  checkpoints, progress extension и fresh-context handoff;
- глобальные AGENTS, profile TOML и `config.toml` становятся consumers этой
  политики и не сохраняют собственные checkpoint/hard-limit копии;
- `community_bot.orchestration.v2` хранит только project-specific document
  routing, отображение project roles на global profile ids, process/review,
  packet и tool-output budgets;
- таблица execution values в task plan является проверенным историческим
  решением до реализации, но не runtime-конфигурацией.

Тем самым после реализации не остаётся второго исполняемого источника,
обнаруженного предыдущим post-escalation review. Это review нового решения,
разрешённого обязательным решением владельца, а не ещё один автоматический
retry остановленного цикла ADR-0007.

## Логика решения

Разделение global/project проведено последовательно в плане и ADR-0015.
Глобальный validator проверяет canonical YAML, bounds и фактические runtime
consumers: model/effort/profile key в TOML, отсутствие числовых
checkpoint/hard-limit копий в profile instructions, native concurrency в
`config.toml`, ссылку из global AGENTS и drift между ними. Именно этот контур
может читать пользовательский Codex home и доказывать применимость глобальной
политики.

Project CI не пытается читать недоступный публичному CI пользовательский путь.
Он проверяет символическую половину контракта: точный policy id и locator,
разрешённые global profile ids, role mapping, `$ref` continuation limits,
отсутствие execution-limit чисел в repository YAML, project-specific budgets,
consumers и конечность graph. Такое разделение не ослабляет проверку: каждая
сторона валидирует доступную ей границу, а совпадающие нормативные числа между
двумя файлами больше не требуются.

Сложная многопоточность сохранена. План оставляет четыре специализированные
роли, Sol для сложной реализации и независимого смыслового review, Luna для
разведки и ограниченных механических слайсов. Fan-out, follow-up и unchanged
state checks ограничены, но измеримый прогресс допускает один extension и один
fresh-context handoff. Состояния `completed` и `blocked` терминальны, поэтому
длительная полезная работа не обрывается только по времени и одновременно не
создаёт бесконечный управляющий цикл. Это совместимо с ADR-0003 и ADR-0007.

CB-50 учтена корректно: план и ADR-0015 вводят pre-merge проверку
candidate-bound freeze. Во время freeze CB-61 может завершить разработку,
проверки и review, но merge ожидает снятия gate; критерии готовности честно
различают merged результат и ожидание freeze.

## Стратегия проверки

Критерии приёмки сопоставлены с автоматическими доказательствами:

| Критерий | Запланированное доказательство |
|---|---|
| Сокращённый startup context | estimator и предел `6000 estimated_tokens`, positive/negative project tests conditional routes |
| Явная Luna/Sol карта | точные четыре role mappings и проверка отсутствия Terra/default `xhigh` |
| Ограниченные fan-out/follow-up/polling | global YAML bounds, runtime consumer validation и конечный continuation graph |
| Продолжение при прогрессе | фиксированный список progress evidence, один extension, compact handoff и terminal-state tests |
| Компактный review packet | именованные поля и предел `6000 estimated_tokens` |
| Единый источник execution budgets | global validator consumers плюс project CI на symbolic refs и отсутствие repository execution numbers |
| Защита Release 1 | pre-merge CB-50 candidate-bound freeze gate |

Команды разделяют быстрый architecture test, полный pytest, lint, type check,
diff/secret checks и глобальный `-ValidatePolicy`. Прежний дефект, при котором
репозиторный pytest не мог доказать фактический global runtime, теперь закрыт
отдельным global validator.

## Обязательные исправления

Отсутствуют.

## Остаточные риски

- Project CI намеренно доказывает только symbolic contract и не подтверждает
  содержимое пользовательского Codex home; перед реализацией и в итоговом
  отчёте обязателен успешный global `-ValidatePolicy`.
- Оценка startup/packet tokens остаётся regression estimator, а не точным
  tokenizer usage. Это допустимо при зафиксированном открытом ограничении:
  точный процент недельного плана недоступен.
- ADR-0015 пока имеет статус `Предложено`. Reviewer не меняет его статус;
  принятие ADR владельцем до реализации остаётся обязательным lifecycle gate,
  а не исправлением плана.
- Состояние CB-50 необходимо перепроверить непосредственно перед merge: freeze
  является внешним изменяемым gate, а не статическим свойством ветки CB-61.

