# CB-59 — финальное ревью

Status: changes_requested

Схема результата: `community_bot.final_review.verdict.v1`.

## Проверенная область

- Полностью прочитаны обязательные правила проекта, workflow Jira/агентов,
  контракт final reviewer, ADR-0009/ADR-0011, утверждённые `plan.md`,
  `plan-source-context.md`, `test-plan.md`, `plan-review.md` и фактический
  `implementation-report.md`.
- Применены требования skills `database-migrations` и `delivery-gate`:
  миграционный контракт проверялся fail-closed, а зелёные команды не считались
  доказательством для отсутствующих сценариев.
- Проверена вся рабочая разница ветки `task/CB-59` относительно
  `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`, включая runtime, tests, package
  metadata и operational docs. Локальные `HEAD`, `origin/main` и remote main
  совпадали на этом commit; реализация на момент ревью не закоммичена.
- Jira проверена read-only: CB-59 находится `В работе`, является дочерней к
  CB-48 и блокирует CB-50. Никакие Jira/Git/GitHub/production/Telegram действия
  в ходе ревью не выполнялись.

## Уровень процесса и условные барьеры

| Барьер | Требуется | Результат | Доказательство |
|---|---|---|---|
| Уровень процесса | 3 | PASS | Утверждённые plan, source context, test plan и повторный plan review присутствуют |
| Соответствие области Jira | Да | PASS | Изменения ограничены repository preparation; deploy, tag, Release и live отсутствуют |
| Единственный image-derived Alembic head | Да | FAIL | Корректный `0020` работает, но padded/blank-extra stdout принимается после нормализации |
| Exact-one production/restored revision | Да | FAIL | Padded DB value и дополнительная blank/whitespace row могут превратиться в допустимый `0020` |
| Безопасность production DB | Да | FAIL | До destructive pre-cleanup нет запрета коллизии production и drill database names |
| Package version `1.0.0` | Да | PASS | `pyproject.toml`, root package `uv.lock`, `__version__` и installed image metadata согласованы |
| Target/static gates | Да | PASS | Независимо повторены и пройдены; подробности ниже |
| Disposable S1–S5 и cleanup | Да | PASS с ограничением | Отчёт содержит матрицу; exact image и отсутствие ресурсов независимо подтверждены, но smoke не покрывает найденные fault cases |
| Неизменность migrations | Да | PASS | Разница и status каталога `migrations/versions` пусты; `alembic heads` сообщает единственный `0020` |
| Секреты и внешние действия | Да | PASS | Секретоподобных значений не найдено; deploy/tag/live не выполнялись |

## Критические замечания

1. В `ops/restore_drill.py:88-90` значение `POSTGRES_DB` принимается как имя
   production DB и сразу передаётся в проверку после pre-cleanup, но до самого
   cleanup нет проверки `production_database != DRILL_DATABASE`. В
   `cleanup_drill_database()` выполняется `dropdb --if-exists --force
   community_bot_restore_drill`. Поэтому ошибочная root-owned конфигурация, где
   рабочая БД названа `community_bot_restore_drill`, приведёт к принудительному
   удалению production DB ещё до любого revision gate. Это прямое нарушение
   утверждённого запрета удалять или изменять production DB и несовместимо с
   fail-closed моделью уровня 3. Теста конфигурационной коллизии и доказательства
   отсутствия subprocess/cleanup при ней нет.

## Существенные замечания

1. Парсинг не реализует утверждённую exact-семантику. Общий
   `capture_text()` в `ops/_runtime.py:132-135` выполняет `stdout.strip()`, а
   `read_image_migration_head()` в `ops/restore_drill.py:212` дополнительно
   обрезает каждую строку и отбрасывает пустые строки. Независимая fault
   injection показала, что image stdout `" 0020 "` возвращает `"0020"` и
   принимается. Дополнительная blank/whitespace строка рядом с `0020` тоже
   исчезает. Это противоречит утверждённому контракту «только одна непустая
   строка; любой лишний вывод отклоняется».

2. Та же нормализация ослабляет exact-one DB gate. В
   `read_database_revisions()` (`ops/restore_drill.py:248`) значение строки
   `"0020 "` превращается в `"0020"`, а набор из blank/whitespace row и
   `0020` превращается в одну строку. Независимая fault injection получила
   `db_trailing_whitespace_rows=['0020']` и
   `db_blank_plus_expected_rows=['0020']`; последующий
   `require_exact_revision()` принимает оба результата. Значит, malformed
   stored revision и фактическая cardinality больше единицы могут пройти gate.
   Стандартный завершающий перевод строки CLI можно удалить без изменения
   значений и без фильтрации строк; внутренние/дополнительные строки должны
   оставаться видимыми валидатору и отклоняться.

3. Обещанная автоматическая fault matrix реализована не полностью. В
   `test-plan.md` явно запланированы отсутствующий/пустой backup и `query error`
   отдельно для production и restored DB с разными cleanup expectations.
   `tests/unit/test_restore_drill.py` содержит только helper-level проверку
   преобразования одного psql failure; orchestration tests query error для
   production (остановка до create) и restored (обязательный final cleanup)
   отсутствуют. Тестов отсутствующего и пустого backup также нет. Кроме того,
   нет регрессий для padded valid image head, blank-extra image output, padded
   DB revision и blank/whitespace DB row рядом с expected revision. Поэтому
   заявленные `39 passed` и coverage `95.45%` проверяют более слабый контракт,
   чем утверждённый план.

## Незначительные замечания

Незначительных замечаний нет.

## Критерии приёмки

- CLI `community-migration-head` получает graph из packaged Alembic и
  fail-closed обрабатывает zero/multiple/invalid heads: PASS на уровне самого
  CLI (`8 passed`, branch coverage `100%`).
- Host запускает CLI из exact immutable image с `--pull=never`, `--network
  none`, `--read-only`: PASS для invocation и независимо проверенного image.
- Любой лишний image stdout отклоняется: FAIL из-за stripping/filtering.
- Production и restored `alembic_version` требуют ровно одну исходную строку и
  exact equality expected head: FAIL из-за потери whitespace и blank rows.
- Production revision проверяется до restore mutations, restored revision — до
  ledger: PASS для покрытых zero/wrong/multiple nonblank cases.
- Production DB никогда не удаляется: FAIL при коллизии с фиксированным именем
  drill DB.
- Pre/final cleanup и absence postcondition: PASS для покрытых обычных ошибок и
  сохранённого fixed-name boundary, но production-name collision не закрыта.
- Ledger/restore/createdb failures дают nonzero и cleanup: PASS для покрытых
  сценариев; orchestration query-error evidence неполно.
- Package metadata `1.0.0`, docs и entry point: PASS по реализованным файлам.
- Новых/изменённых schema migrations, deploy, tag, GitHub Release или Telegram
  live нет: PASS.

## Тесты и проверка ключевого сценария

Независимо повторены:

- `uv lock --check` — PASS (`Resolved 55 packages`).
- `uv run ruff format --check .` — PASS (`481 files already formatted`).
- `uv run ruff check .` — PASS.
- exact-path и полный `uv run ty check ...` из плана — PASS.
- target restore coverage — `39 passed`, branch coverage `95.45%`, порог
  `90%` пройден.
- target migration-head coverage — `8 passed`, branch coverage `100%`.
- package metadata + operations — `17 passed, 1 skipped`; skip относится к
  существующему Windows-only отсутствию Bash/flock.
- changed-scope repository run `uv run pytest -m "not integration" --no-cov` —
  `369 passed, 1 skipped, 174 deselected`.
- `uv run alembic heads` — ровно `0020 (head)`.
- Compose config с safe `.env.example` и syntactically exact local image —
  PASS.
- `git diff --check` и проверка whitespace новых файлов — PASS.

Implementation report фиксирует полный repository run `543 passed, 1
skipped`, coverage `80.43%`; повтор полного интеграционного набора не требовался
для установления воспроизводимых контрактных дефектов.

Disposable evidence S1–S5 содержит ожидаемые success, production/restored
zero/wrong/multiple, ledger mismatch, damaged dump, stale DB и повтор success.
Независимо проверены exact local image
`sha256:5ebad1f3aaa1fd6c94236fb9f7c8aa7d9f1e44af755fe969c4f0568049e81e06`,
его stdout `0020`, installed metadata `1.0.0`/`__version__ == 1.0.0`, а также
отсутствие контейнеров, network и volumes проекта `cb59-smoke-20260816` после
cleanup. Production credentials и production backup для этой проверки не
использовались.

## Документация и язык

Runbook и checklist синхронизированы с image-derived head, отдельными
production/restored gates, cleanup postcondition и privacy allowlist. Русский
язык смысловых артефактов соблюдён. Однако документация обещает strict exact
контракт, который текущий parser не обеспечивает, а implementation report
называет test matrix полной при перечисленных пропусках; документальная
приёмка поэтому не закрыта.

## Секреты и безопасность

- Поиск по изменённым и новым файлам не выявил credentials, tokens, session
  data или приватных Telegram данных.
- Runtime не печатает env values, DB rows или backup content.
- Новых shell scripts и Jira key в runtime identifiers нет.
- Свободно 49.6 GB на диске C; механический delivery gate не блокирует работу.
- Критический риск destructive production cleanup описан выше и должен быть
  устранён до merge.

## Процесс Git/Jira

Ветка и Jira соответствуют задаче; dependency `CB-59 blocks CB-50`
подтверждена. Commit, push, PR, merge, deploy, tag, Release, Jira transition и
Telegram операции не выполнялись. `Status: changes_requested` блокирует
публикацию реализации по текущему обязательному lifecycle до исправления и
повторного независимого final review.

## Обязательные действия

1. До любого cleanup/subprocess/DB mutation явно отклонять конфигурацию, в
   которой production database совпадает с фиксированной drill database;
   добавить тест, доказывающий отсутствие side effects.
2. Переписать парсинг image stdout и DB rows так, чтобы сохранялись значения и
   cardinality исходного протокола: padded value и любая дополнительная
   blank/whitespace/nonblank строка должны fail closed. Добавить отдельные
   regression tests для image, production DB и restored DB.
3. Закрыть запланированные missing/empty backup и отдельные production/restored
   query-error orchestration paths с точными order/cleanup assertions.
4. Обновить implementation report, повторить target/full gates и disposable
   S1–S5 после runtime-изменений, затем провести новое независимое final review.

## Остаточные риски

- S1–S5 подтверждают нормальные и несколько fault paths, но не защищают от
  ошибок, которые parser нормализует до допустимого состояния; зелёный smoke не
  компенсирует найденный fail-open.
- Fixed-name cleanup остаётся безопасным только после явной проверки
  неравенства production name и drill name.
- До исправления нельзя использовать текущую реализацию как release blocker
  prerequisite для CB-50, даже несмотря на зелёные lint/type/coverage gates.
