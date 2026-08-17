# CB-62 — отчёт о реализации

## Итог

Репозиторий переведён в переходное состояние Mini App-only, утверждённое
ADR-0016. Полноценный Telegram chat UI, long-polling runtime, R1 pilot/release
обвязка и исторические task artifacts удалены. Сохранены доменные и прикладные
правила, PostgreSQL-модели и репозитории, ledger, audit, outbox, worker,
история Alembic, backup и isolated restore drill.

Фактический staged diff относительно `21a4b4cae6bac706acbf43191659a79a680cb971`:
410 файлов, 2864 добавления и 41947 удалений. Большая часть объёма — удалённые
presentation/pilot tests и старые task artifacts; миграции не изменены.

## Выполненная область

1. `src/community_bot/transport/telegram/`, bot bootstrap, runner, pilot и
   управляющий test-run CLI удалены вместе с их presentation tests.
2. Outbound Telegram adapter оставлен только для allowlisted plain-text
   уведомлений. Reply keyboard, callback mutations, FSM и transport routers в
   runtime отсутствуют.
3. `community-worker` продолжает обрабатывать PostgreSQL outbox и assignment
   deadlines без импорта удалённого UI. Health gate проверяет только актуальный
   worker process.
4. Production Compose сокращён до `postgres`, `migrate`, `worker`. Новые API,
   frontend, TLS и rollout намеренно не реализованы: это область CB-51–CB-56.
5. R1 deploy/release/smoke/systemd surface удалён. PostgreSQL backup и isolated
   restore drill сохранены и не зависят от старого bot runtime.
6. Старые каталоги `tasks/CB-*` удалены из текущего дерева; история остаётся в
   Git, текущий пакет CB-62 сохранён.
7. README, architecture, project rules, MVP/release-2 документы и исторические
   ADR согласованы с единственным направлением Mini App/web.
8. `aiogram` остаётся только зависимостью outbound notification adapter; слои
   domain/application его не импортируют.

## Критерии приёмки и доказательства

| Критерий | Реализация | Проверка и результат |
| --- | --- | --- |
| Нет старого Telegram UI/runtime | Удалены transport, bot/runner/pilot/test-run entrypoints, R1 ops | Ограниченный `rg` по `src tests ops compose.production.yaml .github/workflows`: `legacy_runtime_references_absent` |
| Backend и данные сохранены | Domain/application, PostgreSQL, ledger, audit, outbox и worker остаются | Полный `uv run pytest`: 516 passed; PostgreSQL integration suite зелёный |
| Миграции неизменны | Ни один revision не редактировался и не удалялся | `git diff --exit-code 21a4b4c... -- migrations/versions`: exit 0; migration-cycle tests входят в полный прогон |
| Test-run данные остаются закрыты | Удалён управляющий CLI, сохранены predicates/models/query/outbox quarantine | Самостоятельный `test_legacy_test_run_quarantine.py` seed-ит active/completed runs, tasks, assignment и pending outbox: обычные actors не видят строки, completed event не получает recipients |
| Уведомления не возвращают старый UI | Adapter отправляет только allowlisted text без markup/callback | Unit/integration notification tests и import/search gate зелёные |
| Core runtime пригоден для следующего этапа | Оставлены migrate, initial-admin, product-config, health и worker entrypoints | Smoke/unit tests entrypoints зелёные; `uv build` успешно создал sdist и wheel |
| Transitional Compose валиден | Только postgres/migrate/worker, внешний image задаётся переменной | `docker compose -f compose.production.yaml config --quiet`: exit 0 с безопасными placeholder env |
| Старые task artifacts удалены управляемо | Решения закреплены в machine-readable manifest | Validator `cleanup-manifest.json`: каждый изменённый base path классифицирован, delete/keep/replace/add правила соблюдены |
| Документация не обещает готовый Mini App | Явно описан core-only этап и ответственность CB-51–CB-56 | Markdown link/path scan: внутренних битых ссылок нет |

## Перенос критических проверок

Точные transport-free node IDs, перечисленные в `test-migration-map.md`,
сохранены в исходных integration-файлах. Пять проверок из удалённых
`test_output_driven_flows.py` и `test_pilot_scenarios.py` перенесены в:

- `test_core_workflows.py::test_cancellation_replay_remains_application_owned`;
- `test_core_workflows.py::test_community_data_survives_the_migration_cycle`;
- `test_core_workflows.py::test_full_exchange_reconciles_ledger_exactly_once`;
- `test_core_workflows.py::test_dispute_resolution_preserves_ledger_and_audit`;
- `test_core_workflows.py::test_raw_karma_access_remains_administrative_and_audited`.

Каждый target выполняет собственный transport-free application/PostgreSQL
workflow и сохраняет уникальные assertions источника: consent всех slots и два
reliability events; provenance/safety snapshot/transaction IDs через
`0012→0011→0012`; reconciliation cached balances с ledger, task/outbox и
karma eligibility; dispute/resolution counts и private payload exclusion;
paid karma replacement, raw audit и отсутствие receipt у чужого actor.

Отдельный
`test_legacy_test_run_quarantine.py::test_legacy_test_rows_remain_quarantined_without_the_old_cli`
проверяет post-removal quarantine. Целевой PostgreSQL прогон карты и новых
инвариантов до первого final review: 22 passed. После замечаний reviewer-а
самостоятельные workflows, расширенный quarantine и точные notification tests
прошли remediation gate: 21 passed.

## Полный набор проверок

- `uv run pytest` — 516 passed за 321,35 с, coverage 80,90% при пороге 80%;
- `uv run ruff format --check .` — 205 файлов отформатированы;
- `uv run ruff check .` — ошибок нет;
- `uv run ty check src tests ops` — ошибок нет;
- `uv build` — sdist и wheel собраны;
- `git diff --check` — ошибок whitespace нет;
- production Compose config — валиден;
- manifest, links/path и secret-like scans — зелёные;
- исторические Alembic revisions — byte-for-byte без изменений.

## Границы и остаточный риск

Реальный Telegram live action и production deployment не выполнялись и не
заявляются. Пользовательского runtime между CB-62 и реализацией CB-52/CB-53
намеренно нет. Server-side ActorContext/operation identity, FastAPI auth/API,
React UI и новая deployment topology остаются в CB-51–CB-56. Destructive data
migration не выполнялась; возврат удалённого UI возможен только из истории Git
и потребует нового архитектурного решения.
