# CB-54 — отчёт о реализации

## Результат

Реализован утверждённый read-only slice `Мои активные назначения`:

```text
Mini App → Мои задания → Взятые мной → список → detail → back
```

Работа начата от `origin/main` `9506bac26d8c40b1445bdb40b7e9da26f01b9d38`
после merge CB-53 (PR #66). Ветка: `task/CB-54`.

## Фактический scope

- Добавлены только `GET /api/v1/assignments` и
  `GET /api/v1/assignments/{assignment_id}`.
- Existing `AssignmentService` получил два actor-native read entrypoint поверх
  существующих `get_member`, `list_assignment_cards` и `get_assignment_card`.
- Список ограничен `ACTIVE_ASSIGNMENT_STATUSES`, `limit=1..50`; cursor кодирует
  existing stable tuple `(accepted_at, assignment_id)` и указывает на последнюю
  выданную строку.
- Detail виден только активному владельцу. Terminal, foreign, missing и
  test-run-invisible UUID схлопываются в одинаковый `404 not_found`.
- DTO — явный whitelist. Raw input/materials, Telegram и internal actor IDs,
  command/receipt IDs, private dispute/case/evidence данные не сериализуются.
- Mini App использует существующие HTML/CSS/JS assets и History API. Добавлены
  loading, empty, retryable error, list, detail и возврат с восстановлением
  keyboard focus. Async list/detail responses защищены screen revision: поздний
  ответ не может перерисовать уже покинутый экран.
- `401`, `403` и `404` имеют разные пользовательские состояния; retry доступен
  только для действительно повторяемого network/server сбоя.
- Assignment list использует semantic `ul/li`, сроки размечены `time[datetime]`,
  а строка показывает безопасный `result_summary`, когда он есть.
- GET не создают receipts/audit/outbox/ledger и не меняют assignment state.

Не добавлены зависимости, таблицы, миграции, repositories, services, frontend
framework или generic endpoint/pagination layer. Domain engine и lifecycle не
изменялись. `withdraw`, `submit` и любые другие mutations отсутствуют.

## Изменённые runtime-границы

- `src/community_bot/application/assignments.py` — минимальный actor/read glue и
  page value object.
- `src/community_bot/transport/web.py` — два GET route, whitelist DTO и локальный
  stdlib cursor codec.
- `src/community_bot/transport/static/index.html` — навигация между каталогом и
  назначениями.
- `src/community_bot/transport/static/app.js` — list/detail/back path.
- `src/community_bot/transport/static/styles.css` — стили двух native tabs.

Тесты изменены в существующих canonical файлах route inventory, web integration
и browser oracle. Новые тестовые слои и fixture framework не создавались.

## Доказательства проверки

- `uv run ruff format --check .` — пройдено после финального форматирования.
- `uv run ruff check .` — пройдено.
- `uv run ty check src tests ops` — пройдено.
- Targeted unit route/cursor oracle:
  `12 passed in 3.61s`.
- Targeted API privacy/pagination + CB-53 regression:
  `2 passed in 17.16s`.
- Отдельный browser oracle после consolidated final-review fix:
  `2 passed in 5.36s`. Он проверяет list → detail → back, focus restoration,
  empty/retry, distinct list/detail `401/403/404`, semantic list/time/result и
  гонку `pending detail → back → late response`.
- Единый контрольный non-browser suite после исправления collection namespace:
  `525 passed, 1 deselected in 421.43s`; coverage `81.76%`, gate `80%`.
- `git diff --check` — пройдено.

Первый контрольный запуск остановился на collection: импорт ORM-класса
`TestRunModel` pytest распознал как тестовый класс. Импорт получил локальный alias
`DbTestRunModel`; тот же полный suite после исправления прошёл. Runtime-код этим
исправлением не затронут.

## Privacy и data-integrity oracle

Интеграционный сценарий создаёт 52 активных назначения с одинаковым
`accepted_at`, terminal owner assignment, foreign assignment и
test-run-invisible assignment. Он проверяет:

- exact ordered ID set через две страницы без дублей и пропусков;
- `next_cursor=null` на последней странице и public boundary `limit=50`;
- exact whitelist key sets списка и detail;
- отсутствие private markers из raw materials/input/result/dispute/case/evidence;
- одинаковые status/body `404` для четырёх классов невидимого detail;
- exact `403 assignment_unavailable` после server-side смены member status;
- неизменность schema counts и assignment state до/после разрешённых и
  запрещённых GET.

## Ponytail audit

Проверен весь planned diff на переизобретение stdlib, speculative abstractions,
лишние зависимости и одноразовые framework-слои.

Результат: `Lean already. Ship.`

Рост тестового diff объясняется одной закрытой privacy/pagination fixture с
реальными FK и 52 строками, а не runtime abstraction. Line-golf не применялся.

## Отклонения и остаточный риск

- Публичный deployment и live Telegram acceptance не входят в CB-54; реальные
  Telegram sessions не читались, сообщения не отправлялись.
- Cursor отражает snapshot-less keyset pagination: concurrent inserts между
  страницами подчиняются существующему DB ordering, но snapshot transaction не
  обещается и не добавлялась.
- `withdraw` и `submit` остаются отдельными later slices с собственными mutation
  receipts и owner approval.

## Consolidated fix после первого final review

Первый независимый verdict был `changes_requested`: browser probe доказал, что
поздний detail response мог перерисовать список после Back; также отсутствовали
distinct account/auth states, list result summary и semantic list/time oracle.

Исправления внесены одним пакетом только в native UI и browser test. Backend,
API, privacy projections и data model после успешного единого контрольного
non-browser suite не менялись, поэтому этот дорогой suite не запускался второй
раз: повтор не проверил бы изменённый JS. Вместо этого дважды выполнен affected
browser test после реализации и после добавления прямых detail `401/403`
assertions; финальный результат `2 passed`. Ruff/ty/diff gates повторены.

## Rollback

До merge достаточно откатить task branch. После merge runtime rollback не
требует database downgrade: схема и данные не менялись; удаляются только два GET
route, read glue и соответствующий static UI slice.
