# CB-96 — отчёт о локальной реализации presentation layer концепции 05

## Статус

После решения владельца в Jira comment 10355 выполнен единый локальный цикл
коррекции runtime UI, browser oracle и visual evidence. Полный scope из `103`
UI ID сохранён. Этот отчёт не заявляет завершение CB-96: новый независимый
final review, commit, push, PR, CI, merge, release, deploy и public Mini App
smoke ещё не выполнялись.

## Фактическая область

Runtime/test diff относительно `origin/main` ограничен четырьмя разрешёнными
файлами:

| Файл | Добавлено | Удалено |
|---|---:|---:|
| `src/community_bot/transport/static/app.js` | 1072 | 104 |
| `src/community_bot/transport/static/index.html` | 16 | 15 |
| `src/community_bot/transport/static/styles.css` | 78 | 21 |
| `tests/browser/test_mini_app.py` | 552 | 54 |
| **Итого** | **1718** | **194** |

Backend, API routes, application, domain, infrastructure, storage, schema,
migrations и dependency-файлы не менялись. Новых frontend dependencies,
маршрутов API и runtime modules нет.

## Реализация owner decision 10355

### Полный предметный UI без renderer-per-screen

- Все `103/103` UI ID имеют явные русские `title`, предмет состояния,
  действие и собственный набор полей/карточек.
- Старые одинаковые fallback-фразы удалены. Неизвестный или неполный ID
  закрывается отдельным безопасным unavailable outcome.
- Сохранены ровно `8` утверждённых semantic layouts: list, detail, editor,
  preview, confirm, outcome, history и hub.
- Сохранены `11` route patterns; route/component/test на каждый ID не создавался.
- `103` records являются закрытым содержимым текущего контракта, а не
  расширяемым plugin/framework API.

### Чистая production/test boundary

- Production `app.js` не экспортирует renderer, navigation helper или fixture
  adapter.
- В production source точные количества строк `presentationTestAdapter`,
  `fixtureOnly` и `test-resource`: `0/0/0`.
- Playwright test перехватывает ответ production module только внутри тестовой
  страницы и дописывает test-only exports уже существующих внутренних функций.
  В обычной production page оба соответствующих свойства module имеют тип
  `undefined`.
- `25 dev_test_fixture_only` representations вызываются только через эту
  test-local boundary. Production DOM не содержит их transition controls и не
  может показать вымышленный authoritative success.

### Connected и navigation paths

- Сохранены `10 production_existing_api` click/request assertions с точными
  HTTP method/path/request-count и авторитетным ответом API.
- Сохранены `93 production_ui_local` transitions с проверкой marker, state,
  history, focus, safe fallback и `request_count=0`.
- Bottom navigation остаётся root-only и role-shaped; context screens показывают
  логический Back и возвращают focus к source control.
- Формы используют читаемые в Telegram WebView 16px controls с явными text,
  background и caret tokens. Видимые действия имеют область не меньше 44px;
  focus ring остаётся на интерактивных controls.

## Machine contract

`uv run python tasks/CB-96/build_ui_contract.py` вернул:

| Срез | Количество |
|---|---:|
| UI ID | 103 |
| no-UI boundaries | 17 |
| capabilities | 26 |
| route patterns | 11 |
| transitions | 128 |
| `production_ui_local` edges | 93 |
| `dev_test_fixture_only` edges | 25 |
| `production_existing_api` edges | 10 |
| `ui_local_only` screens | 61 |
| `disabled_unavailable` screens | 32 |

SHA-256 `ui-contract.json`:
`B9E6ADAB4FB405159E548C96D5BCB70A14A7E2EEBFC80DEC097FBD529F53E7A8`.

## Browser oracle и responsive evidence

Консолидированный `tests/browser/test_mini_app.py` проверяет:

- `103` content representations и subject-specific error state;
- отсутствие старого generic fallback, raw visual-contract строк и знака
  незаполненного значения;
- все `103` ID при `375×812` и `430×932`: no horizontal overflow, root/context
  navigation, Back, controls ≥44px и читаемые form controls;
- `128` переходов в распределении `93/25/10`;
- точный history/focus/safe-fallback/request-count contract;
- обычная production page не получает test-only exports;
- существующие auth/bootstrap/catalog/task/assignment/submission/review/dispute/
  profile/karma/moderation paths не меняют API semantics.

Девять canonical `375×812` PNG обновлены в `tasks/CB-96/evidence/runtime/`.
Полный набор `9 × 2` settled captures находится вне репозитория:

`C:\Users\User\.codex\visualizations\2026\08\19\cb96-owner-correction-final`

Файлы: `T01`, `T03`, `M01`, `P06`, `S01`, `T05`, `P01`, `P02`, `P05` с
суффиксами `-375x812.png` и `-430x932.png`. T01 получен через connected catalog
API mock; остальные representation-only кадры используют test-local harness и
не изображают success неподключённых операций.

## Выполненные проверки

| Команда | Результат |
|---|---|
| `uv run python tasks/CB-96/build_ui_contract.py` | PASS, `103/17/26/11/128`, scopes `93/25/10` |
| `uv run ruff format --check .` | PASS, `354 files already formatted` |
| `uv run ruff check --output-format=github .` | PASS |
| `uv run ty check src tests ops` | PASS |
| `node --check src/community_bot/transport/static/app.js` | PASS |
| `git diff --check origin/main` | PASS |
| `uv run pytest --no-cov -q tests/browser/test_mini_app.py` | PASS, `14 passed in 50.41s` |
| `uv run pytest --no-cov -q tests/unit/test_web_auth.py tests/integration/test_web_api.py` | PASS, `33 passed in 48.94s` |
| `uv run pytest --no-cov -q tests/architecture tests/documentation` | PASS, `23 passed in 0.50s` |

## Ponytail review

Сохранён один закрытый content table, восемь уже требуемых layout renderer и
один консолидированный browser oracle. Не добавлены component-per-ID,
route-per-ID, test-per-ID, generic form framework, новый module или dependency.
Test screenshot seam активируется только двумя test environment paths и не
участвует в production module. Дополнительных сокращений без потери явного
owner-approved `103`-screen scope не найдено.

## Остаточные gates и риски

- `final-review.md` сохранён без изменений с SHA-256
  `59CA19AE1ABA5414FC8465170F51454920E7C57E76DAD81902FF3FA139300F40` и всё ещё
  содержит предыдущий verdict `changes_requested`; требуется новый независимый
  review текущего diff.
- Screens без существующего engine/API остаются честно disabled/unavailable.
  Их подключение, server-projected role/permission/eligibility/outcome и
  authoritative mutations относятся к следующей engine-connection задаче.
- Не выполнялись commit, push, PR, CI, merge, Jira mutation, release, deploy,
  Telegram profile smoke и public URL verification.

## Следующее действие

Передать текущий diff, этот отчёт и `9 × 2` captures независимому final reviewer.
Delivery pipeline начинается только после нового `Status: approved`.
