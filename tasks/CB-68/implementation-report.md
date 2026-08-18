# CB-68 — отчёт реализации

## Фактическая разница

- Baseline: `f2cc1cca9ca47c015b6d9e8469edd8d914a20a7f`.
- Runtime: `src/community_bot/transport/static/app.js` `+162`,
  `index.html` `+1`, `styles.css` net `+2`; всего **+165 LOC**.
- Проверка: `tests/browser/test_mini_app.py` **+186 LOC**.
- Backend/API/schema/migrations/dependencies: **0 changed files / 0 LOC**.

Реализован read-only экран «Профиль»: он использует только существующие
`GET /api/v1/me`, `GET /api/v1/members/{self}` и
`GET /api/v1/leaderboard?limit=30`. Рендер использует явный allowlist полей и
`textContent`; private/unknown/id sentinels не выводятся. Independent profile и
leaderboard loading/error/retry boundaries защищены `screenRevision` от позднего
ответа после Back.

## Проверки

- `uv run pytest tests/browser/test_mini_app.py --no-cov -q` — **5 passed**.
- `uv run ruff check tests/browser/test_mini_app.py` — passed.
- `uv run ruff format --check tests/browser/test_mini_app.py` — passed.
- `uv run ty check tests/browser/test_mini_app.py` — passed.
- `git diff --check origin/main` — passed.

Browser oracle проверяет заполненные public fields, exact karma/reliability,
nullable own и leaderboard reliability, XSS/privacy sentinels, loading/empty,
scoped retry, allowlisted GET paths, Back/focus, stale response и отсутствие
горизонтального переполнения на viewport шириной 375 px.

Ponytail pass объединил однотипные error-boundary и JSON GET helpers, а также
общую response plumbing в browser oracle. После независимого review итог
составляет `165/186` runtime/test LOC: добавлены нормализация пустых массивов,
общий перехват всех network requests и проверка mobile overflow после полной
отрисовки; бесполезный CSS selector удалён. Это выше soft target `150/140`:
оставшиеся строки — два
независимых read boundary и один сценарий, который одновременно доказывает
поля, privacy/XSS, nullable значения, retry и stale-response race. Их удаление
означало бы либо потерю обязательного oracle, либо второй framework/helper
layer, поэтому дальнейшее сжатие не выполнялось.

## Остаточный риск и следующий gate

Локальная реализация не является public delivery. Нужны независимый final
review, staging/secret gate владельца, commit/PR/CI/merge и затем ADR-0019
delivery gate с exact artifact и public URL smoke. Rollback после deployment —
предыдущий совместимый application image/static bundle; schema/data rollback не
нужен.
