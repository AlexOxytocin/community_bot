# CB-56 — отчёт о реализации A1

## Результат

Реализован только утверждённый slice A1: существующий FastAPI/static Mini App
запускается командой `community-web` из того же image, что `migrate` и
`worker`, и доступен только внутри Compose network. Public HTTPS, image
publication, host package, production deployment и live acceptance не
выполнялись.

Jira CB-56 сужена до A1 и переведена «В работе». Для независимого направления
B создана CB-65 под CB-48; она блокирует будущий rollout CB-57, но не локальную
реализацию CB-56. Compact DB import/cutover остаётся CB-64, public HTTPS и live
acceptance — CB-57.

## Изменения

- Добавлены plain `uvicorn` и console script `community-web`; entrypoint
  собирает существующий `create_web_app`, фиксирует UTC restart boundary и
  корректно закрывает DB engine.
- Добавлены `/healthz` и `/readyz`. Readiness fail-closed проверяет PostgreSQL,
  exact singleton packaged/DB Alembic head, product config, failed outbox и worker
  heartbeat с exact release, migration revision, freshness, restart boundary
  и пятисекундным future-skew пределом. Ответ не содержит URL, release или
  revision values.
- Worker больше не пишет literal migration revision: используется существующий
  `single_migration_head()`; тот же helper переиспользует readiness.
- Production settings отклоняют `RELEASE`, если это не полный lowercase 40-hex
  Git SHA.
- Compose образует линейную зависимость
  `postgres -> migrate -> worker -> web`. `web` подключён только к `internal`,
  имеет `expose: 8000`, но не имеет host `ports`.
- Docker image получил OCI revision label. PR CI строит непубликуемый image
  synthetic merge commit, проверяет identity и запускает disposable Compose
  smoke с реальным Uvicorn, liveness/readiness и restart boundary.
- Release 2 и technology-stack docs теперь честно отделяют A1 от B/CB-65,
  C/CB-64 и D/CB-57.

## Ponytail-аудит

Актуальный diff повторно сужен после аудита:

- удалены транзитивные Compose dependencies;
- удалены хрупкие строковые assertions по названиям CI steps, сохранён
  fail-closed `verified-merge-tree.needs: image-contract`;
- устранено второе чтение Alembic graph;
- hard blocker неполного image check закрыт живым disposable Compose smoke без
  production действий и без нового framework/service/secret mechanism.
- По independent final review process-level DB engine перенесён в существующий
  FastAPI lifespan, поэтому shutdown выполняется в Uvicorn event loop; Alembic
  gate требует ровно одну DB revision и отклоняет лишний head.

## Проверки

- `uv run ruff format --check .` — green;
- `uv run ruff check .` — green;
- `uv run ty check src tests ops` — green;
- targeted unit/readiness gate — `40 passed, 6 deselected`;
- local image build — green; OCI revision равна
  `7f2d14ef12c569e6e84daab49be2155a43be5657`, packaged head `0021`,
  `community-web --check` green;
- disposable production Compose contract — green: initial `/healthz=200`,
  `/readyz=200`; после stop worker + restart web `/healthz=200`,
  `/readyz=503`; после нового worker heartbeat `/readyz=200`; затем project и
  volumes удалены;
- полный suite после terminal independent review — `533 passed`, coverage `81.48%` при пороге
  80%; browser и PostgreSQL tests включены;
- `git diff --check` — green.

Первый PR run подтвердил Quality и PostgreSQL jobs, но обнаружил quoting defect
в Go template OCI-label inspection до запуска Compose smoke. Backslash внутри
single-quoted Bash template удалён; это CI-only исправление проверено точечной
operations-проверкой и повторным обязательным PR run.

## Отклонения от предварительного file map

Operational route contract проверяется в существующем
`tests/unit/test_web_auth.py`, а не отдельным сценарием в
`tests/integration/test_web_api.py`: PostgreSQL readiness matrix уже расширена
в `tests/integration/test_notifications.py`, поэтому второй DB-heavy набор был
бы дублированием. Отдельный smoke test file не добавлен: реальный
`community-web --check` и listener/restart path выполняются непосредственно в
Docker/Compose CI gate. Runtime acceptance при этом не сужена.

## Rollback и остаточные gates

A1 не меняет schema/data и не выполняет production mutation. Локальный rollback
удаляет `community-web`, operational routes и `web` Compose service возвратом к
предыдущему reviewed commit; DB downgrade не нужен.

До любого production действия остаются обязательными отдельные owner gates:

1. CB-65: published digest ↔ deterministic protected host-package provenance,
   security review и парный rollback contract;
2. конкретный HTTPS/DNS/TLS edge и target;
3. backup/isolated restore evidence на target;
4. CB-57 deployment и live Mini App acceptance.

CB-64 compact cutover не является precondition текущего backend и остаётся
отложенным. Deployment/live acceptance не объявляются готовыми.
