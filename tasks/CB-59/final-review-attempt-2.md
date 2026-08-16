# CB-59 — повторное финальное ревью

Status: changes_requested

Схема результата: `community_bot.final_review.verdict.v1`.

## Проверенная область

- Повторно прочитаны утверждённые `plan.md`, `test-plan.md`, первый
  `final-review.md`, обновлённый `implementation-report.md`, обязательные
  правила проекта и контракт final reviewer.
- Применены skills `database-migrations` и `delivery-gate`: проверены
  неизменяемость migrations, fail-closed recovery contract, фактические
  subprocess semantics и механические quality gates.
- Проверена вся актуальная разница worktree `CB-59` на ветке `task/CB-59`
  относительно `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`. `HEAD` и
  `origin/main` по-прежнему совпадают с этим commit; реализация не закоммичена.
- Три замечания первой попытки проверены независимо по коду, тестам и
  воспроизведению. Точное содержание первой попытки сохранено в
  `final-review-attempt-1.md`; текущая попытка сохраняется отдельно как
  `final-review-attempt-2.md`.
- Jira, Git remote, production, GitHub, Telegram и внешние окружения не
  изменялись.

## Уровень процесса и условные барьеры

| Барьер | Требуется | Результат | Доказательство |
|---|---|---|---|
| Уровень процесса | 3 | PASS | Plan/source/test package и `plan-review.md` с `Status: approved` присутствуют |
| DB-name collision до side effects | Да | PASS | Guard вызывается до Compose/cleanup/subprocess; regression не допускает boundary calls |
| Literal image stdout | Да | FAIL | `text=True` преобразует CR/CRLF в LF до literal parser, после чего значение принимается |
| Exact DB rows/cardinality | Да | FAIL частично | Padding/blank rows сохраняются, но CR/CRLF transport также нормализуется до допустимого значения |
| Missing/empty backup | Да | PASS | Два автоматических cases останавливаются до env/image/DB operations |
| Production/restored query failures | Да | PASS | Отдельные orchestration cases подтверждают stop-before-create и final cleanup |
| Target/full changed-scope gates | Да | PASS | Независимые результаты перечислены ниже |
| Disposable S1–S5 и cleanup | Да | PASS с ограничением | Повторный smoke заявлен; image/cleanup независимо подтверждены, но CR transport case отсутствует |
| Migrations/secrets/external actions | Да | PASS | Migration diff пуст, secret scan чист, deploy/tag/live отсутствуют |

## Критические замечания

Критических замечаний нет. Риск удаления production DB из первой попытки
устранён.

## Существенные замечания

1. Literal stdout contract остаётся не реализован на настоящей subprocess
   границе. Новый `capture_raw_text()` в `ops/restore_drill.py:207-220`
   вызывает `subprocess.run(..., text=True)`. Text mode использует universal
   newline conversion: до вызова `exact_protocol_rows()` байты CRLF и CR уже
   превращены в LF. Независимый реальный дочерний процесс, писавший в stdout
   байты `b"0020\r\n"` и `b"0020\r"`, в обоих случаях вернул из
   `capture_raw_text()` строку `'0020\n'`; parser получил `['0020']`, то есть
   состояние стало допустимым.

   Это прямо расходится с утверждённым literal/fail-closed контрактом и с
   актуальными `PILOT_RUNBOOK.md`/`implementation-report.md`, где CR явно
   должен отклоняться. Тест `test_read_image_migration_head_rejects_invalid_stdout`
   передаёт строку `"0020\r\n"` через monkeypatch уже после subprocess seam и
   поэтому не обнаруживает реальную нормализацию. Аналогично DB parser не
   сможет отличить revision, завершённую CR/CRLF, от разрешённого LF protocol.
   Padding, blank rows и multiple nonblank rows теперь действительно
   сохраняются и отклоняются; незакрыт именно transport-level newline case.

## Незначительные замечания

Незначительных замечаний нет.

## Критерии приёмки

- Package metadata `1.0.0`: PASS.
- Single packaged Alembic head и exact immutable image invocation: PASS.
- Ноль, несколько heads и malformed identifier: PASS.
- Любой лишний/неразрешённый image stdout: FAIL для CR/CRLF на реальной
  subprocess границе.
- Production/restored exact-one revision: PASS для zero/wrong/multiple,
  padding и blank/whitespace rows; FAIL для literal CR/CRLF distinction.
- Production DB не может совпасть с fixed drill DB: PASS. Guard расположен до
  cleanup и subprocess; disposable smoke сообщает сохранённую заранее созданную
  DB (`count=1`) при коллизии.
- Missing/empty backup и отдельные production/restored query failures: PASS.
- Restore, ledger, cleanup, postcondition и repeat semantics: PASS по
  автоматической матрице и disposable evidence.
- Runbook/tests/report описывают один literal контракт: FAIL, поскольку docs и
  report обещают отклонение CR, которого реальный seam не обеспечивает.
- Migrations неизменны, deploy/tag/Release/Telegram отсутствуют: PASS.

## Тесты и проверка ключевого сценария

Независимо повторены:

- `uv lock --check` — PASS (`Resolved 55 packages`).
- `uv run ruff format --check .` — PASS (`482 files already formatted`).
- `uv run ruff check .` — PASS.
- Exact-path и полный `uv run ty check ...` — PASS.
- Target restore gate — `75 passed`, branch coverage `96.06%`, порог `90%`
  пройден.
- Target migration-head gate — `8 passed`, branch coverage `100%`.
- Package metadata + operations — `17 passed, 1 skipped`; существующий skip
  требует Bash/`flock`.
- Changed-scope run `uv run pytest -m "not integration" --no-cov` —
  `405 passed, 1 skipped, 174 deselected`.
- `uv run alembic heads` — ровно `0020 (head)`.
- `git diff --check` — PASS.

Обновлённый implementation report также фиксирует полный repository gate
`579 passed, 1 skipped`, coverage `80.31%`. Зелёные tests не опровергают
finding: seam-test monkeypatch возвращает готовый `str` и не проходит через
реальное text decoding.

Независимое subprocess-воспроизведение:

```text
lf          -> '0020\n' -> ['0020']
crlf bytes  -> '0020\n' -> ['0020']
cr bytes    -> '0020\n' -> ['0020']
double CRLF -> '0020\n\n' -> ['0020', '']
```

Чистые parser regressions для `" 0020 "`, `"0020 "`, leading blank,
second LF и whitespace row прошли: все отклоняются. Таким образом первая
проблема `.strip()`/blank filtering исправлена, но буквальная граница байтов
ещё нормализуется Python text mode.

Disposable image
`sha256:5ebad1f3aaa1fd6c94236fb9f7c8aa7d9f1e44af755fe969c4f0568049e81e06`
независимо существует, запускается как `65532:65532`, сообщает ровно `0020`,
а installed metadata и `community_bot.__version__` равны `1.0.0`. После smoke
не найдено container/network/volume с Compose project
`cb59-smoke-r2-20260816`. Это подтверждает cleanup обычной smoke matrix, но не
закрывает transport-level CR case.

## Документация и язык

Смысловые артефакты написаны по-русски. Runbook/checklist синхронизированы с
image-derived head, двумя revision gates и DB-name guard. Однако runbook
утверждает, что `CR` блокирует drill, а implementation report — что raw seam не
нормализует stdout. Оба утверждения фактически неверны при `text=True`, поэтому
документальный gate остаётся незакрытым.

## Секреты и безопасность

- Secret-like scan изменённых operational/test/docs/task surfaces: совпадений
  нет.
- Env values, credentials, raw DB rows, backup content и Telegram data в
  артефакты не попали.
- `git diff --name-only -- migrations/versions` и status каталога migrations
  пусты; schema downgrade и новая migration отсутствуют.
- На диске C свободно 49.5 GB: это warning threshold `delivery-gate`, но не
  блокирующий порог 15 GB.

## Процесс Git/Jira

Ветка `task/CB-59` соответствует задаче; внешние действия не выполнялись.
Поскольку это вторая попытка final review с обязательным замечанием,
`Status: approved` запрещён. Обе попытки сохранены отдельными файлами в
`tasks/CB-59/`. Создание `problem-escalation.md` и следующий remediation-цикл
не выполнялись reviewer-ом и остаются владельцу процесса.

## Обязательные действия

1. Сохранять stdout до parser без universal-newline conversion, например
   захватывать bytes и выполнять strict decoding без преобразования CR/CRLF.
   Image и DB protocol должны принимать только точные `REVISION` или
   `REVISION\n`, как утверждено в plan/runbook.
2. Добавить regression, который запускает настоящий дочерний процесс либо
   тестирует byte-level seam с CRLF/CR, а не подменяет уже декодированный
   результат `str`. Доказать rejection отдельно для image и DB gate.
3. Синхронизировать implementation report с фактической реализацией, повторить
   target/full gates и достаточный disposable smoke после runtime-изменения,
   затем передать пакет на следующий review по процессу владельца.

## Остаточные риски

- Текущий типичный Linux image/psql выводит LF, поэтому дефект не проявился в
  S1–S5. Но release blocker спроектирован как exact fail-closed boundary и не
  может полагаться на происхождение нормализованного значения после того, как
  raw protocol evidence уже потеряно.
- Исправленные collision, padding, blank-cardinality, backup и query-failure
  paths подтверждены; повторный remediation должен быть узким и не менять их.
