# CB-62 — карта текущего дерева

Дата среза: 17.08.2026, `main` = `21a4b4c`.

## Keep

| Контур | Почему остаётся |
| --- | --- |
| `domain/` | Бизнес-инварианты, состояния и значения не зависят от UI |
| Основной `application/` | Оркестрация экономики, заданий, модерации и outbox переиспользуется API |
| `infrastructure/db/` | PostgreSQL adapters, ledger, audit, outbox и историческая schema |
| `migrations/` | Forward-only история данных; старые revision не переписываются |
| `worker/` и outbound notification adapter | Дедлайны и короткие Telegram-уведомления нужны Mini App |
| Test-run data quarantine | Исторические test rows обязаны оставаться невидимыми и не расширять рассылку |
| `docs/release-2/design/` | Утверждённая компактная дизайн-система Mini App |
| Domain/integration tests | Защищают общие правила при удалении presentation слоя |
| Jira/process/agent rules | Инженерный процесс не является частью legacy UI |

## Replace

| Текущий контур | Замена |
| --- | --- |
| `ActorContext`-отсутствие и Telegram-shaped application commands | CB-51: internal actor + HTTP operation identity |
| Bot entrypoint и chat navigation | CB-52/CB-53: FastAPI + SPA; минимальный launch shell только при необходимости |
| Reply keyboard/callback внутри notification sender | Plain outbound message; deep link добавляется вместе с Mini App URL |
| R1-oriented README, architecture, tech stack и product flows | Короткие Mini App-first документы |
| Production bot Compose/release workflow | CB-56: API/frontend/worker topology |
| ADR-0014 fallback/parity | ADR-0016 Mini App-only, при сохранении монолита и общего ядра |
| PostgreSQL backup/restore | Сохранить и адаптировать к transitional postgres/migrate/worker Compose |

## Delete

| Контур | Фактическая причина |
| --- | --- |
| `src/community_bot/transport/telegram/` | 12 файлов полноценного chat UI: routers, FSM, cards, keyboards |
| `bootstrap/bot.py` и bot script | Long-polling UI больше не является продуктом |
| Pilot runtime и test-run CLI | Управляли закрытым R1 live-acceptance процессом; data quarantine остаётся |
| Telegram presentation/E2E/pilot tests | Проверяют удаляемый UI и старый pilot workflow |
| Deploy/smoke scripts, release workflow и root wrappers | Закрепляют снятую R1 deployment topology; backup/restore не удаляются |
| `docs/operations/` и bot-only product docs | Описывают закрытое направление |
| Старые `tasks/CB-*` | 284 process-файла уже доступны в Git/Jira и засоряют текущее дерево |
| `config/testing/tg-test.yaml` | Профиль был нужен старому multi-user live gate |

## Границы удаления

- `members.telegram_user_id`, Telegram identity mapping и старые receipt/test-run
  таблицы не удаляются из migration history.
- Общие бизнес-модули не удаляются только потому, что их текущий Python API ещё
  Telegram-shaped: их переводят CB-51, CB-54 и CB-55.
- Outbound Bot API допускается только как доставка короткого уведомления; он не
  возвращает старые меню, FSM или mutation callbacks.
- CB-62 не создаёт FastAPI/frontend заглушки и не объявляет отсутствующий
  Mini App runtime готовым.

## Исполняемый manifest

Каноническая machine-readable классификация находится в
`cleanup-manifest.json`. Алгоритм однозначен:

1. exact path из `deleteExact`/`replaceExact` получает это решение;
2. иначе применяется самый длинный совпавший `prefixRules.prefix`;
3. иначе действует `defaultDecision=keep`.

Поэтому любое не перечисленное содержимое, включая совпадающие basenames,
остаётся. Prose ниже объясняет intent, но не расширяет delete scope.

### Runtime

`keep`:

- `src/community_bot/domain/**`;
- `src/community_bot/application/**`, кроме точных delete paths ниже;
- `src/community_bot/infrastructure/db/**`, кроме `db/pilot.py`;
- `src/community_bot/infrastructure/observability/**`;
- `src/community_bot/infrastructure/outbox/postgres.py` и все test-run
  recipient/suppression predicates;
- `src/community_bot/application/test_runs.py`,
  `src/community_bot/infrastructure/db/test_runs.py`, ORM models, UoW methods и
  все `test_run_id IS NULL`/scope barriers;
- bootstrap `health.py`, `initial_admin.py`, `migrate.py`,
  `migration_head.py`, `product_config.py`, `product_config_cli.py`,
  `settings.py`;
- `migrations/**` без изменения существующего содержимого.

`replace in place`:

- `infrastructure/outbox/telegram.py` → plain allowlisted notifications без
  imports из удаляемого transport, keyboards или mutation callbacks;
- `worker/entrypoint.py` → тот же worker без UI markup factory;
- `compose.production.yaml` → transitional `postgres + migrate + worker`, без
  bot service; `Dockerfile` остаётся generic core/worker image;
- `bootstrap/health.py` → только реально существующие process names;
- `application/conversations.py` и `db/conversations.py` временно остаются как
  зависимость reputation/application до CB-55, но новые UI зависимости туда не
  добавляются.

`delete`:

- `src/community_bot/transport/telegram/**`;
- `bootstrap/bot.py`, `bootstrap/pilot_report.py`, `bootstrap/runner.py`,
  `bootstrap/test_run.py`;
- `application/navigation.py`, `application/pilot.py`,
  `infrastructure/db/pilot.py`.

### Tests

`keep`:

- `tests/architecture/**`, `tests/documentation/**`;
- все domain tests;
- PostgreSQL economy/property/database/notification/test-run tests;
- `tests/unit/test_test_runs.py`, `tests/integration/test_test_runs.py` и новый
  quarantine regression.

`replace in place before transport deletion` (точные полные paths заданы в
`cleanup-manifest.json`):

- `test_member_foundation.py`, `test_initial_admin.py`, `test_catalog.py`,
  `test_registration.py`, `test_task_creation.py`, `test_assignments.py`,
  `test_moderation.py`: удалить dispatcher/fake Bot API части, сохранить прямые
  application/PostgreSQL assertions;
- `test_output_driven_flows.py` и `test_pilot_scenarios.py`: перенести
  перечисленные в `test-migration-map.md` core assertions в
  `test_core_workflows.py`, после чего удалить исходные presentation files;
- `test_notifications.py` и entrypoint smoke/unit tests: сузить до plain sender
  и фактических core scripts.

`delete after replacement gates`:

- `tests/unit/*_transport.py`, `test_task_card.py`,
  `test_navigation_transport.py`, `test_conversation_transport.py`;
- `tests/integration/test_navigation.py`, `test_pilot_readiness.py`;
- `tests/e2e/**`, `tests/fixtures/pilot_e2e_seed.json`;
- pilot metrics, test-run CLI, deploy/release provenance tests.

### Ops, docs и repository surface

`keep/adapt`:

- `ops/__init__.py`, `ops/_runtime.py`, `ops/backup_postgres.py`,
  `ops/restore_drill.py`, `tests/unit/test_restore_drill.py`;
- `.github/workflows/ci.yml`, `compose.yaml`, `compose.production.yaml`,
  `Dockerfile`, `.env.example`, `pyproject.toml`, `uv.lock`;
- все ADR files и `docs/adr/README.md`.

`delete`:

- `.github/workflows/release.yml`, `.dockerignore` только если Dockerfile больше
  не использует её (иначе keep);
- `ops/deploy_from_git.py`, `deploy_self_hosted.py`, `smoke_production.py`,
  `verify_release_provenance.py`, оба `.sh` wrapper и `ops/systemd/**`;
- `compose.production.yaml` удалять запрещено: он заменяется in place;
- `docs/operations/**`, bot-only `docs/mvp/05_BOT_INTERFACE.md`, старые R1
  implementation/test/handoff документы;
- все `tasks/CB-*`, кроме `tasks/CB-62/**`.

`replace`:

- README, project context/rules, architecture, tech stack, Release 2 README и
  parity docs, product flow/security docs, CI/pyproject/lockfile и все ссылки на
  удалённые paths.
