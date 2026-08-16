# CB-59 — отчёт о реализации

## Статус

Реализация утверждённого плана и последний разрешённый R-008 remediation-цикл
после двух `Status: changes_requested` завершены и локально проверены. Изменение
готово к третьему и последнему независимому `final-review`, но этот отчёт не является таким review
и не разрешает commit, push, PR, merge, deploy, tag `v1.0.0`, GitHub Release
или Telegram live acceptance. Reviewer-owned `final-review.md` и оба
`final-review-attempt-*.md` при исправлении не изменялись. Условия terminal stop
при ещё одном неуспешном review закреплены в `problem-escalation.md`.

Уровень риска остаётся 3 по ADR-0004: изменён production recovery gate. Новая
schema/data migration не создавалась, ни один выпущенный файл
`migrations/versions/*.py` не изменён.

## Что реализовано

- Package metadata синхронизирована на `1.0.0` в `pyproject.toml`, корневой
  записи `uv.lock`, `community_bot.__version__` и installed metadata.
- Добавлена package-команда `community-migration-head`. Она читает packaged
  Alembic graph через `ScriptDirectory.get_heads()`, принимает только один
  валидный head и при нуле, нескольких heads, malformed identifier либо ошибке
  graph loader возвращает безопасный nonzero без раскрытия внутренних деталей.
- `ops/restore_drill.py` больше не использует нормативный номер migration.
  Expected head получается только из exact immutable image командой с
  `--pull=never --network none --read-only`.
- До первого cleanup, Docker либо DB subprocess проверяется, что configured
  production DB не совпадает с фиксированной `community_bot_restore_drill`.
  Коллизия останавливает запуск без side effects.
- Узкий subprocess seam сохраняет исходные stdout bytes без `text=True`,
  decoding и universal-newline conversion. Image contract принимает только
  ASCII revision `REVISION` или `REVISION\n`; padding, CR, CRLF, invalid bytes,
  blank/whitespace rows, второй LF и любой дополнительный вывод отклоняются.
- До `createdb` production DB read-only запросом проверяется на ровно одну
  revision, равную expected image head. После `pg_restore` тот же exact-one
  контракт независимо применяется к restored DB до ledger reconciliation.
  DB parser остаётся bytes-first, удаляет только один терминальный LF и
  сохраняет все исходные rows, CR и whitespace, поэтому padded,
  blank-plus-valid, CR/CRLF и invalid-byte значения не нормализуются в success.
  Cleanup count проверяется тем же способом как одна raw row `0` или `1`.
- Pre-cleanup и final cleanup используют только фиксированную
  `community_bot_restore_drill`, `dropdb --if-exists --force` и отдельную
  проверку отсутствия в `pg_database`. Primary и cleanup failures остаются
  ненулевыми и различимы безопасными техническими маркерами.
- Сохранены ledger/cache reconciliation и безопасные агрегаты; production DB
  не мигрируется, не переключается и не удаляется.
- `PILOT_RUNBOOK.md` и `PILOT_CHECKLIST.md` синхронизированы с image-derived
  expected head, отдельными production/restored revisions и cleanup
  postcondition.

## TDD evidence

Сначала были добавлены новые поведенческие тесты и выполнена команда:

```text
uv run pytest -o addopts= tests/unit/test_migration_head.py tests/unit/test_restore_drill.py tests/unit/test_package_metadata.py tests/unit/test_operations.py --strict-config --strict-markers
```

Зафиксирован ожидаемый red: collection завершился code `1` с `ImportError`,
поскольку модуль `community_bot.bootstrap.migration_head` ещё отсутствовал.
После этого добавлена минимальная реализация и матрица стала зелёной.

После первого final review выполнен второй TDD-цикл. Сначала добавлены tests
для production-name collision, raw whitespace/cardinality, missing/empty
backup и production/restored query failures. На старой реализации target run
дал ожидаемый red: `37 failed, 38 passed`; failures воспроизвели отсутствие raw
seam, принятие нормализованных значений и достижение cleanup/head/DB boundary
при коллизии. После минимальной remediation та же матрица стала зелёной.

После второго final review выполнен третий, последний разрешённый R-008
TDD-цикл. Сначала tests были переведены на bytes и добавлены реальные child
process regressions для `CRLF`, одиночного `CR` и invalid bytes. До изменения
transport команда

```text
uv run pytest -o addopts= tests/unit/test_restore_drill.py --strict-config --strict-markers -q
```

дала ожидаемый red: `63 failed, 28 passed`. Failures доказали отсутствие raw
bytes seam и несовпадение bytes DB rows со старым строковым contract. После
единого bytes-first исправления тот же run дал `91 passed`.

## Автоматическая fault matrix

`tests/unit/test_restore_drill.py` содержит 91 сценарий:

- реальные child subprocess stdout bytes без нормализации; exact image
  invocation, пустой, padded, CR, CRLF, invalid-byte, blank-extra,
  многострочный и malformed stdout, Docker failure;
- полный список revision rows с сохранением padding/blank cardinality, query
  error и `zero|one correct|one wrong|many`;
- missing и empty backup до environment/DB operations;
- коллизия production/drill DB до cleanup, image-head и DB boundaries;
- порядок pre-cleanup → image head → production revision → create/restore →
  restored revision → ledger → final cleanup;
- отдельные production/restored revision query, `createdb`, `pg_restore`,
  ledger, pre-cleanup, final cleanup и postcondition failures;
- primary failure вместе с cleanup failure;
- идемпотентная очистка отсутствующей DB и safe CLI exit.

`tests/unit/test_migration_head.py` содержит 8 сценариев exact-single-head CLI,
включая `one|zero|multiple`, malformed identifiers и безопасную ошибку loader.
Version consistency и статические operational boundaries проверяются отдельными
тестами.

## Disposable operational smoke

Smoke первоначально выполнен и полностью повторён после remediation 2026-08-16
только в локальном Docker Desktop Linux-контуре:

- exact test image: `sha256:5ebad1f3aaa1`;
- PostgreSQL: `18.4-alpine`;
- повторный Compose project: `cb59-smoke-r2-20260816`;
- synthetic root-owned env внутри Linux `tmpfs`: owner `0:0`, mode `0600`;
- production credentials, production backup и реальные пользовательские данные
  не использовались.

| Сценарий | Результат | Cleanup oracle |
|---|---:|---:|
| Configured production name совпадает с drill DB | code `1` до subprocess; заранее созданная DB сохранена | DB count `1` |
| S1 correct backup, первый запуск | code `0`; expected/production/restored `0020`; mismatch `0` | DB count `0` |
| S1 повтор тем же backup | code `0`; те же revisions | DB count `0` |
| S2 production zero revision rows | code `1` до restore | DB count `0` |
| S2 production wrong revision | code `1` до restore | DB count `0` |
| S2 production multiple revisions | code `1` до restore | DB count `0` |
| S2 production padded revision | code `1` до restore | DB count `0` |
| S2 production blank + valid rows | code `1` до restore | DB count `0` |
| S3 restored zero revision rows | code `1` | DB count `0` |
| S3 restored wrong revision | code `1` | DB count `0` |
| S3 restored multiple revisions | code `1` | DB count `0` |
| S3 restored padded revision | code `1` | DB count `0` |
| S3 restored blank + valid rows | code `1` | DB count `0` |
| S4 restored ledger/cache mismatch | code `1` | DB count `0` |
| S4 damaged non-empty dump | code `1` | DB count `0` |
| S5 stale drill DB перед запуском | pre-cleanup удалил stale DB, итог code `0` | DB count `0` |

Cleanup command failure и ложный success при оставшейся DB проверены
детерминированной автоматической fault injection, без ослабления реальных прав.
После smoke удалены его PostgreSQL container, network, named volume, Linux
runner и временные файлы. Локальный test image не публиковался и не тегировался.

После последнего bytes-first исправления дополнительно выполнен bounded smoke в
Compose project `cb59-smoke-r3-20260816`. Реальный Docker/PostgreSQL stdout
дважды прошёл обновлённый transport: оба последовательных restore запуска дали
code `0`, expected/production/restored revision `0020`, mismatch `0`, а внешний
cleanup oracle вернул DB count `0`. Контейнер, network, volume, helper и
временные файлы этого запуска удалены. Полная матрица S1–S5 не повторялась в
третий раз, потому что изменение ограничено transport seam; предыдущая полная
повторная матрица сохранена выше, а orchestration fault matrix осталась зелёной.

## Результаты gate

### Целевые проверки

```text
uv run pytest -o addopts= tests/unit/test_restore_drill.py --strict-config --strict-markers --cov=ops.restore_drill --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Результат: `91 passed`; branch coverage `96.18%`, порог `90%` пройден.

```text
uv run pytest -o addopts= tests/unit/test_migration_head.py --strict-config --strict-markers --cov=community_bot.bootstrap.migration_head --cov-branch --cov-report=term-missing --cov-fail-under=90
```

Результат: `8 passed`; branch coverage `100.00%`, порог `90%` пройден.

```text
uv run pytest -o addopts= tests/unit/test_package_metadata.py tests/unit/test_operations.py --strict-config --strict-markers
```

Результат: `17 passed, 1 skipped`; skip — существующий Windows skip проверки,
для которой нужны Bash и `flock`.

### Полный repository gate

- `uv lock --check` — успешно, `Resolved 55 packages`.
- `uv run ruff format --check .` — `485 files already formatted`.
- `uv run ruff check .` — успешно.
- Exact-path `uv run ty check ops/restore_drill.py
  src/community_bot/bootstrap/migration_head.py
  tests/unit/test_restore_drill.py tests/unit/test_migration_head.py
  tests/unit/test_package_metadata.py` — успешно.
- `uv run ty check src tests ops/restore_drill.py
  ops/verify_release_provenance.py` — успешно.
- `uv run pytest` — `595 passed, 1 skipped`, repository coverage `80.31%`,
  длительность `393.91s`.
- `uv run alembic heads` — ровно `0020 (head)`.
- `docker compose --env-file .env.example -f compose.production.yaml config
  --quiet` с exact local image, `COMMUNITY_BOT_ENV_FILE=.env.example` и safe
  example env — code `0`.
- Exact image CLI с `--pull=never --network none --read-only` — stdout ровно
  `0020`, code `0`.

## Diff и безопасность

- `git diff --name-only -- migrations/versions` — пусто.
- `git status --short migrations/versions` — пусто.
- `git diff --check` и отдельная whitespace-проверка новых untracked files —
  замечаний нет.
- Secret-like scan по изменённым operational, test, docs и task surfaces —
  совпадений нет.
- Нормативный `0019` удалён из restore, runbook и checklist; единственное
  актуальное упоминание в unit tests — отрицательный regression assert
  `"0019" not in restore`.
- В diff нет schema downgrade, production SQL mutation, deploy/tag/release или
  Telegram действий.
- SHA-256 reviewer-owned файлов после remediation сохранены:
  attempt 1 `84FFAC54C2F9327EC990893EB8E4323E1905B0EECD6FF74F4258A363CA801B4C`,
  attempt 2 и текущий review
  `B251E177B5C5D207472EF61F69230D71CC005B875676C3D87238118614839AC7`.
- Секреты, env values, connection strings, содержимое backup, строки ledger и
  пользовательские идентификаторы в отчёт не включены.

## Риски и rollback

Главный остаточный риск — operational код выполняет внешние Docker/PostgreSQL
команды и поэтому требует независимого review уровня 3 даже после зелёного
smoke. Fail-closed поведение снижает риск ложного success: успех невозможен без
exact image head, двух exact-one revision checks, ledger reconciliation и
доказанной cleanup postcondition.

До merge rollback не требуется: изменения находятся только в рабочей ветке.
После возможного merge откат выполняется новым revert commit package/restore/docs
изменений; Alembic downgrade и редактирование выпущенных migrations запрещены.
Ни production deploy, ни tag `v1.0.0` в рамках CB-59 не выполнялись.
