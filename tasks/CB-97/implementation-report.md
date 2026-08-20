# CB-97 — отчёт о реализации connected Concept 05

## Результат реализации

Production Mini App после Telegram-auth использует один UI-путь Concept 05.
Параллельный presentation renderer, legacy hero, bespoke preview/confirm,
`globalThis.confirm` и Unicode nav glyphs удалены. Backend, domain, schema,
framework, API paths и payload contracts не менялись.

Навигация capability-shaped: production bootstrap проверяет существующий
`GET /api/v1/moderation/cases?limit=1`; при успешном ответе доступны пять root tabs:
`Каталог / Мои / Участники / Профиль / Модерация`. Участники остаются
самостоятельным разделом по последнему решению владельца.

## Девять connected групп

| Группа | ID | Production API |
|---|---|---|
| Catalog | T01–T03 | `GET /tasks` |
| Accept | T03/T03A | `POST /tasks/:id/assignments` |
| Create | T04–T08 | `GET/POST /task-creation` |
| Participants | P01, P02, P05 | `GET /members`, `/members/:id`, `/leaderboard` |
| Profile/Karma | P03, P04, P06, P07 | `/me`, `/me/profile`, `/karma-vote` |
| Assignments | M01–M07 | `/assignments`, `/submission-drafts` |
| Created/Review | M09–M13 | `/owned-tasks`, `/assignment-reviews` |
| Dispute/Cancel | M08, M14, M15 | `/cancellation`, `/disputes` |
| Moderation | S01–S04 | `/moderation/cases`, `/resolution` |

Полная route/state/request/navigation матрица находится в
`connected-coverage.json`.

## Классификация browser gate

Исходный выбранный набор имел результат `1 passed / 4 failed`.

- Profile — runtime defect: профиль ждал secondary leaderboard и скрывал
  authoritative profile content. Исправлено параллельной загрузкой member и
  leaderboard. Тест доказывает точные pending URL, раннюю видимость профиля,
  раздельные payloads, оба late-response порядка и отсутствие private marker.
- Catalog accept — intentional Concept transition T03→T03A. API request и
  idempotency key остаются только за явным `Принять слот`.
- Karma — intentional Concept transition P02→P03→P04. Все четыре API command,
  revisions, retry key, privacy и refreshed aggregate сохранены.
- Moderation — intentional Concept transition S02→S03→S04. Expected revision,
  request count, retry/conflict и focus/Back assertions сохранены.

Дополнительные пять старых browser failures были теми же намеренными
разделениями T04/T06/T07, M05/M06, M08, M12/M13 и M14/M15. Wording/click order
изменены только вместе с exact Concept ID. Assertions по request counts,
idempotency, eligibility, XSS, privacy, retry, stale response и conflicts не
удалялись.

Повторный review выявил отдельный runtime defect истории: confirm/preview DOM
для T03A, T06, T07, M12 и S03 не всегда совпадал с URL, а popstate T05 при
наличии server preview возвращал T06. Для каждого Concept-state теперь создаётся
собственная history entry. Browser gate отдельно проверяет URL, Back и reload;
T05 восстанавливается явным editor-state без повторного save/publish и без
изменения request counts или idempotency keys.

Последняя композиционная проверка разделила P02/P03 и M03–M08 физически:
member detail содержит только действие `Оценить карму`, assignment detail —
только доступные server-projected actions. Karma, result, dispute и cancellation
редакторы больше не вложены в detail. Exact scroll oracle проверяет обе оси
window/document/shell/screen и полную видимость border/back/title после
M04→M05→M06→Back→M03 и member flow в обоих viewport.

## Visual evidence

`capture_connected_evidence.py` запускает настоящий production bootstrap,
перехватывает существующие `/api/v1` contracts и проходит UI кликами. Direct
presentation navigation не используется.

- 36 reachable ID × 2 viewport = 72 PNG;
- размеры: `375×812`, `430×932`;
- capture gate ждёт `data-state != loading`;
- фактические mock payloads до выдачи валидируются production-моделями
  `MeDto`, `TaskDto` и `MemberDto`;
- каждый PNG имеет точный размер viewport; `full_page` не используется;
- shell/nav/heading и нулевые scroll offsets проверяются до сохранения кадра;
- T01 имеет только approved `+ Создать` в header;
- T02 открывается через `PE-012/open_filters` на существующей строке количества;
- P06 settled, settings — compact line-icon в header, duplicate Participants CTA
  отсутствует;
- T05 использует segmented type, two-column geometry, helpers и calculated
  reserve на прежних API fields.

## Reuse/deletion

Shared primitives: `connectedBoundary`, `showActionConfirmation`, единый shell,
cards, chips, segmented controls, outcome и deterministic line SVG. Они
заменили renderer-per-screen и native confirm paths, не добавляя третий UI
слой.

Итоговый production renderer `app.js`: 891 добавление / 1007 удалений — net
deletion 116 строк при полном переносе connected flow. `index.html` также
уменьшен на 5 строк; CSS вырос на 61 строку из-за единого shell, локальных SVG,
responsive/safe-area и form geometry. В сумме production static — net deletion
60 строк; tracked runtime+browser-test diff — net deletion 54 строки. Новые
evidence/report artifacts вынесены из runtime. Ponytail-review удалил
presentation inventory непроизводственных A/G/P/M/S экранов; production хранит
только Set из 36 реально connected ID.
Deterministic production search: все legacy renderer names, presentation
renderer/caller, native confirm, Unicode nav glyphs, hero и inline preview
selectors имеют `0` occurrences.

Финальные локальные gates: browser `15 passed`; полный `uv run pytest` —
`595 passed`, coverage `82.33%`; Ruff, Ty (`src tests`), Node syntax и
`git diff --check` — green. Матрица содержит 36/36 per-ID `reference_png` и
72/72 PNG.
