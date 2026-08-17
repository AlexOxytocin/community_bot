# CB-62 — терминальное ревью плана перехода к Mini App-only

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники

- Полностью прочитаны `plan.md`, `plan-source-context.md`, `inventory.md`,
  `test-plan.md`, `test-migration-map.md`, `cleanup-manifest.json`, оба предыдущих
  review attempts, `problem-escalation.md` и решение владельца после escalation.
- Сверены proposed ADR-0016, принятый ADR-0014, правила проекта и агентский
  process contract. ADR-0016 остаётся в статусе `Предложено`; его принятие после
  этого review принадлежит владельцу.
- Manifest и тестовая карта проверены независимо относительно base tree
  `21a4b4cae6bac706acbf43191659a79a680cb971` (`558` tracked paths).
- Просмотрены фактические assertions всех 21 перечисленного pytest node ID, а
  также текущие test-run quarantine predicates, PostgreSQL backup/restore,
  notification worker/outbox и migration surface.

## Область задачи

Обязательных замечаний нет. Область остаётся ограниченной удалением legacy
Telegram UI и R1 runtime/operations, не создаёт раньше CB-51–CB-56 FastAPI,
frontend или новую production topology и сохраняет domain/application,
PostgreSQL, ledger, audit, outbox, worker и migration history.

`cleanup-manifest.json` однозначно классифицирует каждый base tracked path:

- `341` paths получают `delete`, `44` — `replace`, `173` — `keep`;
- все `deleteExact` и `replaceExact` существуют в base tree;
- дубликатов, пересечений между exact lists, некорректных repo-relative paths и
  повторяющихся prefix rules не найдено;
- exact rule имеет приоритет, затем применяется единственный самый длинный
  prefix, затем `defaultDecision=keep`; узкий `tasks/CB-62/ = keep` корректно
  перекрывает `tasks/ = delete`;
- basename-only решений нет. Неперечисленные одинаковые basenames не расширяют
  destructive scope и остаются `keep`.

## Логика решения

Предыдущее замечание о неоднозначном destructive inventory закрыто
machine-readable contract. Delete/replace scope больше не выводится из
смысловых категорий в prose. Добавляемые paths отделены в `addExact` и не
маскируют существующие base paths.

Ранее закрытые design risks не регрессировали:

- `application/test_runs.py`, `db/test_runs.py`, query barriers в
  `db/tasks.py`, `db/assignments.py`, `db/task_cancellations.py`, recipient
  filters в `outbox/postgres.py` и существующие test-run tests разрешаются как
  `default=keep`; новый
  `tests/integration/test_legacy_test_run_quarantine.py` закреплён в `addExact`;
- все `23` tracked paths под `migrations/` получают `keep`, текущая разница
  `21a4b4c -- migrations/versions` пуста, а план требует и byte-for-byte diff,
  и upgrade/downgrade/upgrade;
- `ops/_runtime.py`, `backup_postgres.py`, `restore_drill.py`, их regression,
  `compose.production.yaml`, notification sender и worker заменяются exact
  rules, а PostgreSQL outbox остаётся. Поэтому удаление bot deploy/release не
  удаляет backup/restore или delivery semantics.

## Альтернативы и риски

Решение владельца после escalation явно выбрало один deterministic remediation;
варианты сузить либо остановить CB-62 больше не являются открытым вопросом этого
review. Временное core-only состояние и отсутствие production deployment
зафиксированы как принятые последствия, а не скрытая готовность Mini App.

## Стратегия проверки

Команда
`uv run pytest --collect-only -q <21 exact node IDs from test-migration-map.md>`
успешно собрала `21 tests collected`; отсутствующих или переименованных source
nodes нет.

Проверка тел тестов подтверждает заявленные targets: фактические assertions
покрывают audit/receipt exactly-once, полный rollback после fault injection,
bootstrap/invitation/grant/slot/moderation concurrency, publish/cancel replay,
ledger и outbox atomicity, migration immutability/provenance, settlement,
dispute и administrative audit facts. Пять nodes из удаляемых
`test_output_driven_flows.py` и `test_pilot_scenarios.py` имеют конкретный target
`test_core_workflows.py`; правило карты запрещает удалить source раньше переноса
assertion set и требует зафиксировать новый exact node ID в implementation
report. Остальные nodes сохраняются в replace-in-place files.

Дополнительно `git diff --cached --check`, `git diff --check` и проверка
отсутствия текущего diff в `migrations/versions` прошли без вывода.

## Обязательные исправления

Нет.

## Остаточные риски

- Новые target node IDs для пяти переносимых тестов появятся только при
  реализации. Их exact соответствие source assertion set, запуск PostgreSQL
  tests и новый legacy quarantine regression остаются обязательными gates
  implementation report и final review; это контролируемая неопределённость
  плановой стадии, а не открытый дефект плана.
- Массовое удаление по-прежнему несёт риск механической ошибки. Его закрывают
  manifest validator, полный оставшийся pytest с coverage, migration diff и
  независимый final review, уже предусмотренные пакетом.
