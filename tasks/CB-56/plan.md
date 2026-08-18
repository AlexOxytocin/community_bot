# CB-56 — Pareto-план web-service readiness

## Решение

Не реализовывать CB-56 целиком. Исходная задача соединяет четыре независимых
рисковых события и преждевременно считает production cutover обязательным.

Рекомендуемый единственный следующий slice — **A1: web-service readiness
текущего reviewed main**.

Наблюдаемый результат:

> Один image из точного reviewed tree запускает уже реализованный Mini App/API
> как отдельный `web` process рядом с существующими `migrate` и `worker`; local
> production-Compose gate доказывает HTTP liveness, PostgreSQL/migration/config,
> exact worker release + migration identity и отсутствие failed outbox events.

Slice не публикует порт на host, не выбирает TLS/DNS/proxy, не собирает
production host package, не импортирует DB и не выполняет deployment.

## Почему именно A1

| Кандидат | Наблюдаемый результат | Causal necessity сейчас | Риск | Решение |
| --- | --- | --- | --- | --- |
| A1 web process + readiness | Реальный Mini App стартует из image/Compose | Да: entrypoint/service отсутствуют | Средний | Выбрать |
| B image↔host-package provenance | Fail-closed deploy/rollback tuple | Нет до появления runnable web image и owner host boundary | Высокий | Отложить |
| C compact DB import/cutover | Новая compact DB принимает writes | Нет: Mini App уже работает с существующим backend/schema | Критический | Отложить |
| D production HTTPS/live acceptance | Public Mini App проверен на target | Нет без A1, B и owner go-live | Критический | Отложить |

Ponytail: отсутствие compact migration не мешает запустить текущую схему.
Добавление migration/import только ради соответствия старому roadmap увеличит
diff, data-loss surface и rollback complexity, не закрывая отсутствующий web
entrypoint.

## Процесс и owner gates

- Уровень 3: deployment/readiness и security-sensitive identity.
- Новый ADR для A1 не нужен: отдельный web process в одном image/монолите уже
  принят ADR-0016/0017. Направление B требует отдельного предложенного ADR и
  security review до любого расширения forced-command boundary.
- Этот plan package не разрешает implementation, Jira write/transition, branch,
  commit, push, PR, image publication или deployment.
- До implementation владелец должен выбрать один canonical Jira handling:
  1. **рекомендуется:** разрешить Jira write и сузить цель/acceptance CB-56 до
     A1, явно отложив B в отдельную связанную задачу, C в future compact-DB
     решение и D в CB-57; либо
  2. создать отдельную связанную Jira-задачу A1, оставив CB-56 целиком.
  Одного transition недостаточно. Текущий статус CB-56 остаётся
  `К выполнению`, а contract mismatch является hard blocker code/runtime.
- До любого production/runtime действия нужен отдельный owner go-live decision
  по target, HTTPS edge, immutable image producer и host-package boundary.

## Точная область реализации A1

### 1. Запускаемый web process

- Добавить `src/community_bot/bootstrap/web.py` как единственную composition
  boundary:
  - получить существующий `Settings`;
  - настроить существующие logging/Sentry без новых secret/config механизмов;
  - создать один `Database` и существующий `create_web_app`;
  - запустить один ASGI process на фиксированном container endpoint
    `0.0.0.0:8000`;
  - гарантированно закрыть DB engine при shutdown.
- Добавить console script `community-web`.
- Добавить только необходимый ASGI server dependency `uvicorn` без extras.
  FastAPI factory уже существует; новый web framework, DI/factory layer или
  process manager не создавать.

### 2. Liveness и readiness

В существующем `create_web_app` добавить два unauthenticated operational route,
не включающие secrets, identities или DB contents:

```text
GET /healthz -> 200 {"status":"alive"}
GET /readyz  -> 200 safe readiness JSON | 503 safe readiness JSON
```

- `/healthz` доказывает только, что ASGI listener/event loop отвечает.
- `community-web` фиксирует aware UTC `started_at` непосредственно перед
  созданием app. `create_web_app` получает этот timestamp как узкий
  `heartbeat_not_before` только для operational readiness; обычные тестовые
  factory-вызовы могут явно передать `None`.
- `/readyz` повторно использует существующий `readiness_report` с этим
  `heartbeat_not_before` и считается
  healthy только при одновременном выполнении:
  - PostgreSQL отвечает;
  - DB revision равна единственному packaged Alembic head;
  - active product config полна и member backfill не stale;
  - `community-worker` heartbeat свежий, не раньше старта текущего web process,
    не находится более чем на 5 секунд в будущем и имеет тот же `RELEASE`;
  - heartbeat migration revision равна packaged head;
  - failed outbox events равны нулю.
- Ответ содержит только существующие boolean/count/code поля; connection
  details, release string, revisions и error payload наружу не выводятся.

### 3. Устранить ложный worker readiness

- В `worker/entrypoint.py` заменить literal `0020` на
  `single_migration_head()` из уже существующего packaged migration contract.
- В `infrastructure/db/health.py` читать heartbeat `migration_revision` и
  fail-closed сравнивать его с packaged head.
- Добавить отдельный стабильный code `heartbeat_migration_mismatch`; неверная
  revision не маскируется свежим timestamp и совпавшим release.
- Добавить фиксированный clock-skew contract: heartbeat допускается максимум на
  5 секунд вперед; большее значение даёт `heartbeat_in_future`. Новый env knob
  для этого не создавать.
- Не менять schema, миграции, outbox semantics или worker loop.

### 4. Production-like Compose без production mutation

В `compose.production.yaml`:

- добавить один `web` service из того же `${COMMUNITY_BOT_IMAGE}` с command
  `community-web`;
- не добавлять host `ports`; объявить только internal container port `8000`;
- `web` подключить только к `internal`. Telegram auth proof проверяется
  локально; optional Sentry egress не является достаточной причиной расширять
  network boundary A1. Подключение будущего HTTPS edge решается в D;
- `worker` и `web` запускать только после successful `migrate`;
- healthcheck `web` выполнять stdlib HTTP request к
  `http://127.0.0.1:8000/readyz`, без `curl`/нового package;
- сохранить `postgres` непубличным и текущие bounded JSON logs.

`MINI_APP_ORIGIN` остаётся exact HTTPS external origin для auth boundary, но A1
не реализует termination. Это различает container readiness и public HTTPS.

### 5. Image evidence внутри A1

- В `Dockerfile` сохранить один generic image и добавить OCI revision label из
  существующего build arg `RELEASE`; описание обновить с worker-only на Mini
  App backend.
- PR CI A1 собирает image **synthetic merge commit**, задаёт
  `RELEASE=${{ github.sha }}`, запускает package/Compose checks и фиксирует
  local immutable image ID + OCI revision label. Это reviewed-tree image
  evidence, а не evidence будущего actual merge commit.
- Не восстанавливать `release.yml`, deploy scripts или shell wrappers в A1.

Локальный image ID не является production evidence. Перед будущим deploy
обязателен отдельный B gate:

```text
reviewed merge commit + verified merge-tree artifact
== OCI revision label + published GHCR sha256 digest
== deterministic host-package manifest/digest
```

Любое отсутствие или несовпадение останавливает работу до Docker/DB mutation.

## Точный план файлов

Runtime/config:

- `src/community_bot/bootstrap/web.py` — новый минимальный entrypoint;
- `src/community_bot/transport/web.py` — `/healthz` и `/readyz`;
- `src/community_bot/worker/entrypoint.py` — packaged migration head heartbeat;
- `src/community_bot/infrastructure/db/health.py` — heartbeat revision gate;
- `src/community_bot/bootstrap/settings.py` — в `production` принимать
  `RELEASE` только как полный lowercase 40-hex SHA; development `local`
  сохраняется;
- `pyproject.toml`, `uv.lock` — `community-web` и plain `uvicorn`;
- `compose.production.yaml` — `web`, migration ordering, internal healthcheck;
- `Dockerfile` — truthful description и OCI revision label.
- `.github/workflows/ci.yml` — exact synthetic-merge image build/inspection и
  disposable Compose readiness smoke, без push/release/deploy.

Проверки:

- `tests/unit/test_entrypoints.py` — web composition/startup/shutdown и worker
  packaged-head evidence без открытия реального listener;
- `tests/unit/test_package_metadata.py` — exact script set;
- `tests/unit/test_operations.py` — exact Compose services, no host ports,
  same image, command, networks, migrate dependency и healthcheck;
- `tests/unit/test_settings.py` — production full-SHA release validation;
- `tests/integration/test_notifications.py` — расширить существующую readiness
  matrix revision/not-before/future-skew cases, не создавать параллельную
  матрицу в `test_database_health.py`;
- `tests/integration/test_web_api.py` — liveness, ready/unready safe response;
- `tests/smoke/test_entrypoints.py` — безопасный обязательный
  `community-web --check`, который валидирует config/composition без listener и
  DB mutation.

Документация:

- `docs/mvp/TECH_STACK.md` — transitional runtime становится
  `postgres + migrate + worker + web`, всё ещё без public HTTPS;
- `docs/release-2/README.md` — различить A1 readiness, B provenance, C compact
  cutover и D live acceptance.

Soft ceiling: не более 10 runtime/config files, 6 test files и 2 docs files.
Если shutdown нельзя доказать без изменения `create_web_app`, допустима одна
узкая lifecycle правка в том же `web.py`; новый application abstraction
запрещён.

## Preflight implementation

До первого runtime edit исполнитель обязан:

1. Получить явное решение владельца: реализовать narrowed A1, не CB-56 целиком.
2. Read-only перепроверить Jira CB-56/CB-57 и зависимости; при разрешении
   владельца отдельно выполнить точный Jira transition, не предполагая имя.
3. Обновить `origin/main` и подтвердить exact base не ниже
   `7f2d14ef12c569e6e84daab49be2155a43be5657`; создать `task/CB-56` до code
   changes.
4. Подтвердить clean/preserved worktree и отсутствие несвязанных правок.
5. Подтвердить единственный packaged Alembic head, текущий Compose config и
   отсутствие `community-web`/public port.
6. Не читать `.env`, secrets или server state; использовать только safe
   placeholder values в локальных Compose checks.

## Минимальный test plan

### Быстрый gate

- Ruff format/lint и `ty` только по затронутым Python/tests.
- Unit tests entrypoint/package/Compose.
- `docker compose -f compose.production.yaml config --quiet` с placeholder env.
- До commit локальный dirty-worktree build допустим только как функциональный
  smoke и не называется provenance/commit evidence.
- После push PR CI строит synthetic merge tree с
  `RELEASE=${{ github.sha }}`; inspect проверяет non-root user,
  `community-web`, static assets, migration head и exact OCI revision.
- `compose.production.yaml` не использует fallback `manual`: для production-like
  gate `COMMUNITY_BOT_RELEASE` обязателен, контейнерный `RELEASE` равен полному
  SHA и совпадает с OCI revision. Production settings fail-closed отклоняют
  иное значение.

### Exact readiness integration

Один PostgreSQL scenario должен доказать по очереди:

1. exact DB head + complete config + свежий worker heartbeat с exact
   release/revision + zero failed outbox -> `/readyz` 200 `ready`;
2. missing/old/wrong-release heartbeat -> 503 с соответствующим safe code;
3. heartbeat revision `0020` при packaged `0021` -> 503
   `heartbeat_migration_mismatch`;
4. heartbeat позже observed time более чем на 5 секунд -> 503
   `heartbeat_in_future`; значение в допустимом skew не обходит остальные
   gates;
5. DB revision mismatch, incomplete config или failed outbox -> 503;
6. `/healthz` остаётся 200 при DB unready, доказывая отличие liveness от
   readiness;
7. responses не содержат database URL, release value, revision strings,
   exception text, token или Telegram identity.

### Image/Compose smoke

- Поднять только локальный disposable Compose project с placeholder secrets и
  ephemeral PostgreSQL; никаких host/production volumes.
- Выполнить migrations/config bootstrap, запустить worker и web из одного local
  immutable image ID.
- Дождаться `web` healthy, получить `/`, static asset и `/healthz` внутри
  Compose network; host port не публиковать.
- Зафиксировать `restart_started_at`, пересоздать web и worker с тем же exact
  release, до первого нового worker tick обязательно получить `503`, после
  heartbeat `observed_at >= restart_started_at` получить `200`; DB state не
  меняется.
- После smoke выполнить `docker compose down -v` только для явно именованного
  disposable project.

### Контрольный gate

- `uv run pytest -m "not browser"` после targeted green.
- `uv run pytest tests/browser --no-cov` один раз после runtime/image changes.
- `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run ty check src tests ops`, `git diff --check`.
- Secret-like scan только tracked diff; реальные env/secrets не читать.
- Level-3 `implementation-report.md` и независимый `final-review.md` до
  commit/push/PR.

## Health, stop и rollback

### Stop conditions A1

- web требует нового domain/service/repository, DB migration или data import;
- readiness нельзя доказать без раскрытия secret/identity/internal error;
- worker revision mismatch остаётся принимаемым;
- Compose публикует DB или web host port;
- требуется TLS/proxy/host mutation для локальной приёмки;
- image label не совпадает с exact checked tree;
- `COMMUNITY_BOT_RELEASE` отсутствует, не full SHA или не совпадает с OCI
  revision;
- любой target test выявляет schema/data mutation вне existing migrations.

### Rollback A1

A1 не выполняет production mutation. Локальный rollback — вернуть предыдущий
reviewed commit и удалить только `community-web`, operational routes и `web`
Compose service. Schema/data downgrade отсутствует.

Для будущего deployment rollback не разрешён этим планом. Он требует B:
previous compatible image + exact matching host package. Backup/restore должны
быть доказаны до deployment, но изменение backup/restore кода не входит в A1.

## Точно отложенная область

### B — immutable image↔host-package provenance

- новый deterministic manifest/artifact exact merge commit;
- current owner `AlexOxytocin`, без legacy `alexgoodman53`;
- fail-closed commit/image/package tuple;
- owner/mode/symlink/traversal/partial/stale проверки до Docker/DB;
- coordinated image/package rollback;
- новый ADR и security review до forced-command изменения.

### C — future compact DB import/cutover

- read-only production inventory;
- encrypted backup и isolated restore;
- separate compact DB, deterministic importer/reconciliation;
- mutation freeze, synthetic delta, first-real-mutation boundary;
- pre-write legacy rollback и post-write compatible-image rollback.

Ни один пункт C не нужен для A1, потому что A1 использует текущую authoritative
schema и не меняет данные.

### D — production deployment/live acceptance

- DNS/TLS/public HTTPS edge и target host;
- image publish/deploy;
- production backup/restore execution;
- owner go-live, Telegram launch и live CB-57 journeys.

## Blockers и точное решение владельца

После independent review implementation всё равно заблокирована до явного
решения владельца по Jira contract:

> «Разрешаю сузить Jira CB-56 до A1 и обновить её acceptance. Реализовать только
> web entrypoint, internal Compose service и честный readiness текущего backend.
> B оформить отдельно до deployment; C и D сейчас не выполнять».

Если владелец не хочет менять CB-56, требуется альтернативное точное решение:

> «Создать отдельную связанную Jira-задачу A1; CB-56 оставить без изменений».

Перед runtime/deploy потребуется отдельное решение владельца как минимум по:

1. конкретному существующему HTTPS edge/domain и допустимой сетевой границе;
2. отдельному B plan/ADR для image↔host-package provenance;
3. нужен ли вообще compact DB cutover C сейчас или он остаётся отложенным;
4. go-live target, maintenance/data-safety gates и live acceptance D.

Без этих решений A1 можно реализовать и проверить локально, но нельзя называть
public HTTPS или production delivery готовыми.
