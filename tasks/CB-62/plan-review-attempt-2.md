# CB-62 — повторное ревью плана перехода к Mini App-only

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

## Проверенные источники

- Полностью перечитаны Jira snapshot из `plan-source-context.md`, обновлённые
  `inventory.md`, `plan.md`, `test-plan.md`, новый `test-migration-map.md` и
  сохранённый первый verdict `plan-review-attempt-1.md`.
- Сверены proposed ADR-0016, принятый ADR-0014, фактическое дерево runtime,
  tests, ops, docs/config, зависимости worker/outbox и staged diff на base
  `21a4b4c`.
- Повторно проверены области предыдущих findings: test-run quarantine,
  mixed integration tests, historical Alembic revisions и PostgreSQL
  backup/restore.

## Замечания по области

1. **High — подтверждено: заявленный исполняемый keep|replace|delete manifest
   всё ещё не задаёт однозначную классификацию фактического дерева.** Runtime и
   ops теперь в основном описаны точными путями, но test/docs/config surface
   остаётся набором basename и смысловых категорий. В частности:

   - `inventory.md` указывает `test_initial_admin.py` и
     `test_notifications.py` без каталога, хотя в дереве есть одновременно
     `tests/unit/test_initial_admin.py` и
     `tests/integration/test_initial_admin.py`, а также unit и integration
     варианты `test_notifications.py`;
   - delete-категория `pilot metrics, test-run CLI, deploy/release provenance
     tests` и docs-категории `старые R1 implementation/test/handoff документы`
     не содержат paths/globs;
   - replace-категории `product flow/security docs` и `все ссылки на удалённые
     paths` не дают конечного множества файлов;
   - такие tracked paths, как `config/product-config.v1.json`,
     `config/product-config.v2.json`, `.github/CODEOWNERS`,
     `tests/unit/test_operations.py` и `tests/unit/test_runtime_operations.py`,
     не получают явного решения в разделе «Исполняемый manifest».

   Поэтому проверка «сравнить tracked paths до/после с `inventory.md`» из
   `test-plan.md` не имеет машинно проверяемого ожидаемого результата. При
   destructive Level 3 cleanup исполнитель всё ещё должен сам решать, какой
   конкретный файл означает общий ярлык. Это оставляет исходный риск удаления
   общей логики и тестов открытым.

## Замечания по дизайну

Обязательных новых design findings нет. Предыдущие design-дефекты закрыты:

- `application/test_runs.py`, `infrastructure/db/test_runs.py`, ORM models,
  UoW methods, `test_run_id IS NULL` barriers и recipient/suppression predicates
  явно сохраняются; удаляется только управляющий CLI/pilot surface;
- `infrastructure/outbox/telegram.py` и `worker/entrypoint.py` заменяются in
  place без импортов удаляемого UI, а ledger, audit, PostgreSQL outbox и worker
  остаются;
- `backup_postgres.py`, `restore_drill.py` и их regression сохраняются и
  адаптируются, тогда как bot deploy/release/smoke удаляются;
- CB-62 не создаёт FastAPI, React, ActorContext или новую production topology
  раньше CB-51–CB-56.

## Замечания по проверкам

1. **High — подтверждено: `test-migration-map.md` не делает перенос mixed tests
   проверяемым на уровне удаляемых test nodes.** Таблица содержит по одной
   общей строке на basename, но правило 4 требует сравнить её с удалёнными test
   names. Самих test names в таблице нет. Например,
   `tests/integration/test_output_driven_flows.py` содержит 20 test functions,
   а `tests/e2e/test_pilot_scenarios.py` — пять; их строки описывают лишь группы
   инвариантов. Значит, автоматическая либо независимая сверка не может
   доказать, что перед удалением перенесён каждый относящийся к ledger, audit,
   rollback, concurrency и exactly-once test, а не только один представитель
   группы.

2. Положительно подтверждено: `git diff --cached --check` проходит;
   `git diff --exit-code 21a4b4c -- migrations/versions` проходит; HEAD и main
   равны `21a4b4c`; целевой baseline
   `tests/architecture/test_import_boundaries.py` и
   `tests/unit/test_notifications.py` проходит — `19 passed`.

## Обязательные исправления

1. Представить inventory как нормализованный набор `keep|replace|delete` с
   точными repo-relative paths либо однозначными globs и явными исключениями;
   gate должен отклонять любой tracked path вне manifest. Отдельно
   классифицировать все tests, docs, config, CI и package/repository files, не
   используя неоднозначные basename или смысловые ярлыки.
2. Добавить в `test-migration-map.md` точные pytest node IDs сохраняемых
   core-проверок и их target node IDs после очистки либо эквивалентный
   генерируемый before/after manifest. Удаление исходного файла разрешать
   только после полного соответствия этой карте.

Это terminal verdict единственной повторной проверки; новый локальный цикл
ревью не предлагается.

## Остаточные риски

- После исправления manifest главным риском реализации останется механическая
  ошибка при крупном удалении. Её должны ловить allowlist gate, полный pytest,
  migration immutability check и независимый final review.
- Временное core-only состояние без пользовательского runtime и отсутствие
  production deployment являются явным решением владельца, а не finding.
- ADR-0016 остаётся `Предложено`; его принятие по-прежнему принадлежит
  владельцу и не может быть сделано этим ревью.
