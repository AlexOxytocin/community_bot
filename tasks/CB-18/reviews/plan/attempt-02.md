# CB-18 — второе независимое ревью плана

`community_bot.plan_review.verdict.v1`

Status: changes_requested

## Метаданные попытки

- phase: `plan`
- sequence: `2`
- base_commit: `0752a54aa889fb2e0e43cdf856ac8b20df4bf33b`
- snapshot_tree: `9e429ddaf7152133e2f0ef75847e448ec35e865f`
- previous_attempt: `tasks/CB-18/reviews/plan/attempt-01.md`

## Проверенные источники

- Jira `CB-18` и parent `CB-2` заново прочитаны напрямую через Atlassian Rovo
  API со всеми запрошенными полями. CB-18 имеет восемь критериев, статус
  `К выполнению`, приоритет `Medium`, пустые comments/links/labels/attachments и
  не имеет Jira-блокеров; CB-2 находится `В работе`.
- До чтения подтверждены `HEAD == origin/main ==
  0752a54aa889fb2e0e43cdf856ac8b20df4bf33b`, точный index tree
  `9e429ddaf7152133e2f0ef75847e448ec35e865f` и отсутствие unstaged/untracked
  файлов. Все новые источники прочитаны из Git index, а не из более позднего
  рабочего снимка.
- Полностью прочитаны staged `tasks/CB-18/plan.md`,
  `plan-source-context.md`, `test-plan.md`, предложенный ADR-0007 и неизменяемый
  `reviews/plan/attempt-01.md`.
- Полностью сверены `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`,
  `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, ADR-0004,
  `agents/workflow.yaml`, общие agent README/config, инструкции, procedures,
  configs и templates ролей `developer`, `plan-reviewer`, `final-review`, а
  также `pyproject.toml` и текущий unit-test contour.
- Секретов и противоречий Jira с решением владельца в пакете не обнаружено.
  Jira, Git remote, index и остальные файлы в ходе ревью не изменялись.

## Область и архитектурное решение

Область соответствует обновлённой CB-18: двухревьюная эскалация, редкие review
только полного результата, крупная когерентная нарезка, закрытые исключения,
два независимых режима `problem-escalation` и классификация регрессионных
багов рассматриваются одним сквозным результатом. ADR-0007 обоснован и остаётся
`Предложено`; принять его может только владелец после успешного plan-review.

## Результат повторной проверки M-001–M-006

| Пакет | Результат |
|---|---|
| M-001 — история и счётчики | Закрыт: manifest, immutable attempts, SHA-256, outcomes, writer `developer`, readers обоих reviewer и фазовый lifecycle заданы |
| M-002 — snapshot и полные gates | Частично закрыт: base/index-tree identity, Level 3 plan gate, Level 2–3 final gate и Level 1 сохранены; Git invalidation сформулирована технически неверно |
| M-003 — полный scope | Закрыт: включены PROJECT_RULES, AGENT_WORKFLOW, JIRA_WORKFLOW, final-review procedures, общие/role configs, README и templates |
| M-004 — два режима эскалации | Закрыт: существующий template обновляется, `technical_attempts` и `review_cycle` имеют независимые пороги и полные поля |
| M-005 — граница задачи | Закрыт: четыре одновременных условия, независимые ценности под эпиком, закрытые исключения и Level 1 покрыты позитивными/негативными сценариями |
| M-006 — semantic machine contract | Частично закрыт: PyYAML unit test и state scenarios спланированы, но точной структуры `review_cycle_policy` в проверяемом пакете нет |

## Обязательные замечания

### R-001 — working-tree edit не меняет `git write-tree`

План и ADR утверждают: «любое изменение reviewed file после gate меняет tree»;
сценарий 16 повторяет это как ожидаемый результат. В Git `git write-tree`
сериализует index. Изменение файла только в working tree оставляет
`snapshot_tree` прежним до `git add`. Следовательно, реализация буквально по
плану либо создаст неверный тест, либо сможет ошибочно принять старые
доказательства по неизменившейся паре base/tree.

Обязательное исправление: разделить два сигнала инвалидирования.

1. Любой unstaged/untracked файл в reviewed scope немедленно делает gate
   невалидным, даже если `git write-tree` ещё равен старому значению.
2. После полного restage новый `git write-tree` определяет новый snapshot;
   доказательства принимаются только для него. Если байты полностью возвращены
   к прежнему состоянию и tree совпал, это тот же content snapshot, но gate всё
   равно должен подтвердить отсутствие dirty scope перед review.

Сценарии 15–16 и semantic contract должны явно проверять edit-before-stage,
dirty rejection и restaged-tree transition, а не недостоверное «edit всегда
меняет tree».

### R-002 — `review_cycle_policy` назван, но не определён

`test-plan.md` требует проверять «точные поля `review_cycle_policy`», однако
этот идентификатор встречается в staged tree только в самом требовании теста.
Ни `plan.md`, ни ADR-0007 не содержат YAML mapping, ключей, типов, enum или
таблицы переходов. Исполнитель будет одновременно изобретать структуру и писать
тест к собственной структуре; такой self-fulfilling test не доказывает
проверенное решение и не закрывает M-006.

Обязательное исправление: добавить в план точный machine-readable contract,
который затем без творческого выбора переносится в `agents/workflow.yaml`.
Минимально он должен зафиксировать:

- schema/version, history path/schema, immutable attempt paths, writer/readers
  и обязательные/условные manifest fields;
- snapshot keys и два отдельных dirty/index-tree invalidation rules из R-001;
- applicability Level 1/2/3 и полные input gates plan/final;
- отдельные phase counters, counted verdicts, non-counted outcomes, reset/end
  rules и сохранение history при смене agent/file/commit;
- переходы first failure → full re-gate, second failure →
  `escalation_required`, completed consolidated cycle → разрешён один review,
  его failure → `owner_stop`;
- независимый `technical_attempts` threshold `3` и `review_cycle` threshold `2`;
- четыре условия task boundary и точный закрытый список small-task exceptions.

Unit test должен сравнивать эти конкретные значения и переходы, включая
manifest scenarios 8–9, а не только подтверждать наличие произвольно выбранных
ключей.

## Сопоставление критериев Jira

| Критерий CB-18 | Результат |
|---|---|
| Двухревьюный барьер | семантически закрыт |
| Единые процедуры ролей | scope закрыт |
| Минимальный пакет | закрыт двумя режимами |
| Счётчики и фазы | закрыты на уровне плана; machine schema ещё не зафиксирована |
| Полные gates без узких слайсов | состав закрыт; snapshot invalidation требует R-001 |
| Крупная когерентная нарезка | закрыта четырьмя условиями и исключениями |
| Классификация багов | соответствует Jira и решению владельца |
| Links/YAML/language/diff | проверяемый YAML contract пока отсутствует |

## Обязательные действия и эскалационный барьер

Это второе завершённое непройденное plan-review той же фазы: attempt 01 и
текущая attempt 02 имеют `Status: changes_requested`. После архивирования этого
артефакта запрещены очередное точечное исправление и новое review.

Необходимо создать/обновить `problem-escalation.md` в режиме `review_cycle`,
включить оба immutable review и все M/R findings, выполнить одно
консолидированное исправление R-001 и R-002 вместе с общей регрессионной
проверкой M-001–M-006, затем повторить полный плановый gate на новом staged
snapshot. Только после этого допустимо следующее независимое review с нуля.

## Остаточные риски

- Правило снимка должно использовать Git index как content identity, а
  working-tree status — как отдельный guard; смешение этих понятий снова
  откроет путь к доказательствам не того снимка.
- Размер когерентной задачи остаётся инженерным решением, но четыре условия и
  закрытые исключения дают достаточную проверяемую границу без искусственного
  лимита файлов или строк.
- Отдельный Jira-баг/ветка остаются внешними мутациями и требуют установленного
  проектом намерения; процессная классификация не выполняет их автоматически.
