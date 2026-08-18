# CB-54 — план узкого Mini App slice «Мои активные назначения»

## Решение и ожидаемый результат

Сузить устаревшую формулировку «полный движок заданий» до одного наблюдаемого
пути после CB-53:

```text
Mini App → Мои задания → Взятые мной → Активные
→ список performer-owned assignments
→ открыть назначение
→ увидеть authoritative status, сроки и последний result summary
```

Это 20/80 slice: после принятия из CB-53 пользователь перестаёт попадать в
тупик и видит взятое обязательство, дедлайн и серверное состояние. Delta не
затрагивает settlement, ledger или workflow transitions и переиспользует уже
существующие privacy-scoped projections.

Terminal state этого пакета: `plan ready / owner decision required`.
Runtime начинается только после явного owner approval плана и только после
merge CB-53.

## Scope

### Входит

1. Два authenticated read routes:
   - `GET /api/v1/assignments?status=active&limit={1..50}&cursor={opaque}`;
   - `GET /api/v1/assignments/{assignment_id}`.
2. Тонкое подключение существующего `AssignmentService` и performer-scoped
   projection к internal `ActorContext` web session.
3. Явные whitelist DTO для списка и detail, без прямой сериализации
   `AssignmentCard`, `Assignment` или `PublishedTask`.
4. Нативный Mini App экран поверх CB-53 shell: semantic HTML, CSS и ES modules;
   состояния loading/empty/error/content; keyboard/back navigation.
5. Targeted API tests и один минимальный browser oracle выбранного пути.
6. Один короткий аудит planned diff на очевидный мусор перед реализацией.

### Не входит, но остаётся в roadmap

- `withdraw`, replacement и cancellation responses;
- submission draft, result upload/version и confirm;
- creator task draft/publish, group slots/close intake;
- creator/reviewer full/partial/reject/revision;
- community publication/approval/reviewer replacement;
- disputes, appeals, moderation и admin UI;
- новый scheduler/reminder/finalizer код;
- notification deep links и deployment;
- generic endpoint framework, generated client SDK, state manager, frontend
  framework, websocket, event bus, новый repository/service/table или
  speculative abstraction.

CB-53 `accept` POST не дублируется и не расширяется.

## Exact API contract

### `GET /api/v1/assignments`

- Auth: существующая `__Host-community_session`; отсутствие/истечение — `401`.
- Query:
  - `status=active` — единственное значение CB-54; server mapping ровно на
    existing `ACTIVE_ASSIGNMENT_STATUSES`;
  - `limit` — integer `1..50`, default `20`;
  - `cursor` — opaque URL-safe token, кодирующий existing stable pair
    `(order_at, assignment_id)`; invalid token — `422 invalid_request`.
- Call order:
  1. FastAPI `current_actor` получает internal `ActorContext`;
  2. existing `AssignmentService` actor-native read entrypoint подтверждает
     актуальный member/status через текущий UoW;
  3. actor-native owner вызывает DB projection напрямую с
     `list_assignment_cards(performer_id, statuses=ACTIVE...,
     limit=page_limit+1, before_order_at, before_id)`; публичный предел
     `page_limit <= 50` не прогоняется через старую проверку
     `AssignmentService.cards(limit <= 50)`, поэтому `limit=50` корректно
     читает максимум 51 строку только внутри DB boundary;
  4. transport выдаёт `rows[:page_limit]`; если extra row есть,
     `next_cursor` кодирует ровно `(items[-1].assignment.accepted_at,
     items[-1].assignment.id)`, иначе возвращает `null`;
  5. cursor codec — два локальных stdlib helper без generic pagination layer;
     он строго проверяет URL-safe encoding, UTC timestamp и UUID, а malformed
     или partial cursor даёт `422 invalid_request`.
- Response:
  - `items[]`: `id`, `task_id`, `task_title`, `task_origin`,
    `assignment_status`, `accepted_at`, `submitted_at`, `review_deadline_at`,
    `reject_dispute_deadline_at`, `reviewed_at`, `task_deadline_at`,
    `result_summary`, `case_status`;
  - `next_cursor: string | null`.
- Cache: `Cache-Control: no-store`.

### `GET /api/v1/assignments/{assignment_id}`

- Auth: тот же session/actor path.
- Call order:
  1. parse UUID;
  2. `current_actor`;
  3. actor-native wrapper существующего `AssignmentService.card` semantics;
  4. `get_assignment_card(performer_id, assignment_id)`;
  5. existing application owner проверяет
     `card.assignment.status in ACTIVE_ASSIGNMENT_STATUSES`;
  6. terminal, missing, foreign и test-run-invisible result одинаково
     становятся `404 not_found` с одинаковым body. История terminal
     assignments остаётся отдельным later slice по D-031.
- Response включает list fields и безопасную карточку задачи:
  `category_name`, `category_icon`, `task_kind`, `time_size`, `description`,
  `performer_instructions`, `completion_criteria`, `reward_per_performer`,
  `format`, `city`, `minimum_level`, `performer_slots`.
- Не выдавать: `performer_id`, raw Telegram ID, `creator_id`, admin IDs,
  `publish_command_id`, `terminal_command_id`, raw `input_payload`, raw
  `materials`, private dispute comment/evidence, audit/receipt identifiers,
  test-run internals. Если CB-53 докажет отдельный safe public-materials DTO,
  его можно переиспользовать; иначе materials остаются закрыты.
- Cache: `Cache-Control: no-store`.

Для list и detail отказ актуальной server-side actor/status проверки имеет
точный контракт `403 {"code":"assignment_unavailable"}`. Transport ловит
только соответствующий `PermissionError` существующего owner и добавляет
`assignment_unavailable` в текущий public error allowlist; невидимая detail
карточка по-прежнему схлопывается в `404 not_found`.

DTO не содержит `allowed_actions`: frontend не вычисляет допустимые переходы,
а CB-54 вообще не показывает mutation controls.

## Файлы и минимальный порядок реализации

Финальные frontend paths уточняются после merge CB-53; если shell имеет иной
закрытый route inventory, реализация останавливается и план обновляется, а не
создаёт второй router.

1. `src/community_bot/application/assignments.py`
   - добавить только actor-native read overload/entrypoint для `cards/card`,
     переиспользующий `get_member`, тот же UoW projection и active-status
     проверку detail;
   - добавить `get_member` в существующий assignment UoW protocol, следуя уже
     работающему precedent `TaskService.list_available`; не создавать новый
     identity adapter/service;
   - не менять domain states, mutation signatures или receipt semantics.
2. `src/community_bot/transport/web.py`
   - создать `AssignmentService`;
   - добавить DTO, cursor codec на stdlib и два GET routes;
   - сохранить единый error envelope и `no-store`.
3. CB-53-owned static assets
   - расширить существующий router/navigation и общий fetch helper;
   - добавить один экран list/detail, без нового framework/state layer.
4. `tests/integration/test_web_api.py`
   - один сценарий owner list/detail + active filter/cursor;
   - foreign/missing collapse, non-active denial и privacy whitelist.
5. CB-53-owned browser test file
   - один путь list → detail → back с loading/empty/error и keyboard oracle.
6. `tests/unit/test_web_auth.py`
   - обновить route inventory только если этот файл остаётся canonical после
     CB-53; отдельный дублирующий inventory test не создавать.

## Security, privacy и data integrity gates

- Сервер заново читает member/status; client/session claims не определяют
  ownership или permissions.
- Projection всегда scoped по internal performer ID. UUID из URL — только
  недоверенная подсказка.
- Foreign и missing detail неразличимы (`404`), чтобы не раскрывать existence.
- Terminal owner, foreign, missing и test-run-invisible detail неразличимы
  (`404` с exact одинаковым body), чтобы active-only route не становился
  скрытым history endpoint.
- Ответы whitelist-only, `extra=forbid`, `no-store`; логи не получают payload,
  cookie, Telegram proof или private case data.
- Read routes не создают receipt, ledger, audit, outbox и не меняют state.
- Existing test-run quarantine применяется до projection; обход через прямой
  URL запрещён.
- Время приходит в UTC ISO 8601; отображение локальной зоны использует
  существующий CB-53 helper/platform, не меняя authoritative timestamp.
- Никакой JS settlement/permission/action eligibility logic.

## Идемпотентность и concurrency

GET операции side-effect free и не требуют operation identity. Stable cursor
использует existing ordering tuple `(accepted_at, assignment_id)` и всегда
указывает на последнюю выданную, а не первую невыданную строку. Следующая
страница применяет строгий предикат «меньше cursor»; одинаковое `accepted_at`
разрешается UUID tie-breaker. Mutation receipt contract не затрагивается.

Любое обнаруженное требование POST, ledger/outbox change или изменение
assignment state переводит работу в stop/gap и требует owner-approved новый
slice.

## UI oracle

- Native path: `Мои задания → Взятые мной → Активные`.
- List row показывает title, status, deadline и краткий latest result state.
- Detail использует semantic heading/list/time elements, видимый focus,
  keyboard activation, системный back из CB-53 и Telegram/browser safe-area.
- Обязательные состояния: skeleton/loading, пустой список с возвратом в каталог,
  retryable network error, `401` re-auth boundary, `403` account unavailable,
  `404` detail removed/invisible.
- Не показывать disabled кнопки будущих mutations: это ложное обещание UI.

## Минимальные проверки

1. API integration scenario:
   - active owner видит только свои active assignments;
   - terminal assignment отсутствует при `status=active`;
   - terminal owner UUID, foreign UUID, missing UUID и test-run-invisible UUID
     дают одинаковые status/body `404 not_found`;
   - при одинаковом `accepted_at` test собирает все страницы и сравнивает
     exact ordered ID set без пропусков и дублей, получает `next_cursor=null`
     на последней странице и отдельно проверяет публичный `limit=50`;
   - populated raw `input_payload`, `materials`, private case/evidence и
     internal IDs не просачиваются: list/detail key sets сравниваются целиком с
     exact DTO contract, а не поиском отдельных строк;
   - до/после успешных и denied GET совпадают assignment/task state и counts
     receipts, account ledger, audit и outbox; read не имеет эффектов;
   - inactive actor получает exact
     `403 {"code":"assignment_unavailable"}`;
   - restart сохраняет тот же read result, если это помещается в тот же
     scenario без отдельной fixture/абстракции; иначе слабый restart assertion
     уступает прямому side-effect oracle.
2. Existing assignment lifecycle regression, без расширения full suite.
3. Один browser scenario list → detail → back и один empty/error variant в том
   же test, если это не ухудшает читаемость.
4. Route inventory/accessibility check, уже существующий после CB-53.
5. Контрольный повтор targeted tests и secret-like scan planned diff.

Full product regression, concurrency mutation tests и live Telegram session не
входят. Live Mini App acceptance остаётся CB-57 после deployment.

## Hard gates, stop и rollback

### До реализации

- CB-53 действительно merged в `origin/main` и её tests зелёные.
- Owner явно одобрил сужение CB-54 и read-only scope.
- Актуальная Jira CB-54 всё ещё соответствует плану; Jira write отдельно
  разрешён владельцем, если summary/description нужно обновить.
- Actor-native read glue помещается в existing owner без нового abstraction.

### Stop

- требуется переписать domain engine или изменить assignment states;
- нужен новый service/repository/table/dependency/framework;
- projection не может скрыть private input/material/dispute data;
- CB-53 route/API contracts конфликтуют с exact routes этого плана;
- test-run quarantine или foreign/missing collapse не доказаны;
- появляется POST без accepted HTTP receipt owner.

### Rollback

До merge — удалить только два GET routes, DTO и UI route slice из task branch.
Schema/data/ledger/outbox изменений нет. После deployment rollback — предыдущий
совместимый application image/static bundle; database downgrade не требуется.

## Soft targets и одноразовый audit

- Soft target: 3–5 production files поверх фактического CB-53 layout, 2 targeted
  test files, без line-golf.
- Dependencies/tables/services/repositories added: `0`.
- Domain lifecycle/settlement lines changed: `0`.
- Перед plan final review и перед implementation final review — один
  примерно 10-минутный audit очевидного мусора: удалить duplicate DTO/helper,
  inline one-use abstraction и лишний test; не расширять его в repo refactor.

## Последовательность later slices

1. Owner decision и minimal HTTP operation receipt bridge.
2. Performer `withdraw` как один POST с reason, exact replay и authoritative
   returned state.
3. Submission draft → preview → exact confirm → immutable result version.
4. Creator-owned tasks + review outcomes.
5. Group close intake/cancellation responses/replacement.
6. Performer dispute entry/history.
7. Community/admin/moderation capabilities — CB-55 или отдельные истории.
8. Notifications/deep links/deployment/acceptance — CB-56/CB-57.

## Решения владельца

До runtime нужны ответы «да/нет»:

1. Одобрить CB-54 как read-only slice «Мои активные назначения», сохранив весь
   остальной engine в roadmap.
2. Подтвердить, что `withdraw` и `submit` не входят в CB-54 и получат отдельные
   slices после решения HTTP operation receipts.
3. После merge CB-53 разрешить повторную сверку layout/API и только затем
   запуск реализации в `task/CB-54`.
