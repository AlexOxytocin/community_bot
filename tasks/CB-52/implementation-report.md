# CB-52 — отчёт о реализации минимального Web foundation

## Итог

Реализована только foundation для первого Mini App slice: проверка raw Telegram
`initData`, короткая server-side session, logout/revoke и пять read projections
через существующие application owners. Добавлены ровно одна таблица
`web_sessions` и семь business/API operations. Domain mutations, frontend,
deployment, Uvicorn, CORS framework, cursor codec и operation framework не
добавлялись.

## Zero domain-engine rewrite

Production diff относительно
`4b05030edc90f8338cc050fcde41d5bc42d289c8` классифицирован полностью:

| Категория | Файлы | Результат |
|---|---|---|
| A — web/auth/session/DTO glue | `bootstrap/settings.py`, `infrastructure/db/models.py`, `infrastructure/db/database.py`, `application/identity.py`, `transport/web.py`, `migrations/versions/0021_web_sessions.py` | transport validation, session persistence/resolution/revoke и allowlisted serialization |
| B — механическая адаптация identity к существующему owner | `application/registration.py`, `application/reputation.py`, `application/tasks.py`, `infrastructure/db/registration.py` | Telegram-shaped caller заменён на server-created `ActorContext`; прежние проверки owners сохранены |
| C — business/domain outcome logic | нет | **ZERO** |

`web.py` не вычисляет visibility, permissions, levels, ledger, karma,
reliability, task eligibility, moderation или config outcomes. Route валидирует
wire/auth, строит `ActorContext`, вызывает существующий owner и сериализует
явный DTO allowlist.

Отдельный regression oracle фиксирует исходный default
`TaskService.list_available(limit=10)`. Во время self-audit временный default
20 был обнаружен до публикации, возвращён к baseline 10 и не входит в итоговый
business outcome. Web route передаёт собственный bounded wire limit явно.

## Реализованный контракт

- `POST /api/v1/auth/telegram`: exact Origin/content type, raw initData HMAC,
  freshness, existing-member lookup, 32 random bytes, SHA-256 digest-only
  persistence, `__Host-` cookie (`Secure`, `HttpOnly`, `SameSite=Strict`, 900 s).
- `DELETE /api/v1/session`: exact Origin, atomic idempotent revoke и удаление
  cookie; concurrent replay возвращает одинаковый безопасный результат.
- `GET /api/v1/me`, `/members`, `/members/{member_id}`, `/tasks`,
  `/leaderboard`: только server-side session actor и существующие read owners.
- Member query: omitted/empty/whitespace означает unfiltered; nonblank input,
  нормализующийся в blank (`@`, `@ `, `@@`), стабильно даёт
  `422 invalid_member_query`.
- Member/leaderboard возвращаются bounded list; task pagination переиспользует
  существующий UUID cursor. Универсального cursor codec нет.

## Simplicity evidence

- production Python/Alembic: **10 файлов**, **660 добавленных nonblank строк**
  при soft target `10/850`;
- tests: **7 файлов**, **712 добавленных nonblank строк** при soft target
  `7/730`;
- schema: **1** новая additive migration, **1** новая table;
- routes: **7** business/API operations плюс generated `GET /openapi.json`;
- dependencies: одна runtime (`fastapi`) и одна test (`httpx`);
- запрещённые `Repository`, `Gateway`, `Bus`, `Mediator`, `CQRS`, DTO/schema/cursor
  frameworks: 0;
- FastAPI/Starlette imports в `application`/`domain`: 0;
- Uvicorn, Redis, CORS middleware, frontend/deployment и domain mutation routes:
  0.

После owner checkpoint production вырос только с `626` до `660` nonblank строк:
это закрытая allowlisted error boundary и bounded cumulative auth-body reader.
Обе добавки закрывают подтверждённые security defects; route/domain scope не
изменён.

Числовые LOC/files counts по решению владельца являются review trigger, а не
acceptance blocker. Выполнен ровно один аудит тестового объёма:

| Группа | Отдельный риск |
|---|---|
| auth proof/body/error | HMAC/freshness, body limit до buffering, закрытые error codes/private detail и `no-store` |
| session | restart, revoke/replay/concurrency и повторная проверка current authority |
| DTO/route contract | allowlist, закрытый route set, query/cursor/default `limit=10` |
| migration | isolated `0020 → 0021`, preservation и exact DDL |
| mechanical regressions | прежние owners получают `ActorContext` без изменения outcomes |

Очевидных эквивалентных повторов без потери самостоятельного risk oracle не
осталось. Дальнейшая compaction ухудшала читаемость, поэтому line-golf
остановлен; target поднят до `730` с небольшим запасом над ясной версией.

## Проверки

- exact web/auth/session/migration coverage:
  `9 passed`; `transport/web.py` — **100% statements/branches**,
  `application/identity.py` — **100%**;
- affected application/integration/architecture set:
  **61 passed in 101.10s** (`--no-cov`; coverage проверяется отдельным exact
  прогоном);
- полный suite, один финальный прогон:
  **517 passed in 316.87s**, total coverage **81.43%** при gate 80%;
- Ruff format: `221 files already formatted`;
- Ruff lint: pass;
- `ty check src tests ops`: pass;
- lock check, Ruff lint, `ty`, `alembic heads` (`0021 (head)`) и
  `git diff --check`: pass;
- route-set regression, session restart/expiry/revoke, concurrent logout,
  status recheck, privacy allowlist и exact isolated migration lifecycle входят
  в tests;
- credential-shaped scan по production, migration, CB-52 artifacts и новым web
  tests: совпадений нет; frozen proof и test tokens являются искусственными
  fixtures и не содержат рабочих секретов.

Первый partial запуск affected set завершился nonzero только из-за глобального
80% coverage порога для неполного набора. Тот же набор воспроизводимо прошёл с
`--no-cov`; exact web coverage и полный coverage gate приведены отдельно выше.

Четыре blocker-а первого independent review закрыты: private framework detail
не покидает allowlist и любой API error получает `no-store`; auth body ограничен
до unbounded buffering для declared и chunked input; migration oracle проверяет
exact `0020 → 0021` preservation/DDL; все metrics/diff/secret gates считают
реальный `baseline...staged` delta. Production outcome category C остаётся
**ZERO**.

## Остаточный риск и следующий gate

CB-52 не поднимает executable web process и не выполняет deployment: это scope
CB-56. До commit требуется независимый `final-review.md` с отдельным verdict по
четырём identity-adaptation файлам и подтверждением **zero business outcome
change**. Любой иной verdict блокирует PR/merge и переход Jira в Done.
