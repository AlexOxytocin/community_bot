# CB-57 — контекст и источники плана

## Jira

- Задача: CB-57, `В работе`, «Выполнить первый production pilot deploy Mini App
  и закрепить post-task delivery gate»; описание актуализировано 2026-08-18.
- Родитель: CB-48, Community Mini App.
- Проверенные зависимости: CB-54, CB-55, CB-56 и CB-65 — `Готово`.
- Комментарии: CB-65 блокировала только rollout; после её завершения blocker
  снят. Planning comments фиксируют branch и discovered project mismatch.
- Критерии: exact artifact, owner-gated data cutover/migration/edge, public smoke,
  permanent deploy/skip classification и Jira evidence без false parity claim.

## Документация и ADR

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: Jira-first, level 3 plan/review,
  Russian artifacts, no secrets, deployment не равен локальной готовности.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `agents/workflow.yaml`:
  lifecycle, transitions, review и Jira evidence; здесь будет закреплён новый
  post-merge delivery gate.
- `docs/release-2/README.md`: CB-57 владеет public HTTPS/deploy/live acceptance;
  schema change требует отдельного owner gate.
- ADR-0016: Mini App — единственный UI, old bot runtime не восстанавливается как
  product direction.
- ADR-0017: backend capabilities сохраняются, но текущая UI-доступность не может
  быть выведена из будущего parity intent.
- ADR-0018: exact reviewed image+host package, manual-first activation, no SSH/CD,
  strict same-head preflight, pending semantics и одна compatible previous tuple.
- `ops/release_contract.py`: initial activation устанавливает package, затем
  `_preflight` выполняет Compose config, image/live head equality и только после
  этого пишет `pending` и запускает worker/web.
- `ops/backup_postgres.py`, `ops/restore_drill.py` и `ops/_runtime.py` требуют
  selected release с `active.json=ready`; они не могут выполнить initial backup
  old unmanaged project или production restore до activation. One-time cutover
  использует native `pg_dump`/`pg_restore` operator commands; после activation
  canonical Python ops снова обязательны.
- Telegram Mini Apps primary documentation, раздел `Initializing Mini Apps`:
  official bridge загружается в `<head>` до других scripts; raw `initData`
  передаётся backend и используется только после server-side validation:
  https://core.telegram.org/bots/webapps.

## Факты о репозитории

- Base `30ad7277e8cc23698706e32e583c1d78044286c4`; branch `task/CB-57` создана от
  exact `origin/main` в изолированном worktree.
- Release run `32106370758`, `#71/1`, success; artifact id `9313314990`;
  manifest SHA-256 `2de8c1a18c01bf00e5cee3e07ffc0c9b9fd8e2cd3ac2961cc67b5ec6e37249af`;
  image digest `sha256:4090e0306fe275adb2119d8450c4c3035f186f261bd31ce31a56adb81a804d9f`;
  target head `0021`.
- Эти identities являются baseline publication evidence. Production candidate —
  новый exact green release merge CB-57 после fresh-session fix; его complete
  identities фиксируются перед go-live, а не угадываются в плане.
- `compose.production.yaml` имеет top-level project `community-mini-app-core`,
  internal-only `web:8000`, no host ports и service chain
  `postgres→migrate→worker→web`.
- `migrations/versions/0021_web_sessions.py` создаёт только `web_sessions` от
  `0020`. `tests/integration/test_web_api.py` проверяет сохранение schema/data.
- `src/community_bot/transport/static/index.html` и `app.js`: index может быть
  опубликован на `/mini-app`; assets и API используют абсолютные same-origin
  `/mini-assets/` и `/api/v1/`.
- Go-live blocker: `index.html` не загружает official Telegram bridge;
  `platform.js` лишь optional читает `globalThis.Telegram?.WebApp`; `app.js`
  bootstrap сразу GET `/me` + `/tasks` и никогда не POSTит `initData` в уже
  реализованный `/api/v1/auth/telegram`. Browser tests обходят gap seeded
  cookie/API. Поэтому release 71 не user-testable и не deploy candidate.
- Фактический current slice из CB-54/55/56 reports: catalog/task detail/accept,
  active assignments list/detail, read-only moderation queue, internal readiness.

## Проверенный host context

Контекст передан владельцем как read-only verified facts; в этой planning-фазе
server не опрашивался и не изменялся.

- Ubuntu 24.04 arm64; Docker 29.2.1; Compose 5.0.2.
- `/opt/community-bot` root-owned; environment mode `0600`; daily backup current.
- Current old bot/worker/PostgreSQL healthy, live DB head `0020`.
- Current Compose identities: project `community-bot`, network
  `community-bot_internal`, volume `community-bot_postgres-data`.
- Existing nginx serves HTTPS `allo.godmodetools.com` and landing page `/` from
  existing `/opt/app`; currently only on `app_app_network`.
- Artifact project identity differs, поэтому direct initial activation cannot
  see old PostgreSQL and must fail rather than create/accept empty data.

## Ограничения

- На момент подготовки пакета разрешён был только planning до owner decision;
  server/GitHub mutations были запрещены.
- Ponytail full: reuse ADR-0018, release contract, existing backup/restore,
  Docker Compose/nginx; no new dependency/script/framework/daemon.
- No server IP, credentials, secret paths/content or environment values in
  repository/Jira/evidence.
- Initial dump path/content не публикуются; file root-only `0600`, atomic и
  retained только по действующей backup policy до подтверждённого cleanup.
- Existing landing `/` and unrelated `/opt/app` services are protected scope.
- Telegram chats/media/messages are outside permission; HTTP/browser smoke only.

## Решение владельца

Владелец 2026-08-18 ответом «да разрешаю» принял:

1. Proposed ADR-0019 и постоянный process;
2. data cutover через new project/new volume с old stopped snapshot;
3. temporary mutation freeze;
4. migration `0020→0021`;
5. path-scoped HTTPS edge `/mini-app`, `/mini-assets/`, `/api/v1/` при сохранении
   landing `/`.
6. conditional resume нового worker и outbound Telegram processing только после
   green smoke и zero-backlog recheck.

Live Telegram interaction, чтение chats и отправка сообщений этим решением не
разрешены.
