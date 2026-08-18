# CB-57 — независимая финальная проверка

**Контракт:** `community_bot.final_review.verdict.v1`

Status: approved

## Findings

Обязательных исправлений не осталось.

Единственное замечание первой попытки закрыто consolidated diff: уже выданный
conditional owner gate теперь однозначно применяется без нового вопроса только
после green public smoke и zero-backlog recheck; до выполнения условий
worker/outbound остаются остановленными. Это одинаково отражено в основном
порядке cutover, шагах реализации и gate 15 ручного test plan. Общее правило о
новом owner gate для будущих migration-changing releases сохранено корректно.

## Проверенная реализация

- Fresh-session bootstrap сначала проверяет `/api/v1/me`, только на первом
  `401` читает непустой `Telegram.WebApp.initData`, отправляет raw body одним
  POST с exact `Content-Type: text/plain; charset=utf-8` и same-origin
  credentials, затем допускает только один retry. Missing/invalid proof и
  existing-session paths закрыты без auth loop.
- Official bridge находится в `<head>` до app module. CSP расширена только на
  `https://telegram.org`; `unsafe-inline`, новый connect origin, storage,
  логирование proof, frontend package или framework не добавлены. Официальная
  Telegram Mini Apps documentation подтверждает этот порядок и обязательную
  server-side validation `initData`.
- Existing backend сохраняет exact Origin check, bounded body, HMAC validation,
  freshness check и Secure/HttpOnly/SameSite session cookie. Browser oracle не
  использует внешний script или реальный Telegram proof и проверяет отсутствие
  proof в URL, storage и console.
- Permanent process contract соответствует ADR-0019: deploy/skip classification,
  serialized monotonic supersession, migration owner gate, один compatible
  rollback, public smoke/Jira evidence и запрет `Done` до smoke или waiver.
- Data cutover и edge остаются manual-first stop-on-failure планом поверх
  ADR-0018/`ops/release_contract.py`; immutable Compose, release activator,
  migration и dependencies не изменены. Release 71 везде отделён как baseline,
  а не deploy candidate.
- Jira CB-57 прочитана без изменений: задача остаётся `В работе`, dependencies
  CB-54/55/56/65 — `Готово`, production gates честно не объявлены выполненными.
- Scope не заявляет full backend parity; server IP, credentials, private key,
  Telegram token, secret assignment или raw proof в diff/task artifacts не
  найдены.

## Воспроизведённые проверки

- `uv run pytest tests/browser/test_mini_app.py tests/unit/test_web_auth.py tests/architecture/test_agent_orchestration_policy.py --no-cov -p no:cacheprovider -q` — `30 passed`.
- `uv run pytest -m "not integration and not browser" --no-cov -p no:cacheprovider -q` — `417 passed, 149 deselected`.
- `uv run pytest -m integration --no-cov -p no:cacheprovider -q` — `145 passed, 421 deselected`.
- `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run ty check src tests ops`, `git diff --check` — green.
- Official script URL без query и актуальный documented URL с `?63` на момент
  проверки возвращали одинаковые bytes; unversioned official URL реализации
  не является найденным дефектом.

## Ponytail

Lean already. Ship.

Новых abstractions, daemon, deployment framework, SSH workflow или dependencies
в diff нет; сокращение runtime/process diff без потери принятого контракта не
найдено.

## Оставшаяся неопределённость

PR/main CI, новый exact release artifact, host preflight, backup/restore,
migration, edge, rollback rehearsal и public smoke ещё не выполнялись. Это не
блокирует готовность ветки к PR, но CB-57 не может получить `Done` до их green
evidence либо отдельного owner waiver. Live Telegram interaction отдельно не
разрешена; её нельзя подменять чтением chats, отправкой сообщений или скрытым
production proof.
