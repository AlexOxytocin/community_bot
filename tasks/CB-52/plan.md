# CB-52 — минимальный план auth/session и read API foundation

## Результат и уровень процесса

На refreshed baseline
`4b05030edc90f8338cc050fcde41d5bc42d289c8` добавить самый маленький
end-to-end foundation, который позволяет CB-53 начать Mini App: проверить
Telegram `initData`, выдать короткую opaque server session, получить
server-side `ActorContext` и прочитать существующие безопасные проекции через
versioned `/api/v1`.

Уровень: `3`. Причины — новая auth trust boundary, cookie/session security,
публичный API contract и additive migration. До runtime implementation нужны
`plan-source-context.md`, независимый `plan-review.md` и явное одобрение
владельца. Если разрешённый review run завершён `changes_requested`, его
findings сохраняются, исправляются в плане и требуют отдельного решения
владельца; автор плана не меняет verdict задним числом.

Новый ADR не создаётся: Mini App-only, FastAPI, internal actor, server
session, PostgreSQL и stdlib Telegram verification уже покрыты принятыми
ADR-0016/0017 и сохраняемыми security-частями ADR-0014.

## Scope

### 1. Identity и Telegram proof

- Добавить небольшой immutable `ActorContext` только с internal `member_id`,
  provider и `authenticated_at`; role/status/permissions в него не помещать.
- Проверять raw Telegram `initData` на сервере стандартными `urllib.parse`,
  `hmac`, `hashlib` и `json`: ограничение размера, строгий разбор, запрет
  дублирующихся ключей, обязательные `hash`, `auth_date`, `user.id`, HMAC и
  constant-time comparison, не более 32 полей, положительный 64-bit user ID,
  максимальный возраст 5 минут и future skew не более 30 секунд.
- Не принимать `initDataUnsafe`, Telegram ID из body/query/header и client
  claims как authority.
- Raw proof, bot token, cookie/session token и Telegram ID не логировать и не
  возвращать в API DTO.
- Auth exchange разрешает session только существующему member. Создание
  member/public registration не происходит в auth endpoint.
- Wire input: `Content-Type: text/plain; charset=utf-8`, raw UTF-8 body не
  более `8192` bytes. До parsing выполняются `Content-Length` fail-fast и
  bounded cumulative ASGI stream read. Используется `parse_qsl` со strict parsing,
  `keep_blank_values=True`, `max_num_fields=32` и strict UTF-8; duplicate
  любого key отклоняется.
- HMAC contract следует Telegram буквально: percent-decode пары; извлечь и
  исключить только `hash`; остальные `key=value` (включая `signature`, если
  он присутствует) отсортировать по key и соединить `\n`; secret key =
  `HMAC-SHA256(key=b"WebAppData", msg=bot_token)`; expected hash =
  `HMAC-SHA256(key=secret_key, msg=data_check_string).hexdigest()`;
  сравнить через `hmac.compare_digest`. Только затем проверять freshness и
  разбирать `user` JSON; до успешной проверки `user.id` не используется.

### 2. Короткая server session

- Добавить одной Alembic revision только таблицу `web_sessions`:
  `token_digest BYTEA PRIMARY KEY`, `member_id UUID NOT NULL REFERENCES
  members(id) ON DELETE RESTRICT`, `created_at TIMESTAMPTZ NOT NULL DEFAULT
  now()`, `authenticated_at TIMESTAMPTZ NOT NULL`, `expires_at TIMESTAMPTZ
  NOT NULL`, nullable `revoked_at TIMESTAMPTZ`; checks:
  `octet_length(token_digest)=32`, `expires_at>created_at`,
  `authenticated_at<=expires_at`, `revoked_at IS NULL OR
  revoked_at>=created_at`. Primary key является единственным digest lookup
  index; неиспользуемые cleanup/member indexes не добавляются.
- Raw session token — ровно 32 bytes из `secrets.token_bytes(32)` (256 bits
  entropy). Cookie wire value — canonical unpadded base64url этих bytes
  (`base64.urlsafe_b64encode(...).rstrip(b"=")`), ровно 43 ASCII characters;
  lookup key — `hashlib.sha256(raw_token_bytes).digest()`, ровно 32 bytes.
  Raw token существует только в cookie/памяти ответа; в PostgreSQL хранится
  только digest. Insert session завершается до формирования cookie; duplicate
  digest/DB failure возвращает generic `503`, не выдаёт cookie и не оставляет
  partial row. Session TTL — 15 минут; истёкшая или revoked session fail-closed.
- Cookie: `__Host-community_session`, `Secure`, `HttpOnly`,
  `SameSite=Strict`, `Path=/`, без `Domain`, `Max-Age=900`. Каждая успешная
  auth exchange выдаёт новый random token и отдельную session с абсолютным
  TTL; sliding refresh отсутствует. Logout выставляет cookie `Max-Age=0`.
- `DELETE /api/v1/session` требует exact configured `Origin`, атомарно ставит
  `revoked_at`, очищает cookie и возвращает тот же `204` при exact replay,
  уже revoked/expired либо отсутствующей cookie. Отдельный operation receipt
  для logout не создаётся.
- Новый app instance после restart разрешает ещё живую session из PostgreSQL;
  process memory не является источником session state.
- Auth, logout и все authenticated responses, включая errors, получают
  `Cache-Control: no-store`.

### 3. Минимальный versioned read API

Ровно семь business/API operations входят в CB-52:

| Method/path | Success | Назначение |
|---|---:|---|
| `POST /api/v1/auth/telegram` | `204` | proof → session cookie |
| `DELETE /api/v1/session` | `204` | revoke/logout, exact replay |
| `GET /api/v1/me` | `200` | собственный профиль, баланс, опыт и уровень |
| `GET /api/v1/members` | `200` | bounded safe active member list с search/limit |
| `GET /api/v1/members/{member_id}` | `200` | safe member card с одинаковым not-found/forbidden response |
| `GET /api/v1/tasks` | `200` | доступные actor-у member/group/community task cards |
| `GET /api/v1/leaderboard` | `200` | bounded server-side leaderboard |

- FastAPI routes только валидируют transport input, получают `ActorContext`,
  вызывают существующий application owner и сериализуют privacy-safe DTO.
- Тронутые read methods заменяют `telegram_user_id` на `ActorContext`/internal
  `member_id` без временного `int | ActorContext` overload и без параллельного
  compatibility method. Все существующие production/test call sites этих
  methods мигрируют атомарно в том же diff. Методы повторно читают актуальный
  member/status/role/permissions/ownership из PostgreSQL; session claims этого
  не заменяют.
- OpenAPI генерирует FastAPI. Отдельные schema generator, client SDK, DTO
  framework и route registry не создаются. Допускается только сгенерированный
  `GET /openapi.json`; Swagger/ReDoc routes отключены.
- Общий минимальный error body — `{ "code": "<stable_code>" }` без internal
  details. Невалидный/unknown auth и отсутствующая/истёкшая session возвращают
  одинаковый `401`; wrong/missing Origin — `403`; скрытый и отсутствующий
  member — одинаковый `404`; transport validation — `422`.
- `/members` принимает optional `query` и `limit` default `30`, range `1..50`.
  Omitted, empty или whitespace-only raw query после outer trim означает
  список без фильтра. Любой непустой raw query route делегирует существующему
  `normalize_member_search_query`: удаление всех leading `@`, Unicode
  whitespace collapse через `split/join`, затем `casefold()`. Если такой
  непустой input нормализовался в пустую строку (например, `"@"`, `"@ "` или
  `"@@"`), либо итоговая длина вне `3..80` Unicode code points, route возвращает
  stable `422 invalid_member_query`. Ответ — один bounded list без cursor.
  `/leaderboard` принимает только `limit` с теми же bounds и также возвращает
  один list: продуктовая когорта 20–30 человек не оправдывает pagination
  codec. `/tasks` переиспользует существующий UUID keyset: optional query
  `cursor` — canonical UUID предыдущей task, `limit` default `20`, range
  `1..50`. Malformed UUID отклоняется transport validation с `422`; валидный
  UUID отсутствующей, устаревшей или более не видимой actor-у task сохраняет
  фактическую семантику owner-а и детерминированно начинает с первой видимой
  страницы, не подтверждая существование записи. Cursor framework, opaque
  codec и version registry не создаются.
- Закрытые DTO allowlists:
  - `/me`: `member_id`, `display_name`, `city`, `timezone`, `short_bio`,
    `current_goal`, `help_categories`, `skill_tags`, `availability`,
    `credit_balance`, `experience_total`, `level {number,display_name}`;
  - member item: `member_id`, `telegram_username`, `display_name`, `city`,
    `short_bio`, `current_goal`, `help_categories`, `skill_tags`,
    `availability`, `experience_total`, `level_number`,
    `karma {score,count}`, `reliability
    {accepted,approved_weight,no_show,rate}`; Decimal values — canonical
    decimal strings либо `null`, не binary float;
  - task item: `id`, `origin`, `author_display_name`, `category_name`,
    `category_icon`, `task_kind`, `time_size`, `title`,
    `credit_reward_per_performer`, `performer_slots`, `minimum_level`, `format`,
    `city`, `deadline_at`, `status`; internal creator/admin/reviewer/template
    IDs, reserve, command IDs, test-run ID и input/material payload исключены;
  - leaderboard item: `rank`, `member_id`, `display_name`, `experience`,
    `unique_recipients`, `reliability` как decimal string/null, `no_show`.
  Response models создаются явно; application dataclass целиком не
  сериализуется. List responses имеют только `items`; task response — `items`
  и `next_cursor` UUID/null.
- Same-origin contract: CORS middleware отсутствует. Unsafe auth/logout
  requests принимаются только с точным configured `Origin`; прямой URL не
  обходит server authorization.
- `Settings.mini_app_origin` остаётся optional для worker. Только web app
  factory fail-fast проверяет nonempty bot token и один canonical HTTPS origin:
  scheme `https`, hostname обязателен, optional numeric port допустим,
  userinfo/path/query/fragment/trailing slash, wildcard/regex/prefix comparison
  запрещены. Ошибка не печатает secret/config value и не мешает worker startup.

## Non-scope: сначала отказ от лишнего

- Нет profile/task/assignment/karma/moderation/admin domain mutations.
- Нет общего HTTP operation receipt: без domain mutation он не имеет consumer.
  `processed_telegram_updates` не расширяется, не переименовывается и не
  используется как HTTP idempotency store.
- Нет отдельного one-time-proof registry: официальный Telegram contract
  требует integrity + freshness, а CB-52 не создаёт второй replay store без
  domain effect. Повторный валидный proof в пятиминутном окне может выдать
  отдельную короткую session; logout/revoke действует на конкретный token.
- Нет полного API CB-53—CB-55, template/admin catalog routes, balances history,
  raw karma, reliability detail, disputes, appeals, sanctions, interaction
  alerts, config administration или notifications API.
- Нет registration/onboarding write flow; CB-53 добавляет его вместе с UI и
  реальным mutation acceptance.
- Нет generic repository/service/DTO framework, CQRS, event bus, schema
  generator, client SDK, Redis, broker, microservice, DI container или
  универсального middleware.
- Нет frontend/static assets, browser auth, public registration, CORS matrix,
  rate-limit framework, TLS/edge/deployment/observability и live Telegram
  acceptance. Edge rate limiting и public ingress — gate CB-56.
- Нет schema consolidation/import, переписывания существующих migrations и
  удаления `processed_telegram_updates`/conversation state.

## Планируемое владение файлов

После одобрения плана один developer владеет runtime diff. Другие агенты не
редактируют эти файлы параллельно.

| Файл | Изменение |
|---|---|
| `src/community_bot/application/identity.py` | `ActorContext` без authority claims |
| `src/community_bot/application/registration.py` | own-profile read по internal actor |
| `src/community_bot/application/reputation.py` | safe members/profile/leaderboard reads по internal actor |
| `src/community_bot/application/tasks.py` | available-task read по internal actor |
| `src/community_bot/infrastructure/db/models.py` | `WebSessionModel` |
| `src/community_bot/infrastructure/db/database.py` | session lookup/create/revoke и internal-member delegates |
| `src/community_bot/infrastructure/db/registration.py` | own-profile projection принимает internal `member_id` вместо Telegram identity |
| `src/community_bot/transport/web.py` | proof validation, session dependency, FastAPI routes/DTO/error mapping |
| `src/community_bot/bootstrap/settings.py` | exact Mini App origin; существующий secret `bot_token` переиспользуется |
| `migrations/versions/0021_web_sessions.py` | additive session table only |
| `pyproject.toml`, `uv.lock` | FastAPI; `httpx` в test group для прямых ASGI tests; Uvicorn отложен до CB-56 |
| `tests/unit/test_web_auth.py` | proof/cookie/auth exact cases |
| `tests/integration/test_web_api.py` | session/restart/logout/read/privacy slice |
| `tests/architecture/test_import_boundaries.py` | exact route/import boundary без нового отдельного framework test |
| `tests/integration/test_registration.py` | существующие own-profile calls атомарно перевести на internal actor |
| `tests/integration/test_reputation.py` | существующие profile/members/leaderboard calls перевести на internal actor |
| `tests/integration/test_task_creation.py` | существующий available-task call перевести на internal actor |
| `tests/integration/test_core_workflows.py` | существующие reputation calls перевести на internal actor |
| `docs/release-2/README.md` | исправить фактические результаты CB-51 и узкий foundation CB-52 |

`plan-review.md` принадлежит независимому `plan-reviewer`; runtime author его
не пишет и не принимает ADR за владельца.

## Machine-checkable simplicity targets и hard gates

Числовые targets считаются от baseline
`4b05030edc90f8338cc050fcde41d5bc42d289c8`. Это soft review triggers, а не
acceptance blockers: при превышении выполняется один короткий аудит очевидных
дублей, лишнего файла или зависимости. Line-golf и отдельный рефакторинг ради
числа запрещены; после аудита сохраняется ясная версия с обоснованием:

- target `10` изменённых/новых production Python/Alembic файлов и `850`
  добавленных nonblank production Python lines;
- target `7` test files и `730` добавленных nonblank test lines; четыре
  существующих integration files меняются только механически для actor
  signature migration, новые scenarios остаются в двух web test files;

Для текущего staged delta получены `10/660` production и `7/712` tests.
Единственный budget-аудит завершён: tests классифицированы как auth
proof/body/error, session restart/revoke/current authority, DTO/route contract,
migration DDL/preservation и mechanical regression adaptations. Очевидных
повторов, которые можно удалить без потери читаемости или отдельного risk
oracle, не осталось; дальнейшая compaction остановлена решением владельца.

Hard gates, которые числовой target не ослабляет:

- ровно `1` новая table и `1` additive Alembic revision;
- ровно `7` business/API operations из таблицы выше плюс generated
  `GET /openapi.json`; отсутствие любого или появление другого route блокирует
  gate до изменения плана;
- не более `1` новой direct runtime dependency (`fastapi`) и `1` реально
  используемой test dependency (`httpx`); Uvicorn добавляет CB-56 вместе с
  executable process/deployment smoke;
- `0` imports FastAPI/Starlette в `domain` и `application`;
- `0` новых файлов/символов с именами `Repository`, `Gateway`, `Bus`,
  `Mediator`, `CQRS`, `DTOFactory`, `SchemaGenerator`, `CursorCodec`,
  `CursorRegistry`;
- `0` domain mutation routes и `0` новых operation receipt tables.
- `0` изменений business/domain outcomes: production diff классифицируется как
  (A) web/auth/session/allowlisted DTO glue или (B) механическая передача
  `ActorContext` существующему owner. Категория (C) business/domain logic
  обязана оставаться пустой; transport не повторяет visibility, permissions,
  levels, ledger, karma, reliability, task/config/moderation rules.

Проверка использует только staged task delta:
`git diff --cached --name-only/--numstat
4b05030edc90f8338cc050fcde41d5bc42d289c8`, а nonblank additions считаются
по `git diff --cached --unified=0` (без `+++` headers). Дополнительно проверяются
точный count `__tablename__`, dependency diff, `rg` по запрещённым
imports/symbols и test,
сравнивающий фактический FastAPI route set с закрытым списком. Превышение
числового target само по себе не блокирует приёмку после описанного аудита;
hard invariant, security oracle или ясность теста ради target не урезаются.

## Минимальная тестовая матрица

| Gate | Exact cases | Доказательство |
|---|---|---|
| Telegram proof | frozen valid/tampered vectors; stale/future `auth_date`; duplicate/missing/malformed field; exact 8192 boundary; oversized declared/chunked body | `Content-Length` fail-fast не читает stream; cumulative reader прекращает chunked body после превышения; Telegram ID/raw proof отсутствуют в output/log capture |
| Session issue | existing member; unknown identity; exact 32-byte CSPRNG → 43-char unpadded base64url → SHA-256 digest mapping; digest-only storage; duplicate digest/DB failure без row/cookie; exact cookie flags; expiry | integration test с PostgreSQL и monkeypatched entropy только для deterministic oracle |
| Session authority | active/paused/blocked statuses по действующим projection rules; role/status change после issue учитывается немедленно | тот же integration scenario читает member заново |
| Logout replay | live, repeated, revoked, expired, absent cookie; wrong/missing Origin; два concurrent `DELETE` с одной cookie получают одинаковый `204`, один переход `revoked_at IS NULL → value`, затем read `401`, оба ответа имеют exact clear-cookie и `no-store` | один parameterized branch плюс один PostgreSQL concurrency case, всегда zero duplicate effects |
| Restart | session создана app instance A, прочитана app instance B, затем revoked и более не принимается | PostgreSQL restart probe без process cache |
| Migration preservation | isolated `0020 → 0021` сохраняет tables/row counts и добавляет exact columns/defaults/PK/FK/unique/index/check contract; downgrade удаляет только `web_sessions` | один PostgreSQL migration scenario в существующем web integration test file |
| Read projections | `/me`, bounded members list/detail privacy; member query: omitted/`""`/whitespace-only → без фильтра; nonblank `"@"`/`"@ "`/`"@@"` и normalized lengths `1`,`2`,`81` → stable `422`; multiple leading `@`, repeated whitespace и Unicode casefold; normalized lengths `3`,`80` → delegated search; tasks: malformed UUID → `422`, missing/hidden valid UUID → первая видимая page; bounded leaderboard order | API smoke + переиспользованные domain/integration assertions |
| Privacy/errors | Telegram ID/raw karma/private moderation fields отсутствуют; hidden/missing member indistinguishable; stable 404/405; structured detail и unexpected owner 500 закрыты generic allowlisted code; любой error `no-store` | exact body/header assertions, ASGI transport с отключённым re-raise только для 500 oracle |
| Boundaries | exact 7 operations + `/openapi.json`, no docs UI, no domain/application FastAPI import, no old chat UI | architecture test |
| Web config/cache | missing/empty bot token; malformed/non-HTTPS origin; worker без origin; `no-store` на success/error | unit + ASGI header assertions без нового test file |

После точечных tests выполняются один раз существующие gates:

1. `uv run pytest tests/unit/test_web_auth.py tests/integration/test_web_api.py --no-cov`;
2. targeted coverage только изменённых auth/read runtime-модулей с branch
   report; новые proof/session/Origin enforcement modules обязаны иметь 100%
   branch coverage, остальные read adapters — объяснение каждой незакрытой
   branch;
3. `uv run ruff format --check .`, `uv run ruff check .`,
   `uv run ty check src tests ops`;
4. полный `uv run pytest` для текущего CI contract;
5. `git diff --check`, machine simplicity gate и secret/log scan.

Live Mini App, real Telegram chat reads/messages и deployment не выполняются.

## Security invariants

1. Только server-verified `initData` разрешается в internal existing
   `member_id`; клиент не задаёт actor.
2. Session хранит identity и время authentication, но не актуальные права.
3. Каждый read use case повторно применяет PostgreSQL status/role/permission/
   ownership/visibility rules.
4. Cookie/session token, raw proof, bot token, Telegram ID и private fields не
   попадают в логи, DTO, audit payload или task artifacts.
5. Digest collision/duplicate token, expired/revoked session, invalid Origin и
   невалидный proof fail-closed без частичного session effect.
6. Logout exact replay детерминирован и не требует общего idempotency layer.
7. Existing domain, ledger, audit, outbox, test-run quarantine и все business
   capabilities не меняются этим read-only slice.

## Stop и rollback

### Stop

- actor можно подменить Telegram ID/client claim либо route обходит session;
- session продолжает работать после expiry/revoke или после server-side
  status/permission запрета;
- raw secret/proof/session/private field попадает в лог или response;
- safe projection требует копирования business visibility rule в route;
- появляется необходимость domain mutation, generic operation/middleware/
  repository framework или восьмого route;
- migration меняет существующую table/data либо полный/targeted test расходится;
- hard simplicity invariant нарушен либо soft target превышен без однократного
  аудита и зафиксированного объяснения.

### Rollback

- До deployment CB-56 откатить только commit CB-52 и additive migration
  `0021`; существующие 43 tables, migrations и данные не трогать.
- Если `web_sessions` уже получила test rows, сначала выключить API, затем
  удалить только эту таблицу downgrade-операцией; sessions не являются
  business history.
- Runtime/image/production cutover CB-52 не выполняет. Rollback публичного
  HTTPS принадлежит CB-56.

## Критерии перехода к CB-53

CB-53 разблокируется только когда:

- независимый review завершён, все его findings отражены в плане, а владелец
  явно принял post-review corrections и разрешил implementation;
- после реализации CB-52 auth/session/logout и ровно пять read projections
  проходят exact tests, targeted/full CI, privacy/secret и simplicity gates;
- migration additive, restart/revoke доказаны, OpenAPI содержит точные семь
  routes;
- branch CB-52 прошла commit/push/PR/CI/review/merge в `main`;
- Jira CB-52 отражает фактический результат, а не «полный API CB-53—CB-55»;
- CB-53 получает право добавлять первый domain mutation только вместе с
  конкретным UI consumer, server-side authorization и operation identity.

## Terminal текущей фазы

Владелец принял `@ → 422` и разрешил ровно один следующий независимый recheck.
Recheck завершён точным `Status: approved`; owner authorization разрешает
runtime implementation в пределах этого плана. Перед final review отдельно
доказываются zero-domain-engine rewrite и production/test simplicity budgets.
