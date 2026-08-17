# CB-51 — план компактного backend с полным parity

## Результат

Заменить текущую раздутую реализацию небольшим feature-oriented монолитом и
compact schema, не изменив ни одного бизнес-исхода. Работа выполняется slices:
старый owner удаляется в том же slice, где его новый owner прошёл exact oracle.

Уровень риска: `3`. Нового ADR не требуется: структурное решение принято в
ADR-0017. Ветка не merge, пока все backend capability CB-51 не имеют реальные
passing nodes; `AUTH` и `MINI_APP_REACHABILITY` остаются `planned_external` с
явными владельцами CB-52 и CB-57.

## Архитектурная граница

- один Python application и одна PostgreSQL;
- feature modules работают напрямую с `AsyncSession`;
- state, ledger, audit и outbox intent фиксируются одной транзакцией;
- typed JSON используется только для редких versioned payload;
- query-critical actor/state/subject/time/key остаются constrained columns;
- `jsonschema.Draft202012Validator` сохраняет historical template semantics;
- broker/cache/command bus/repository/UoW/DI framework не добавляются.

## Slice 1 — исполнимый delete gate

Файлы:

- `ops/check_refactor_contract.py`;
- `tests/architecture/test_refactor_contract.py`;
- точечное расширение `tasks/CB-64/parity-map.json` только фактическими
  `status`, real node IDs и measured totals.

Поведение:

- стандартной библиотекой проверить JSON schema/version и уникальные IDs;
- доказать 43/43 mapping actual `__tablename__` → table link;
- проверить все capability/constraint links и существование old evidence;
- считать production/test/migration/docs LOC, test functions, tables и direct
  dependencies из tracked tree;
- режим `--report` показывает baseline/current/delta и не маскирует превышения;
- режим `--enforce-final` падает при unmapped/non-passing capability или
  принятом ceiling violation;
- planned future nodes до реализации разрешены только со статусом `planned`;
  удаление legacy owner требует `passing` и реально собираемый node ID.

Gate: `uv run pytest -o addopts="-ra --strict-config --strict-markers"
tests/architecture/test_refactor_contract.py -q
--cov=ops.check_refactor_contract --cov-branch --cov-report=term-missing
--cov-fail-under=0`, затем `uv run pytest tests/unit tests/architecture
tests/documentation tests/smoke -q --no-cov`, formatter/lint/type и чистый diff.
Stop: validator требует новую dependency или не может однозначно сопоставить
tracked paths. Rollback: удалить два новых файла; runtime/schema не изменены.

## Slice 2 — compact schema и importer spike

Файлы:

- временный side-by-side compact model/migration/import module;
- scenario tests для constraints C01–C11;
- read-only inventory/import и точечное усиление существующих
  `ops/backup_postgres.py`/`ops/restore_drill.py`: потоковый encrypted backup,
  SHA-256 manifest и hash-checked restore без plaintext dump.

Целевые owners: `members`, `invitations`, `sessions`,
`product_config_versions`, `tasks`, `assignments`, `account_transactions`,
`reputation_events`, `moderation_cases`, `operations`, `outbox_events`;
двенадцатая таблица допустима только при измеренном упрощении invariant/query.

До импорта каждая строка получает provenance `public`, `synthetic` или
`ambiguous`. `ambiguous` останавливает перенос: importer ничего не угадывает по
member ID, времени или названию. Test-run quarantine строится как transitive
closure:

- roots: `task_creation_drafts.test_run_id IS NOT NULL` и
  `tasks.test_run_id IS NOT NULL`;
- dependents: assignments, cancellation request/response, result/submission
  versions/drafts, disputes/cases/evidence/resolutions/appeals, reliability,
  ledger rows, audit и outbox/notifications, которые ссылаются на root task,
  assignment или case;
- `test_runs`, participants и весь closure экспортируются в отдельный archive
  manifest с row counts/checksums, но не попадают в compact DB;
- сами members сохраняются, потому что test-run participants являются обычными
  зарегистрированными accounts; импортируются только public identity/profile/
  role/status, а cached credit/experience/level/karma/reliability/risk summaries
  пересчитываются из импортированных public ledger/reputation/case rows;
- любой зависимый row без классифицированного пути к root либо public row с
  ненулевой test-run связью останавливает import.

Source подключается отдельной read-only ролью с
`default_transaction_read_only=on`; importer не получает DDL/DML privileges.
До и после import сравниваются database identity, Alembic head, row counts и
order-independent logical checksums канонических полей каждой source table.
Физические bytes рабочей PostgreSQL не сравниваются. Backup создаётся потоком
`pg_dump` → `gpg` сразу в зашифрованный файл во внешнем root-owned каталоге
`COMMUNITY_BOT_SECURE_ARTIFACT_DIR`, разрешённом вне repository root. Пароль
читается `gpg` только из secret-файла вне git; plaintext dump не создаётся.
Python ops создаёт SHA-256 manifest зашифрованного файла, а restore сначала
проверяет hash и затем потоково расшифровывает его в `pg_restore`.

Gate: `uv run pytest -o addopts="-ra --strict-config --strict-markers"
tests/scenarios/test_migration.py -q --cov=community_bot.compact_import
--cov-branch --cov-report=term-missing --cov-fail-under=0`, empty DB migration,
downgrade до чистой DB до первой mutation, 43/43 import transformation,
quarantine/provenance closure с нулём `ambiguous`, два последовательных запуска
`apply` с проверкой `second_run_mutations=0`, source DB identity/head/counts/
logical checksums unchanged, per-member ledger/experience и state/history
checksums совпадают, а derived member summaries пересчитаны только из public
rows. Stop: любой
constraint требует generic event framework или JSON скрывает query-critical
поле. Rollback: удалить отдельную compact DB и spike code; legacy DB/runtime
остаются untouched.

## Slice 3 — members, auth primitives и operations

Перенести invitation/application/profile/roles/status/effective sanction,
starting grant, sessions, operation exact replay и audit. Durable state и
outbox intent коммитятся атомарно. Этот slice переводит внутренние session/
operation primitives в `backend_ready`; `REGISTRATION`, `MEMBERS` и
`AUDIT_IDEMPOTENCY` получают passing exact nodes, после чего удаляются только
их superseded protocols/UoW/adapters и transport-only receipts. `AUTH` не
становится `passing`: Telegram initData/Origin delivery остаётся
`planned_external` до CB-52. Conversation FSM и old UI остаются неизменёнными
dormant owners до `MINI_APP_REACHABILITY` в CB-57 и не блокируют backend merge
CB-51.

Gate: `uv run pytest -o addopts="-ra --strict-config --strict-markers"
tests/scenarios/test_auth_members.py tests/scenarios/test_operations.py -q
--cov=community_bot.members --cov=community_bot.operations --cov-branch
--cov-report=term-missing --cov-fail-under=0`, exact cases,
concurrency/fault/restart и full suite.
Stop: любой permission/status/audit исход расходится. Rollback: последний
зелёный slice commit и отдельная compact DB.

## Slice 4 — catalog, tasks и economy

Перенести config/catalog/template Draft 2020-12 validation, все durable drafts,
member/group/community tasks, assignments, cancellations, result versions,
deadlines, full/partial/reject/dispute handoff и весь ledger/reversal набор.

Gate: `uv run pytest -o addopts="-ra --strict-config --strict-markers"
tests/scenarios/test_drafts.py tests/scenarios/test_tasks.py
tests/scenarios/test_economy.py tests/scenarios/test_config_reputation.py -q
--cov=community_bot.tasks --cov=community_bot.config --cov-branch
--cov-report=term-missing --cov-fail-under=0`, `CATALOG_CONFIG`,
task/draft/deadline/economy/reversal exact oracles,
last-slot/approve-cancel/config-activation races, targeted coverage и full suite.
Stop: несовпадение schema validation, slot, reserve, settlement, revision или
deadline. Rollback: последний зелёный slice commit; source DB untouched.

## Slice 5 — reputation, moderation и notifications

Перенести levels/leaderboard, karma/history/privacy, reliability/corrections,
disputes/evidence/resolutions/appeals, sanctions, risk signals, interaction
alerts/private notes/penalties, outbox/reminders/retry/finalizers.

Gate: `uv run pytest -o addopts="-ra --strict-config --strict-markers"
tests/scenarios/test_config_reputation.py tests/scenarios/test_moderation.py
tests/scenarios/test_notifications.py -q --cov=community_bot.reputation
--cov=community_bot.moderation --cov=community_bot.notifications --cov-branch
--cov-report=term-missing --cov-fail-under=0`, все оставшиеся exact oracles,
privacy/log scan, retry/restart/concurrency и full suite. Stop: теряется append-only chain,
conflict/privacy boundary или notification dedupe. Rollback: последний зелёный
slice commit; compact DB backup.

## Slice 6 — удалить superseded tree и доказать ceilings

- не удалять old Telegram handlers/long polling/callback/FSM runtime в CB-51:
  их физическое удаление выполняется после passing `MINI_APP_REACHABILITY` в
  CB-57; CB-51 не добавляет им compatibility code и не меняет их;
- удалить старые service/protocol/UoW/adapters/models/migrations после import
  reconciliation;
- заменить 297 повторяющихся tests на 53–68 scenario tests;
- консолидировать living docs только после переноса каждого актуального правила;
- удалить временный side-by-side код и compatibility names.

Final ceilings: backend/API ≤10 000 Python LOC, tests ≤80/5 000 LOC, schema
≤12, dependencies ≤8, net deletion ≥18 000 строк. Если parity не помещается,
ceiling пересматривается до функции.

Gate: `uv run python ops/check_refactor_contract.py --enforce-final --scope
backend`, все backend parity statuses `passing`,
`AUTH` и `MINI_APP_REACHABILITY` явно `planned_external` с владельцами CB-52 и
CB-57, 0 legacy backend unmapped paths,
full PostgreSQL suite, migration/import/restore, formatter/lint/type, secrets,
independent final review. Rollback: последний зелёный slice commit; до cutover
legacy runtime/database остаются рабочими.

Исполнимый data gate в PowerShell, где `DATABASE_URL` заранее указывает только
на isolated compact DB, source/target URLs переданы через secret environment,
а `COMMUNITY_BOT_SECURE_ARTIFACT_DIR` — абсолютный root-owned каталог вне
repository root с ACL только для deployment owner:

```powershell
$secureRoot = (Resolve-Path -LiteralPath $env:COMMUNITY_BOT_SECURE_ARTIFACT_DIR).Path
uv run python ops/backup_postgres.py --encrypted-output "$secureRoot/source.dump.gpg" --sha256-manifest "$secureRoot/source.dump.gpg.sha256" --gpg-passphrase-file $env:COMMUNITY_BOT_BACKUP_PASSPHRASE_FILE
uv run python ops/restore_drill.py "$secureRoot/source.dump.gpg" --sha256-manifest "$secureRoot/source.dump.gpg.sha256" --gpg-passphrase-file $env:COMMUNITY_BOT_BACKUP_PASSPHRASE_FILE
uv run python -m community_bot.compact_import inventory --output "$secureRoot/cb51-inventory.json" --quarantine "$secureRoot/cb51-quarantine.json"
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run python -m community_bot.compact_import apply --inventory "$secureRoot/cb51-inventory.json" --quarantine "$secureRoot/cb51-quarantine.json"
uv run python -m community_bot.compact_import verify --inventory "$secureRoot/cb51-inventory.json" --quarantine "$secureRoot/cb51-quarantine.json"
uv run python -m community_bot.compact_import apply --inventory "$secureRoot/cb51-inventory.json" --quarantine "$secureRoot/cb51-quarantine.json" --expect-mutations 0
uv run python -m community_bot.compact_import verify --inventory "$secureRoot/cb51-inventory.json" --quarantine "$secureRoot/cb51-quarantine.json" --expect-rerun-mutations 0
```

Ops прекращает работу, если secure artifact root находится внутри repository,
не имеет owner-only ACL, `gpg`/secret-файл недоступны или manifest hash не
совпадает. Importer прекращает работу, если source connection не read-only,
target database identity совпадает с source, provenance содержит `ambiguous`
или второй `apply` изменил хотя бы одну строку.

## Проверки каждого slice

1. exact scenario nodes из parity map;
2. точная targeted команда соответствующего slice выше с явным `addopts`
   override и `--cov-fail-under=0`, чтобы global coverage не подменял targeted
   evidence;
3. `uv run pytest tests -q --no-cov` после targeted evidence;
4. `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`;
5. `uv run python ops/check_refactor_contract.py --report`;
6. PostgreSQL/migration/import gate, если slice меняет data path;
7. `git diff --check`;
8. `uv run python ops/check_refactor_contract.py --scan-secrets`.

## Не входит

- FastAPI routes/session auth delivery — CB-52, кроме необходимых внутренних
  session/operation data primitives;
- web UI — CB-53—CB-55;
- production cutover — CB-56;
- release acceptance — CB-57;
- новый backlog, microservices, broker, Redis, React/Vite или generic framework.
