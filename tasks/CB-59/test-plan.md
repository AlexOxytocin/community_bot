# CB-59 — план проверки version и restore contract

## Почему нужен отдельный test plan

Текущий `tests/unit/test_operations.py` проверяет наличие строк в operational
files, но не доказывает порядок subprocess-вызовов, cardinality
`alembic_version`, failure propagation и фактическую очистку временной БД.
Автоматические тесты не покрывают operational behavior полностью. Для задачи
уровня 3 нужен отдельный план, который сочетает детерминированную fault matrix и
disposable Docker/PostgreSQL smoke без production доступа.

## Safety boundary

- Используется только локальный disposable root/Compose project и искусственный
  backup.
- Production host, `/opt/community-bot`, production `.env`, реальные backup и
  GitHub Environment не используются.
- Telegram profiles, сообщения и live acceptance не затрагиваются.
- Drill DB имеет только фиксированное имя `community_bot_restore_drill` внутри
  disposable PostgreSQL.
- Ни один test не запускает Alembic downgrade на production и не изменяет
  `migrations/versions`.
- Evidence не содержит env values, connection strings, dump content и строки
  участников.

## Preconditions

1. Worktree находится на `task/CB-59`, diff ограничен CB-59.
2. Для disposable smoke доступен изолированный Linux host/runner с Docker,
   Compose и возможностью создать root-owned `0600` test env через `sudo`.
3. `uv sync --locked --all-groups` успешен.
4. Локальная migration graph имеет один текущий head.
5. Test image собран из текущего worktree и адресуется immutable local image ID,
   не mutable tag.
6. Disposable environment содержит только synthetic values; его root path
   передаётся через `COMMUNITY_BOT_ROOT`, а env действительно имеет owner
   `root` и mode `0600`, без ослабления production validator.

Если Docker недоступен, automated fault matrix выполняется полностью, а
operational smoke отмечается `blocked`; final review не подменяет этот gate
статическим чтением кода.

## Автоматическая матрица

### A. Package version

| Случай | Ожидаемый результат |
|---|---|
| `pyproject.toml`, installed metadata и `community_bot.__version__` | все равны `1.0.0` |
| root project entry в `uv.lock` | равна `1.0.0` |
| `uv lock --check` | code `0`, lock не меняется |

### B. Packaged image head

| Graph внутри CLI | Ожидаемый результат |
|---|---|
| один head | одна строка revision, code `0` |
| ноль heads | безопасная ошибка, nonzero |
| два heads | безопасная ошибка, nonzero; ни один не выбран |
| stdout пустой/две строки/с whitespace-only | host parser отклоняет |
| реальный child пишет `CRLF`, одиночный `CR` или invalid bytes | bytes transport сохраняет вывод; image/DB/cleanup gates отклоняют |
| malformed revision identifier | host parser отклоняет |
| mutable/invalid current image | `read_current_image()` отклоняет до Docker |
| exact immutable image | вызов содержит `--pull=never --network none --read-only` и exact identity |

Проверяется, что restore code не вызывает локальный `uv run alembic heads` и не
читает revision из имени migration file или документации.

### C. Production `alembic_version`

Для каждого случая pre-cleanup уже подтвердил отсутствие stale drill DB, а
revision assert выполняется до `createdb`/`pg_restore`:

| Строки | Ожидаемый результат |
|---|---|
| `[]` | failure, drill DB не создаётся |
| `[expected]` | переход к create/restore |
| `[wrong]` | failure, drill DB не создаётся |
| `[expected, other]` | failure, drill DB не создаётся |
| query error | failure, drill DB не создаётся |

### D. Restored `alembic_version`

После успешного `pg_restore`:

| Строки | Ожидаемый результат |
|---|---|
| `[]` | failure, final cleanup, DB отсутствует |
| `[expected]` | переход к ledger check |
| `[wrong]` | failure, final cleanup, DB отсутствует |
| `[expected, other]` | failure, final cleanup, DB отсутствует |
| query error | failure, final cleanup, DB отсутствует |

### E. Restore и ledger

| Случай | Ожидаемый результат |
|---|---|
| backup отсутствует/пуст | failure до DB operations |
| `createdb` failure | nonzero, cleanup attempted, absence checked |
| `pg_restore` failure | nonzero, cleanup, DB отсутствует |
| key-table query failure | nonzero, cleanup, DB отсутствует |
| ledger/cache mismatch | nonzero, cleanup, DB отсутствует |
| ledger/cache exact | `ledger_mismatch_count = 0`, безопасные aggregate counts |

### F. Cleanup и повтор

| Случай | Ожидаемый результат |
|---|---|
| stale drill DB до запуска | pre-cleanup удаляет её и подтверждает отсутствие |
| drill DB уже отсутствует | `--if-exists` даёт idempotent success |
| pre-cleanup command error | abort до create/restore |
| final cleanup command error | итог failure независимо от primary result |
| drop вернул `0`, но DB ещё видна | postcondition failure |
| primary failure + cleanup success | итог failure, DB отсутствует |
| primary failure + cleanup failure | итог failure, обе причины различимы безопасными codes |
| полный success | code `0` только после доказанного отсутствия DB |
| второй идентичный запуск | тот же исход, stale DB отсутствует |

Fault injection выполняется через тестируемый command seam/monkeypatch без
реальных внешних изменений. Тесты проверяют не только exit code, но порядок,
точную target DB и запрет операций изменения production DB.

Transport-level regression не подменяет уже декодированный `str`: настоящий
дочерний процесс пишет в `sys.stdout.buffer` raw `CRLF`, одиночный `CR` и
invalid UTF-8. Тест проводит фактически захваченные bytes через image-head,
DB-revision и cleanup-count gates, чтобы universal-newline normalization не
могла скрыть запрещённый протокол.

## Disposable operational smoke

### S1. Успешный путь

1. Собрать current branch image и получить immutable local image ID.
2. Поднять disposable PostgreSQL 18 в отдельном Compose project.
3. Выполнить `alembic upgrade head`, создать минимальные synthetic ledger/cache
   данные с нулевым mismatch.
4. Создать local custom-format backup.
5. Записать immutable image ID в disposable `shared/releases/current-image` и
   создать через `sudo` synthetic root-owned test env `0600` без production
   values.
6. Запустить `restore_drill.py`.
7. Зафиксировать expected image head, production/restored exact revision,
   `ledger_mismatch_count = 0`, code `0` и отсутствие
   `community_bot_restore_drill` в `pg_database`.
8. Повторить запуск тем же backup; получить тот же success и отсутствие DB.

### S2. Production revision failures

На disposable production DB поочерёдно создать zero, wrong и multiple rows в
`alembic_version`. Каждый запуск должен завершиться до restore и не оставить
drill DB. После каждого случая disposable DB возвращается в correct state
штатным synthetic setup, не изменением migration files.

### S3. Restored revision failures

Создать три synthetic dump: empty revision, wrong revision и multiple rows.
Production DB при этом остаётся correct. Каждый dump должен пройти `pg_restore`,
затем получить revision failure и обязательную очистку drill DB.

### S4. Ledger mismatch и damaged backup

- Dump с намеренно рассогласованным synthetic cache/ledger восстанавливается,
  отклоняется ledger gate и очищается.
- Невалидный non-empty dump даёт `pg_restore` failure и очищается.

### S5. Cleanup postcondition

Нормальный success/failure smoke подтверждает реальное отсутствие DB запросом к
`pg_database`. Cleanup command failure и «drop success, DB remains» безопасно
инъецируются автоматическим тестом: намеренно ломать права либо удерживать
production-like DB ради этой проверки не требуется.

## Команды

Целевые быстрые проверки:

```text
uv lock --check
uv run ruff format --check src/community_bot ops/restore_drill.py tests/unit
uv run ruff check src/community_bot ops/restore_drill.py tests/unit
uv run ty check ops/restore_drill.py src/community_bot/bootstrap/migration_head.py tests/unit/test_restore_drill.py tests/unit/test_migration_head.py tests/unit/test_package_metadata.py
uv run pytest -o addopts= tests/unit/test_restore_drill.py --strict-config --strict-markers --cov=ops.restore_drill --cov-branch --cov-report=term-missing --cov-fail-under=90
uv run pytest -o addopts= tests/unit/test_migration_head.py --strict-config --strict-markers --cov=community_bot.bootstrap.migration_head --cov-branch --cov-report=term-missing --cov-fail-under=90
uv run pytest -o addopts= tests/unit/test_package_metadata.py tests/unit/test_operations.py --strict-config --strict-markers
```

Две coverage-команды намеренно выполняются раздельно. `-o addopts=` убирает
глобальный `--cov=community_bot` и его aggregate threshold только для targeted
run; затем каждая команда измеряет line/branch coverage ровно своего модуля,
показывает пропуски через `term-missing` и требует не менее `90%`. Найденные
непокрытые error/cleanup branches добавляются в fault matrix до финального
review; один модуль не компенсирует низкое покрытие другого.

После закрытия целевого coverage:

```text
uv run ty check src tests ops/restore_drill.py ops/verify_release_provenance.py
uv run pytest
uv run alembic heads
docker compose config
git diff --check
```

На исходном baseline до реализации уже подтверждено:

```text
uv run ty check ops/restore_drill.py
```

Команда прошла. Coverage toolchain отдельно распознал
`ops/restore_drill.py` и измерил baseline `37%` при запуске только CLI `--help`;
низкое число не является gate результата, а доказывает необходимость новых
поведенческих тестов. Точные target pytest-команды станут исполнимы после
создания предусмотренных планом test modules; заменять их сейчас временными
тестами нельзя.

Дополнительные проверки diff:

```text
git diff --name-only -- migrations/versions
rg -n --fixed-strings "0019" ops docs/operations tests/unit
```

Первый результат обязан быть пустым. Второй не должен находить нормативный
hardcode в актуальных operational surfaces; исторические migration filenames и
артефакты завершённых задач не являются дефектом.

## Abort и resume

- Любой ambiguous image head, production revision failure или pre-cleanup
  failure останавливает запуск до создания drill DB.
- Любая ошибка после `createdb` переходит в cleanup; успех не объявляется до
  absence postcondition.
- При cleanup failure повтор restore запрещён до безопасной проверки и удаления
  только `community_bot_restore_drill`.
- Повтор после устранения причины начинает весь preflight заново и не использует
  прошлое expected-head/DB evidence.
- Ни один failure path не вызывает deploy, rollback image, Alembic downgrade,
  tag или Telegram action.

## Evidence allowlist

В `implementation-report.md` допускаются:

- branch/commit и immutable local test image ID в сокращённом виде;
- package version;
- expected, production и restored revision;
- result code каждого именованного scenario;
- aggregate row counts и `ledger_mismatch_count`;
- UTC duration;
- факт `drill_database_absent=true`;
- команды и сводка test results.

Запрещены env values, passwords, URLs с credentials, backup content,
participant identifiers, строки ledger, Telegram data и raw subprocess dumps с
потенциальными секретами.

## Критерий прохождения

- Все cases A–F зелёные.
- S1–S5 выполнены в disposable environment; cleanup failure branch закрыт
  детерминированной fault injection.
- Один Alembic head, migrations directory вне diff.
- Целевой и полный test gates успешны.
- Runbook/checklist семантически совпадают с проверяемым контрактом.
- Никакой production, tag, GitHub Release или Telegram activity не выполнялось.
