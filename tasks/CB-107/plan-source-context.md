# CB-107 — исходный контекст плана

## Снимок задачи и Git

- Jira: `CB-107`, родитель `CB-48`, процесс Level 3.
- Канонический scope и acceptance переданы владельцем оркестрации; Jira и
  удалённые состояния в этом planning-срезе не изменялись.
- Worktree: `C:\Users\User\community_bot-worktrees\CB-107`.
- Ветка: `task/CB-107`.
- База: точный `origin/main`
  `3656bbe6ee18ef27641ca1ccace15f0f1c91aaf0`; ветка и путь до создания
  отсутствовали.
- Planning-срез меняет только `tasks/CB-107/plan.md`,
  `tasks/CB-107/plan-source-context.md`, `tasks/CB-107/test-plan.md`.

## Канонические визуальные источники

| Источник | SHA-256 | Нормативный вывод |
|---|---|---|
| `C:\Users\User\.codex\visualizations\2026\08\19\01a01b68-a553-76f3-a083-a21881ce997c\profile-v4-overview.png` | `AA28A3A8943DD5AEA4F52C42C64F81D2C4097FB2B6C4F608ED3BF38B33835B55` | Свой заполненный, чужой и частично заполненный профиль; один язык действий через карандаш; свои credits/experience/karma, публичные experience/karma; empty CTA только у owner |
| `...\profile-v4-fields.png` | `2D1BEF481BF0DB6FD1C0727505FFBFF38419A8B89FBFBA4F96061E98DE051E0E` | Отдельные редакторы name/city/bio/skills; Back отбрасывает; одна кнопка `Сохранить`; без `Отмена` и preview; лимиты `80/80/500`, skills `20` |
| `...\profile-v5-links.png` | `0CB51AA87C616FBC1B3DB6DE7492BCD1C4EC7153C501EF72BB13E5D233AAADC0` | Links list/new/edit/delete-confirm; max five; compact pencil/trash; большие destructive actions и confirm — `Удалить`; public row открывает URL |

Хэши проверены локально перед планированием. Более старые boards не являются
fallback и не используются для разрешения расхождений.

## Прочитанные правила и решения

- `AGENTS.md`, `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira-first,
  русский язык, branch/process, Ponytail full, сохранение пользовательских
  изменений и Mini App-only.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `agents/workflow.yaml`,
  `agents/developer/instruction.md` — Level-3 artifacts, независимый plan/final
  review, фактические переходы Jira и точная evidence mapping.
- `docs/AGENT_CONTEXT_AND_COST_POLICY.md`, `agents/README.md`,
  `agents/config.yaml` — ограниченный planning slice и compact handoff.
- `docs/mvp/README.md`, `01_PRODUCT_REQUIREMENTS.md` — owner profile, safe public
  profile, active visibility, credits/experience/level/karma.
- `docs/mvp/02_DOMAIN_RULES.md`, `11_DECISIONS_AND_OPEN_QUESTIONS.md` — D-001,
  D-005, D-011, D-020—D-022: агрегированная карма, privacy, level resolver,
  eligibility и safe active-member projection; reliability домен сохраняется.
- `docs/mvp/TECH_STACK.md`, ADR-0004/0005 — Level 3, Python/FastAPI,
  SQLAlchemy/Alembic/PostgreSQL, native frontend.
- ADR-0014 — signed initData, internal actor, server authorization, operation
  fingerprint/receipt, untrusted navigation hints и platform isolation.
- ADR-0016 — Mini App единственный UI; старый chat/fallback не сохраняется.
- ADR-0017 — native HTML/CSS/ES modules, один монолит/DB, удаление дублирующих
  слоёв без ослабления privacy/idempotency/reliability.
- `docs/release-2/README.md`, заменённые ADR-0011/0012/0013 — deployment нельзя
  заявлять без точного release/schema/restore/live evidence; старую R1 topology
  не восстанавливать.
- `ponytail` full — сначала delete/reuse/native, без dependency или speculative
  abstraction; validation/security/accessibility не сокращать.

## Проверенный runtime trace

### Backend и auth

- `src/community_bot/infrastructure/db/models.py:83-130`: `members` содержит
  immutable `telegram_user_id`, mutable `telegram_username`, profile fields и
  JSONB skills; link owner/storage отсутствует.
- `migrations/versions/0021_web_sessions.py`: текущий head `0021`, parent
  `0020`; web sessions являются последней migration.
- `src/community_bot/transport/web.py:479-532`: cookie разрешается в internal
  member ID; `/api/v1/auth/telegram` валидирует proof, создаёт session, но не
  синхронизирует username.
- `web.py:1311-1364`: signed `user` JSON проверяется после HMAC, но validator
  возвращает только numeric ID.
- `src/community_bot/application/registration.py:449-501` и
  `src/community_bot/infrastructure/db/registration.py:179-191`: existing
  registration flow уже обновляет и очищает mutable username без смены identity.
- `src/community_bot/infrastructure/db/database.py:170-193`: session creation
  находит member и пишет session в одной transaction; это минимальное место для
  повторного использования username sync.

### Profile mutation и projection

- `src/community_bot/domain/registration.py:94-104,167-191`: allowlisted
  `ProfileField`, name/city/bio/skills normalization; skills уже ограничены 20
  элементами по 50 символов.
- `src/community_bot/application/registration.py:820-865`: web profile update
  использует actor ownership, identity gate, member lock, normalization, audit,
  receipt и один commit. Receipt проверяется до mutation.
- `src/community_bot/transport/web.py:124-170`: `MeDto` содержит statistics,
  но не username/links; `MemberDto` содержит safe username и reliability, но не
  links.
- `web.py:558-604`: `GET /me` и `PUT /me/profile`; mutation использует strict
  content type/body, deterministic fingerprint, namespaced numeric update ID,
  `422` validation и `409` stale/conflict boundary.
- `web.py:1612-1649`: public/own DTO mapping. Reliability и own statistics
  остаются без cleanup согласно финальной reliability-границе.
- `src/community_bot/application/reputation.py:102-145` и
  `src/community_bot/infrastructure/db/reputation.py:433-452`: `SafeProfile`
  содержит только public fields, aggregate karma и reliability projection;
  public visibility reauthorizes server-side.

### Frontend

- `src/community_bot/transport/static/app.js:61-117`: presentation route map и
  direct-location parsing; resource ID allowlist уже fail-closed.
- `app.js:856-991`: legacy universal profile list/editor, inline form,
  `Отмена`, task statistics и reliability presentation.
- `app.js:1022-1058`: participant row рисует karma и reliability.
- `app.js:1251-1269`: public member detail рисует safe fields и reliability.
- `app.js:1455-1552`: member/own profile loading; own profile сейчас читает
  `/me` и собственный `/members/:id`.
- `app.js:2748-2888`: bootstrap, deep-link, bottom nav, Back и popstate;
  legacy `profile-settings` branch ещё существует.
- `src/community_bot/transport/static/styles.css:234,271-295`: legacy profile
  dashboard/indicator/inline editor selectors; safe-area/focus/shared buttons
  уже существуют и переиспользуются.
- `src/community_bot/transport/static/platform.js`: сейчас только theme/ready/
  expand; external-link capability отсутствует.
- `tests/browser/test_mini_app.py:1307+`, `1630+`, `1862+`: текущие connected
  profile/participant/karma journeys, retry/stale/focus/privacy patterns и оба
  целевых размера экрана можно переиспользовать вместо нового harness.

## Deletion/reliability trace

В active frontend надёжность встречается только в `app.js` helpers
`reliabilityText`/`reliabilityPercent`, own indicators, participant rows и member
detail. Leaderboard row UI показывает rank/name/XP и не требует изменения.

Backend reliability имеет многочисленных non-profile consumers: append-only
writers в assignments/cancellations/moderation, effective folding,
`PersonalStatistics`, safe DTO и leaderboard tie-break ordering. Поэтому
удаление `own_statistics`, reliability DTO, writers, tests или DB объектов не
является профильной чисткой и прямо запрещено финальной областью CB-107.

## Security и privacy assumptions

1. Только подписанный `user.username` по `^[A-Za-z0-9_]{5,32}$` либо его
   подписанное отсутствие являются authority; malformed auth отклоняется.
2. Public profile links намеренно видимы любому actor, которому server уже
   разрешил safe active profile. Hidden/non-active policy не меняется.
3. Link label и URL — untrusted text: только `textContent`, никакого HTML.
4. Только absolute HTTPS URL без credentials может храниться и открываться;
   URL не используется как auth/navigation authority и не получает referrer/
   opener.
5. Link mutation только owner-side, под текущим status/ownership lock и receipt.
6. Karma comment/authors, Telegram ID, cookies, initData, reliability history и
   административные данные не входят в новые DTO/evidence.
7. `can_rate_karma` использует один snapshot и exact `begin_vote`: non-self,
   оба active, historical eligibility; endpoint reauthorizes, список без query.
8. Только foreign valid username ведёт на `https://t.me/<username>`; own plain.

## Почему новый ADR не нужен

CB-107 не вводит новую системную форму: одна JSONB-колонка в существующей
`members`, расширение уже принятой profile mutation, safe DTO и native
Mini App routes соответствуют ADR-0014/0016/0017. Нет нового сервиса,
repository, dependency, transport, auth provider, cross-cutting rule или
release topology. Если реализация потребует такой элемент, это stop condition и
новое решение владельца, а не молчаливое расширение плана.

## Открытые вопросы

Открытых продуктовых или технических вопросов, блокирующих реализацию, нет.
Проверка exact replay server-generated UUID является implementation gate с
заранее определённым stop action, а не вопросом требований.
