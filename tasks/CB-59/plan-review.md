# CB-59 — повторное ревью плана

Status: approved

Схема результата: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- Jira read-only: актуальные CB-59, CB-50 и CB-48, включая описания,
  комментарии, родителей, статусы и issue links. Связь подтверждена в обе
  стороны: CB-59 блокирует CB-50; обе задачи находятся под CB-48. CB-59 имеет
  статус `В работе`, а её Jira-область исключает production deploy, Environment
  approval, Telegram live acceptance, tag `v1.0.0` и GitHub Release.
- Полностью перечитаны после консолидированного исправления
  `tasks/CB-59/plan.md`, `tasks/CB-59/plan-source-context.md` и
  `tasks/CB-59/test-plan.md`; исходный `plan-review.md` со всеми двумя
  обязательными замечаниями также проверен построчно.
- Прочитан актуальный
  `C:/Users/User/community_bot-worktrees/CB-50/tasks/CB-50/plan-review.md`; его
  текущий точный вердикт — `Status: approved`.
- Применены `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`,
  `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `agents/README.md` и полный
  контракт `agents/plan-reviewer/*`.
- Полностью прочитан skill `database-migrations`; применимы неизменяемость уже
  выпущенных migrations, forward-only production migration и запрет schema
  downgrade как rollback приложения.
- Сверены ADR-0009, ADR-0011, `docs/mvp/TECH_STACK.md`, релевантные решения
  D-025/D-029, `docs/operations/PILOT_RUNBOOK.md` и
  `docs/operations/PILOT_CHECKLIST.md`.
- Сверены фактические `ops/restore_drill.py`, `ops/_runtime.py`,
  `src/community_bot/bootstrap/migrate.py`, `Dockerfile`,
  `compose.production.yaml`, `tests/unit/test_operations.py`, `pyproject.toml`,
  `uv.lock`, `src/community_bot/__init__.py` и migration graph.
- Git read-only: локальные `HEAD` и `origin/main`, а также remote
  `refs/heads/main` совпадают на
  `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`; ветка — `task/CB-59`.
  Migration graph линейна до единственного head `0020`; каталог migrations не
  изменён. Package metadata фактически равна `0.1.0`, а нормативный `0019`
  фактически остаётся в restore script, runbook, checklist и unit-test.

## Область задачи

Граница задачи проведена правильно. CB-59 подготавливает только repository
candidate: version metadata `1.0.0`, fail-closed restore contract, tests и
operational documentation, затем собственные implementation report, final
review, PR, CI и merge. Она не выбирает release SHA/digest, не развёртывает
production, не работает с Telegram и не создаёт tag/Release. Это соответствует
Jira и сохраняет CB-50 единственным владельцем внешней release acceptance.

Новая schema/data migration не требуется и план её правильно запрещает. Уже
развёрнутые `migrations/versions/*.py` остаются неизменяемыми; downgrade и
ручной production SQL не добавляются.

## Логика решения

Основной технический контракт спроектирован корректно:

- expected revision получается не из checkout, документации или имени файла, а
  через узкий CLI из Alembic graph того же exact immutable image, который
  валидирован `read_current_image()`;
- `docker run` использует exact identity, `--pull=never`, `--network none` и
  `--read-only`; zero/multiple heads, ненулевой exit, пустой, многострочный или
  malformed stdout отклоняются до обращения к production DB;
- production и restored `alembic_version` читаются полным набором строк и
  независимо требуют cardinality `1` и exact equality expected head; scalar
  semantics и SQL-интерполяция expected value исключены;
- production revision проверяется до `createdb`, restored revision — после
  `pg_restore` и до ledger reconciliation;
- pre-cleanup и final cleanup используют только фиксированную drill DB,
  сопровождаются отдельной проверкой отсутствия в `pg_database`, повтор
  отсутствующей DB идемпотентен, а cleanup/postcondition failure не может дать
  success;
- production DB остаётся read-only для restore tool, рабочая схема не
  переключается и не мигрируется;
- версия согласуется сразу в `pyproject.toml`, root entry `uv.lock`,
  `community_bot.__version__` и installed metadata без создания tag.

Эта схема закрывает исходный дефект лучше простой замены `0019` на `0020` и не
требует нового ADR: она реализует действующие ADR-0009/ADR-0011, не меняя
release boundary или migration policy.

## Альтернативы и риски

Отклонённые в плане альтернативы обоснованы: hardcoded `0020`, локальный
Alembic graph и mutable image tag снова создали бы drift либо потерю
provenance. Отдельный packaged CLI даёт маленькую детерминированную границу,
которую можно независимо тестировать.

Failure semantics достаточны: restore error, wrong/ambiguous revision, query
error, ledger mismatch, cleanup error и недоказанная absence postcondition дают
ненулевой результат. Матрица различает primary и cleanup failures безопасными
кодами и запрещает повтор после неустранённого cleanup failure.

Privacy boundary также сохранена: разрешены только image/revision identity,
агрегаты, UTC duration и result codes; env values, credentials, backup content,
сырые DB rows и Telegram data исключены.

## Стратегия проверки

`test-plan.md` содержательно закрывает требуемую матрицу:

- `one|zero|multiple` heads и exact immutable image invocation;
- `zero|one correct|one wrong|multiple|query error` отдельно для production и
  restored `alembic_version`;
- отсутствующий/повреждённый backup, `createdb`/`pg_restore`/key-table error,
  ledger mismatch;
- stale/absent drill DB, pre/final cleanup error, ложный успешный drop,
  primary+cleanup failure, success и повторный запуск;
- локальный disposable PostgreSQL 18 smoke S1–S5 без production credentials,
  production backup, deploy или Telegram;
- version consistency, lock consistency, documentation parity и отсутствие
  migration diff.

Для S1–S5 заданы preconditions, порядок, ожидаемые oracles, abort/resume и
evidence allowlist. Недоступность Docker честно блокирует final review, а не
подменяется статическим чтением.

Точные quality-команды теперь соответствуют этому обещанию и правилам проекта:

- `-o addopts=` отключает aggregate `--cov=community_bot` только для target
  runs, после чего `ops.restore_drill` и новый
  `community_bot.bootstrap.migration_head` измеряются раздельно с branch
  coverage, `term-missing` и порогом `90%`; покрытие одного модуля не может
  скрыть пробелы другого;
- отдельный exact-path `ty check` включает restore script, новый CLI и их
  тесты, а полный type gate дополнительно включает `src`, `tests`,
  `ops/restore_drill.py` и существующий release provenance script;
- package metadata и статические operational boundaries проверяются отдельным
  target pytest без ненужного aggregate coverage, после чего обычный полный
  `uv run pytest` снова применяет штатный repository threshold `80%`;
- baseline read-only проверка `uv run ty check ops/restore_drill.py`
  независимо повторена и прошла; актуальный `pytest-cov` подтверждает поддержку
  всех использованных `--cov`, `--cov-branch`, `--cov-report` и
  `--cov-fail-under` options. Будущие module/test paths точно перечислены в
  планируемой разнице и станут исполнимы после разрешённой реализации.

## Обязательные исправления

Обязательных исправлений нет. Оба замечания первой проверки закрыты одним
консолидированным обновлением полного пакета:

1. `plan-source-context.md` теперь явно отделяет исторический первый
   `Status: changes_requested` CB-50 от актуального повторного
   `Status: approved`, не переносит approval через dependency и правильно
   фиксирует фактическую связь `CB-59 blocks CB-50`.
2. `plan.md` и `test-plan.md` содержат согласованные, точные и раздельные
   coverage-команды для `ops.restore_drill` и packaged image-head CLI, branch
   threshold `90%`, `term-missing`, exact-path `ty check` и последующий полный
   repository gate.

## Остаточные риски

- Disposable smoke требует Linux/Docker/Compose и root-owned test env; план
  корректно считает отсутствие такой среды блокером final review.
- Preflight failure до доступного DB connection доказывает только отсутствие
  новых DB operations в данном запуске, но не фактическую absence stale DB;
  итоговый отчёт не должен записывать `drill_database_absent=true` без успешной
  postcondition query.
- Проверку неизменности migrations полезно выполнять и относительно merge base,
  а не только рабочей разницы, если lifecycle реализации отклонится от
  предусмотренного review-before-commit порядка.
- `Status: approved` разрешает переход к реализации утверждённой области CB-59,
  но не доказывает будущие test results, не заменяет implementation report и
  final review и не разрешает production, tag, GitHub Release или Telegram
  действия.
