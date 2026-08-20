# CB-99 — отчёт реализации

## Результат

- P01 использует compact horizontal member rows, hidden page heading и native
  search с точным accessible именем «Найти участника» без минимальной длины.
- P05 использует компактный ranked list и рабочие периоды `week|month|all` через
  существующий endpoint/service/projection; late responses не меняют текущий
  период, включая возврат на cached view.
- P06 не запрашивает и не отображает leaderboard. Identity row содержит local
  pencil SVG; метрики и показатели используют server-owned DTO.
- Profile statistics projection минимально расширена created count; доступ
  владельца `ACTIVE|PAUSED` сохранён.

## Матрица приёмки

| Критерий | Доказательство | Статус |
|---|---|---|
| P01 density 4/5 и compact header/search | browser exact geometry в 375×812 и 430×932 | green |
| Пустой/односимвольный поиск | service/API tests и native-submit browser request | green |
| Три периода и отсутствие гонок | integration cutoffs и browser pending/cached sequence | green |
| P06 без leaderboard, финальный mapping/null | browser DOM с различимыми и null values | green |
| Pencil/P07/back и a11y target | browser geometry/aria/back oracle | green |
| Active-or-paused own profile | integration API regression | green |

## Проверки

- `uv run ruff format --check .` — green, 361 files;
- `uv run ruff check .` — green;
- `uv run ty check src tests ops` — green;
- `node --check src/community_bot/transport/static/app.js` — green;
- `uv run pytest -m "not browser" --no-cov` — 581 passed до двух точечных
  review-fixes; после них профильный integration regression — 1 passed;
- полный browser file — 16 passed; после race-fix соответствующий focused
  browser oracle — 1 passed;
- отдельные reputation/web/unit/browser проверки области — green;
- `git diff --check` и secret-pattern scan — green.

Первый PR CI run `32379746202`: PostgreSQL/Alembic green; Quality выявил
Linux-only race в существующем moderation browser test — `pending.pop()`
выполнялся до появления GET. Product runtime не менялся: test синхронизирован
через native Playwright `expect_request`, точечный сценарий дважды green и
полный browser file повторён перед новым review/CI.

PR, CI, release, deploy и production smoke являются следующими обязательными
gate и не объявлены выполненными локально.

## Остаточный риск

Visual acceptance production WebView остаётся незакрытым до deploy. Период
фильтрует XP, а существующие tie-breakers остаются all-time.
