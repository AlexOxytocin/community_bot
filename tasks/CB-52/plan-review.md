# CB-52 — финальный owner-authorized recheck плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- Полностью проверены актуальные `tasks/CB-52/plan.md`,
  `plan-source-context.md`, `problem-escalation.md`, обе исторические попытки
  review и предыдущий terminal verdict.
- `git rev-parse HEAD` подтвердил baseline
  `4b05030edc90f8338cc050fcde41d5bc42d289c8`; runtime CB-52 на baseline
  отсутствует.
- Повторно сверены реальные owners:
  `RegistrationService.own_profile`, `ReputationService.profile/members/leaderboard`,
  `normalize_member_search_query`, `TaskService.list_available`,
  `infrastructure.db.registration.get_own_profile` и
  `infrastructure.db.tasks.list_available_tasks`.
- Проверены Telegram proof, session DDL/token/cookie/origin/cache contracts,
  DTO allowlists, authorization, ownership, file/LOC/dependency ceilings,
  tests, stop/rollback и CB-53 gate. Runtime, Jira, Telegram и Git/remote не
  изменялись.

## Замечания по области (`scope_findings`)

Обязательных замечаний нет. План сохраняет фиксированный Pareto scope:

- ровно одна additive table `web_sessions` и одна revision `0021`;
- ровно семь business routes плюс generated `GET /openapi.json`;
- auth/session/logout и пять существующих read projections без domain
  mutations и HTTP operation receipts;
- bounded members/leaderboard lists и существующий task UUID keyset;
- без cursor framework/version registry, Uvicorn, CORS middleware/matrix,
  frontend, deployment, public ingress и live acceptance.

Новый ADR не требуется: Mini App-only, FastAPI, internal actor, PostgreSQL
session и stdlib Telegram verification уже покрыты ADR-0014/0016/0017.

## Замечания по дизайну (`design_findings`)

Обязательных замечаний нет.

- Raw `initData` проверяется server-side через strict parse, canonical
  bot-token HMAC, `compare_digest`, freshness и only-after-HMAC JSON parsing;
  `initDataUnsafe` и client identity claims не являются authority.
- Session token contract точен: `secrets.token_bytes(32)`, 256-bit entropy,
  canonical 43-character unpadded base64url и
  `hashlib.sha256(raw_token_bytes).digest()`. PostgreSQL хранит только digest;
  duplicate digest/DB failure fail-closed без cookie и partial row.
- `ActorContext` содержит только internal `member_id`, provider и
  `authenticated_at`; status/role/permissions/ownership перечитываются
  защищёнными application owners.
- Exact member query contract совпадает с baseline owner: omitted, empty и
  whitespace-only raw input дают unfiltered list; непустые `"@"`, `"@ "` и
  `"@@"` дают stable `422 invalid_member_query`; полный pipeline использует
  removal всех leading `@`, whitespace collapse, `casefold`, затем bounds
  `3..80` на normalized result.
- Malformed task cursor даёт transport `422`; valid missing/hidden/stale UUID
  сохраняет owner behavior и начинает первую видимую страницу без раскрытия
  существования записи.

## Стратегия и доказательства проверки (`verification_findings`)

Все ранее обязательные findings закрыты:

1. **Actor migration/ownership:** включены фактический
   `infrastructure/db/registration.py`, четыре существующих integration
   call-site файла, два web test files и architecture test. Gates согласованы:
   не более `10` production Python/Alembic и `7` test files; compatibility
   overload/method запрещён.
2. **Member normalization:** исправленный план и матрица требуют exact
   `@ → 422`. Контрольный вызов baseline helper подтвердил:
   `None`, `""`, whitespace → `None`; `"@"`, `"@ "`, `"@@"`, `"ab"` →
   `ValueError`; `"@@name"` → `"name"`; `"abc"` → `"abc"`.
3. **Session token:** deterministic stdlib probe подтвердил 43-character wire
   value и 32-byte SHA-256 digest; тестовая матрица содержит CSPRNG mapping,
   digest-only storage и duplicate/DB failure oracle.
4. **Logout replay:** предусмотрены sequential live/revoked/expired/absent
   cases и concurrent same-cookie PostgreSQL case: одинаковые `204`, один
   условный revoke, subsequent `401`, exact clear-cookie и `no-store`.
5. **Scope/baseline:** статическая проверка подтвердила `7` routes, `43`
   baseline tables, `20` baseline revisions, `10` runtime dependencies и
   отсутствие FastAPI/Uvicorn на baseline. План добавляет только заявленные
   FastAPI/httpx и `web_sessions`.

Матрица также закрывает proof tampering/freshness, session expiry/restart,
current authority, DTO privacy, exact DDL/migration preservation,
origin/config/cache, route/import boundary, targeted branch coverage, полный
CI suite и secret/log scan.

## Обязательные исправления (`required_actions`)

Нет.

## Остаточные риски (`residual_risks`)

- Это одобрение плана, а не реализации: exact tests, simplicity gates,
  `implementation-report.md` и независимый `final-review.md` остаются
  обязательными до commit/push/PR/merge.
- UX 15-minute TTL и bounded lists проверяет CB-53. Public ingress, edge rate
  limiting, executable server/deploy и live Mini App acceptance остаются
  CB-56/CB-57.
- CB-53 разблокируется только после реализации CB-52, успешных targeted/full
  gates и merge ветки CB-52 в `main`; первый domain mutation остаётся вне
  текущего scope и требует собственного operation identity/concurrency
  acceptance.
