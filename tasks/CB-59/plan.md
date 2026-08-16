# CB-59 — план подготовки воспроизводимого release-кандидата 1.0.0

## Уровень риска

Уровень 3 по ADR-0004. Изменение затрагивает production recovery gate,
неизменяемую identity release image, проверку Alembic revision, очистку
временной базы и package version перед Release 1. Ошибка здесь может дать ложное
подтверждение восстанавливаемости либо оставить служебную базу на production
host.

Новый ADR не требуется: задача реализует уже принятые ADR-0009 и ADR-0011, не
меняет форму runtime и не вводит новую политику миграций. Если реализация
потребует изменить release boundary, разрешить несколько Alembic heads или
редактировать уже выпущенную миграцию, работа останавливается до отдельного ADR
и решения владельца.

## Цель

Подготовить новый `main` к выбору release-кандидатом CB-50:

- согласовать package metadata на версии `1.0.0`, не создавая Git tag;
- заменить нормативный hardcode `0019` на fail-closed контракт, в котором
  expected Alembic head извлекается из exact immutable image текущего release;
- одинаково проверить production и restored базы: ровно одна строка
  `alembic_version`, точно равная expected head;
- сохранить ledger reconciliation, изолированное восстановление и обязательную
  идемпотентную очистку drill DB;
- синхронизировать код, тесты, runbook и checklist.

## Исходное состояние и причина

- `origin/main` на старте ветки — `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`.
- Репозиторий имеет один Alembic head `0020`; CB-50 plan review независимо
  подтверждает production migration gate `0020` для развёрнутого run 64.
- `ops/restore_drill.py`, `PILOT_RUNBOOK.md`, `PILOT_CHECKLIST.md` и статический
  unit-test всё ещё ожидают `0019`.
- `pyproject.toml`, `uv.lock` и `community_bot.__version__` содержат `0.1.0`.
- Текущий restore drill проверяет только restored revision и не доказывает
  cardinality/совпадение `alembic_version` текущей production DB.

Простая замена `0019` на `0020` не закрывает дефект: следующая forward migration
снова рассинхронизирует код и operational gate. Источником ожидания должен быть
сам exact image, который проверяется и восстанавливается.

## Область изменений

### 1. Версия пакета

- установить `1.0.0` в `pyproject.toml`;
- синхронизировать корневую запись проекта в `uv.lock` штатной командой `uv lock`;
- синхронизировать `src/community_bot/__init__.py` и добавить проверку равенства
  `community_bot.__version__`, installed metadata и `pyproject.toml`;
- подтвердить `uv lock --check`.

Версия пакета не является разрешением на создание `v1.0.0`: tag, GitHub
Release, release notes и выбор финального merge SHA остаются в CB-50.

### 2. Источник expected Alembic head

Добавить узкий read-only CLI `community-migration-head` в package image:

1. CLI читает packaged `alembic.ini` и migration graph через
   `ScriptDirectory.get_heads()`.
2. Ровно один непустой head печатается одной строкой в stdout, команда
   завершается code `0`.
3. Ноль или несколько heads завершаются ненулевым кодом с безопасным сообщением
   без выбора «первого» значения.
4. CLI не читает production environment, не подключается к БД и не изменяет
   схему.

`ops/restore_drill.py` сначала получает immutable image через существующий
`read_current_image()`, затем запускает именно этот image изолированно:

```text
docker run --rm --pull=never --network none --read-only \
  --entrypoint community-migration-head EXACT_IMAGE
```

Stdout принимается только как одна непустая строка с одним revision identifier.
Любой лишний вывод, ноль строк, несколько строк, невалидный identifier или
ненулевой exit code блокирует drill до обращения к production DB. Локальный
checkout, номер из документации, mutable tag и «последнее имя файла» не могут
быть источником expected head.

### 3. Контракт production и restored revision

Для каждой базы выполняется отдельный read-only запрос к `alembic_version` через
`psql --tuples-only --no-align`:

- `production` — база из `POSTGRES_DB` в root-owned environment;
- `restored` — только `community_bot_restore_drill`.

Парсер получает полный список строк, а не scalar с неявным выбором:

- `0` строк — failure;
- `1` строка, отличная от expected head, — failure;
- `>1` строк — failure, даже если одна из них равна expected head;
- ровно одна строка, точно равная expected head, — success.

Production revision проверяется до создания drill DB. Restored revision
проверяется после успешного `pg_restore` и до ledger reconciliation. SQL/query
error также является failure. Значение expected head передаётся как данные в
Python-сравнение и не интерполируется в исполняемый SQL.

### 4. Restore, ledger и cleanup

Порядок одного запуска:

1. Проверить backup, root-owned env и exact current image.
2. Идемпотентно удалить возможную старую drill DB через
   `dropdb --if-exists --force`; ошибка pre-cleanup блокирует продолжение.
3. Подтвердить отсутствие drill DB после pre-cleanup.
4. Получить один expected head из exact image.
5. Проверить cardinality и exact revision production DB.
6. Создать `community_bot_restore_drill` и восстановить backup.
7. Проверить cardinality и exact revision restored DB.
8. Выполнить существующую ledger/cache reconciliation и вывести только
   безопасные агрегаты.
9. В `finally` удалить drill DB и отдельным read-only запросом подтвердить её
   отсутствие в `pg_database`.

Cleanup считается успешным только если `dropdb` вернул `0` и postcondition
подтвердила отсутствие БД. Повторная очистка отсутствующей БД успешна. Любая
ошибка restore, revision, ledger, cleanup или проверки postcondition даёт
ненулевой итог; cleanup failure не маскируется более ранней ошибкой. Если
отсутствие drill DB доказать нельзя, оператор получает failure и обязан
проверить/удалить только эту именованную временную БД по runbook перед повтором.

Рабочая production DB никогда не переименовывается, не переключается, не
мигрируется и не удаляется restore-скриптом.

### 5. Документация

Обновить:

- `docs/operations/PILOT_RUNBOOK.md` — источник expected head, порядок
  production/restored проверок, failure/cleanup semantics и безопасные поля
  evidence;
- `docs/operations/PILOT_CHECKLIST.md` — отдельные поля `Expected image head`,
  `Production revision`, `Restored revision` без нормативного `0019`;
- при необходимости точечные комментарии в коде/тестах, но не исторические
  артефакты CB-49, которые корректно фиксируют факты своего времени.

## Неизменяемость миграций

По контракту `database-migrations` и действующим ADR:

- ни один файл `migrations/versions/*.py` не изменяется;
- новая schema/data migration не создаётся;
- production остаётся forward-only, `alembic downgrade` в restore/rollback не
  добавляется;
- текущая линейная graph с одним head проверяется, но не переписывается;
- restored dump не становится источником «правильной» схемы: он обязан
  соответствовать release image.

## Файлы и компоненты

Планируемая разница:

- `pyproject.toml`;
- `uv.lock`;
- `src/community_bot/__init__.py`;
- новый узкий модуль в `src/community_bot/bootstrap/` для
  `community-migration-head`;
- `ops/restore_drill.py`;
- `tests/unit/test_restore_drill.py` — поведенческая fault matrix;
- `tests/unit/test_migration_head.py` — exact-one CLI и безопасные
  `one|zero|multiple` outcomes;
- `tests/unit/test_operations.py` — статические production boundaries без
  hardcoded revision;
- `tests/unit/test_package_metadata.py` — точечная version consistency;
- `docs/operations/PILOT_RUNBOOK.md`;
- `docs/operations/PILOT_CHECKLIST.md`;
- `tasks/CB-59/implementation-report.md` и `tasks/CB-59/final-review.md` после
  реализации.

Имена новых runtime-команд и функций не содержат ключ Jira.

## Шаги реализации

1. Получить независимое review полного пакета `plan.md`,
   `plan-source-context.md`, `test-plan.md`; для уровня 3 требуется
   `Status: approved` до кода.
2. Реализовать и отдельно протестировать single-head CLI на `one|zero|multiple`
   graph heads.
3. Обновить package version и lock metadata, добавить consistency test.
4. Разделить restore orchestration на тестируемые операции: получение image
   head, чтение полного списка DB revisions, exact comparison, ledger check,
   cleanup и проверка отсутствия.
5. Реализовать fail-closed порядок без изменения production schema и
   миграционных файлов.
6. Добавить автоматическую fault matrix и локальный disposable operational
   smoke по `test-plan.md`.
7. Обновить runbook/checklist и удалить нормативный hardcode `0019` только из
   актуальных operational surfaces/tests.
8. Выполнить два отдельных целевых coverage gate: каждый измеряет свой
   изменяемый модуль (`ops/restore_drill.py` и packaged image-head CLI) с branch
   coverage не ниже `90%` и `term-missing`; затем закрыть непокрытые ветки либо
   явно обосновать только действительно недостижимый defensive path до final
   review. Отдельно выполнить exact-path `ty check`, включающий restore script,
   новый модуль и их тесты. После этого один раз запустить полный repository
   gate; после последующего изменения кода/тестов полный gate повторяется.
9. Создать `implementation-report.md` с доказательством каждого критерия и
   получить независимый `final-review.md` со `Status: approved`.
10. После успешных gates выполнить штатные commit, push, PR, CI/review и merge в
    `main`. CB-50 сможет выбрать только новый merge commit `origin/main`.

## Стратегия проверки

Полная матрица находится в `test-plan.md`. Минимальный набор:

- `one|zero|multiple` heads внутри image CLI;
- exact image identity из `current-image`, без локального Alembic graph;
- `zero|one correct|one wrong|multiple` rows отдельно для production и
  restored `alembic_version`;
- `pg_restore` failure;
- ledger mismatch;
- pre-cleanup, final cleanup и postcondition failure;
- отсутствие drill DB после success и после каждого failure, где cleanup
  выполним; cleanup error сам остаётся fail-closed результатом;
- повторный запуск и cleanup отсутствующей БД;
- package metadata `1.0.0` и lock consistency;
- отсутствие изменений migration files.

Команды финального локального gate:

```text
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check ops/restore_drill.py src/community_bot/bootstrap/migration_head.py tests/unit/test_restore_drill.py tests/unit/test_migration_head.py tests/unit/test_package_metadata.py
uv run pytest -o addopts= tests/unit/test_restore_drill.py --strict-config --strict-markers --cov=ops.restore_drill --cov-branch --cov-report=term-missing --cov-fail-under=90
uv run pytest -o addopts= tests/unit/test_migration_head.py --strict-config --strict-markers --cov=community_bot.bootstrap.migration_head --cov-branch --cov-report=term-missing --cov-fail-under=90
uv run pytest -o addopts= tests/unit/test_package_metadata.py tests/unit/test_operations.py --strict-config --strict-markers
uv run ty check src tests ops/restore_drill.py ops/verify_release_provenance.py
uv run pytest
uv run alembic heads
git diff --check
```

`-o addopts=` намеренно отключает глобальные pytest `addopts` только в двух
target coverage commands: иначе автоматический `--cov=community_bot` измерял бы
весь пакет и не давал бы отдельного результата host-side
`ops/restore_drill.py`. Каждый изменяемый модуль запускается своей командой,
поэтому общий процент одного модуля не может компенсировать пробелы другого.
Полный `uv run pytest` после этого использует обычную конфигурацию проекта и
порог `80%` для продукта.

Дополнительно:

- `uv run alembic heads` должен вывести ровно один `0020 (head)` для текущего
  baseline; это доказательство текущего факта, не нормативный hardcode кода;
- `git diff --name-only -- migrations/versions` должен быть пуст;
- `docker compose config` выполняется при изменении Compose/YAML; в плановой
  области YAML не требуется;
- secret-like scan выполняется по diff без вывода значений секретов;
- локальный disposable restore smoke не использует production environment,
  production backup и Telegram.

## Критерии приёмки и доказательства

| Критерий CB-59 | Реализация | Проверка |
|---|---|---|
| Package metadata равна `1.0.0` | `pyproject.toml`, `uv.lock`, `__version__` | consistency test, `uv lock --check` |
| Нет нормативного номера миграции | expected head из exact immutable image | поиск актуальных surfaces, image-head tests |
| Zero/multiple image heads отклоняются | `get_heads()` + exact-one CLI | unit matrix и отдельный branch coverage `>=90%` |
| Production DB имеет ровно одну expected revision | full-row query до drill | unit/fault matrix и disposable smoke |
| Restored DB имеет ровно одну expected revision | full-row query после restore | unit/fault matrix и disposable smoke |
| Wrong revision отклоняется | exact string comparison | отдельные production/restored cases |
| Ledger mismatch и restore error дают failure | restored ledger gate и preserved subprocess failure | injected failures и disposable corrupt dump |
| Cleanup идемпотентен и доказуем | `--if-exists --force` + absence postcondition | success/failure/replay matrix и restore branch coverage `>=90%` |
| Runbook, checklist и tests описывают одно правило | synchronized docs/tests | semantic review и `rg` |
| Выпущенные migrations неизменны | migration directory вне diff | `git diff --name-only -- migrations/versions` |
| Нет deploy/tag/live действий | только local disposable checks | implementation report и external-state audit |

## Риски и меры снижения

- **Проверяется не тот image.** Image берётся только из валидированного
  `current-image`; CLI запускается через `--pull=never`, без mutable tag и сети.
- **Несколько heads случайно принимаются.** Используется `get_heads()` и
  exact-one cardinality, а не `get_current_head()` с неявным предположением.
- **Несколько строк DB скрываются scalar-запросом.** Читается полный список
  строк, cardinality проверяется в Python до exact comparison.
- **Primary failure скрывает cleanup failure.** Итог остаётся failure, обе
  безопасные причины различимы; success невозможен без доказанного отсутствия
  drill DB.
- **Скрипт затрагивает production DB.** Production path содержит только SELECT;
  create/drop адресованы фиксированному `community_bot_restore_drill`.
- **Drill выводит приватные данные.** Разрешены revision, aggregate counts,
  mismatch count, UTC duration и технические коды; строки участников, ledger и
  env values не выводятся.
- **Version bump ошибочно воспринимается как release.** Документация и отчёт
  явно фиксируют: CB-59 не создаёт tag/Release и не выбирает candidate SHA.
- **Rollback кода возвращает broken hardcode.** При проблеме PR не сливается;
  после merge rollback — новый forward fix/PR. Deployed migrations не
  редактируются и schema downgrade не выполняется.

## Вне области

- production deployment и GitHub Environment approval;
- запуск на production server или чтение production `.env`/backup;
- Telegram probe, чтение/отправка сообщений и live acceptance;
- annotated tag `v1.0.0`, GitHub Release и release notes;
- выбор финального Release 1 commit/digest и merge freeze;
- создание, изменение либо downgrade Alembic migration;
- изменение RPO `<=24h`, RTO `<=4h`, retention семь суток или принятого риска
  same-host backup;
- Release 2 runtime и любые продуктовые правила.

## Условия готовности

- полный плановый пакет имеет независимый `Status: approved`;
- каждый критерий CB-59 имеет фактическое доказательство в
  `implementation-report.md`;
- целевые, operational и полный CI-equivalent gates успешны;
- `final-review.md` содержит `Status: approved` на фактическую финальную разницу;
- ветка `task/CB-59` прошла PR/CI/review и merge;
- production deploy, tag и Telegram действия честно отмечены как не
  выполнявшиеся, а CB-50 продолжает release acceptance с нового `origin/main`.
