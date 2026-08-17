# CB-52 — исходный контекст плана

## Снимок задачи и репозитория

- Jira: `CB-52`, «Добавить Telegram Mini App auth и полный тонкий API».
- Статус до начала этой фазы: `К выполнению`; после проверки доступных
  переходов задача переведена точным переходом `В работе` как ближайшим
  фактическим аналогом планирования.
- Jira updated snapshot: `2026-08-17T16:02:58.155-0300`; planning comment
  `10231` добавлен после перехода.
- Родитель: `CB-48`, статус `В работе`.
- Связи: `CB-51` больше не блокирует и имеет статус `Готово`; `CB-52`
  блокирует `CB-53` и `CB-56`, обе задачи имеют статус `К выполнению`.
- Исходный baseline после CB-51:
  `c61b0afd7cb5fa6bef315e235ba867c2959e242c`.
- Перед owner-authorized final recheck `task/CB-52` безопасно fast-forwarded до
  актуального `origin/main`:
  `4b05030edc90f8338cc050fcde41d5bc42d289c8`. Два промежуточных commit относятся
  только к GitHub owner migration и не меняют runtime scope CB-52.
- Перед fast-forward worktree blobs `.github/CODEOWNERS`, `Dockerfile` и
  `agents/config.yaml` побайтно совпали с `origin/main`. Только эти три пути
  временно сохранены в recoverable stash `cb52-pre-ff-owner-migration`, затем
  ветка fast-forwarded; stash не применяется и не удаляется в этой фазе.
- Ветка не имела уникальных commits; старые planning artifacts отсутствовали.
  Runtime-код CB-52 отсутствует.

## Исправляемые расхождения Jira

Фактический результат CB-51 отличается от старого предусловия CB-52:

- CB-51 выполнила Pareto-cleanup без compact schema/import migration;
- текущая схема осталась на 43 SQLAlchemy tables и 20 Alembic revisions;
- `ActorContext`, HTTP operation identity, FastAPI и web routes в baseline
  отсутствуют;
- формулировка «тонкие FastAPI routes для всех функций CB-53—CB-55» создаёт
  преждевременный API без UI consumer.

По решению оркестратора CB-52 не добавляет произвольную domain mutation ради
демонстрации API/idempotency. Foundation ограничивается auth/session/logout и
реальными read projections. Первая profile/task/karma mutation создаётся в
CB-53 или последующей UI-задаче вместе с consumer и собственной приёмкой.

## Фактическая форма backend после CB-51

- Production Python: 58 файлов, 19 615 строк.
- Tests: 46 Python-файлов, 13 848 строк.
- Direct runtime dependencies: 10; FastAPI/Uvicorn отсутствуют.
- `src/community_bot/transport/` не содержит web transport.
- `processed_telegram_updates` хранит только Telegram `update_id`, тип и
  outcome; это не HTTP operation contract.
- Общая PostgreSQL transaction boundary уже существует в
  `Database.unit_of_work()` / `SqlAlchemyUnitOfWork`.
- Application read services по-прежнему принимают `telegram_user_id`:
  `RegistrationService.own_profile`, `ReputationService.profile/members/
  leaderboard` и `TaskService.list_available`.
- Product mutations дополнительно принимают Telegram `update_id` и часто
  завязаны на conversation/FSM contracts. Оборачивать их HTTP-роутом без
  смены контракта нельзя.

## Реальные owners первого read slice

| Projection | Текущий owner | Доказательство поведения |
|---|---|---|
| Свой профиль, баланс, опыт и уровень | `RegistrationService.own_profile` | `tests/integration/test_registration.py` |
| Safe member card и member list | `ReputationService.profile`, `members` | `tests/integration/test_reputation.py` |
| Leaderboard | `ReputationService.leaderboard` | `tests/integration/test_reputation.py` |
| Доступные member/group/community tasks | `TaskService.list_available` | `tests/integration/test_task_creation.py`, `test_assignments.py` |

Проекции уже содержат серверные visibility/filtering rules. CB-52 меняет
только способ получения actor: session разрешается в internal `member_id`, а
role/status/permissions/ownership по-прежнему читаются из PostgreSQL внутри
защищённого use case.

## Источники и приоритет

1. Jira `CB-52`, `CB-51`, `CB-53`, `CB-56`, их статусы, связи и комментарии.
2. `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`.
3. Принятые ADR-0016 и ADR-0017; сохраняемые auth/security части ADR-0014.
4. `docs/release-2/README.md`, `docs/mvp/01_PRODUCT_REQUIREMENTS.md`,
   `docs/mvp/02_DOMAIN_RULES.md`, `docs/mvp/07_SECURITY_AND_PRIVACY.md` и
   `docs/mvp/TECH_STACK.md`.
5. Фактический source/test tree baseline commit.
6. Официальный Telegram Mini Apps contract:
   `https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app`.
   Он требует передавать raw `Telegram.WebApp.initData` на backend, не доверять
   `initDataUnsafe`, проверять bot-token HMAC и дополнительно ограничивать
   возраст по `auth_date`. Новый third-party Ed25519 path не нужен backend,
   который уже владеет bot token.

ADR-0017 уже выбирает Mini App-only, FastAPI, server session, PostgreSQL и
минимальную feature-oriented форму. CB-52 не вводит новое структурное решение,
поэтому новый ADR не нужен. Точный auth/session контракт фиксируется планом и
независимой security-проверкой в рамках уже принятого решения.

## Независимая разведка

Read-only explorer подтвердил:

- FastAPI, `ActorContext`, session storage и HTTP routes отсутствуют;
- существующие read projections достаточно переиспользовать;
- HTTP mutation нельзя строить поверх Telegram-FSM/update receipt;
- минимальный vertical slice — proof → session/ActorContext → реальные read
  projections;
- task/result, karma, moderation и admin mutations следует отложить до их UI
  задач.

## Открытые факты, не превращаемые в предположения

- CB-52 не публикует HTTPS runtime: deployment, edge rate limiting, DNS/TLS,
  observability и live Mini App acceptance принадлежат CB-56/CB-57.
- Shared/production DB не считается пустой. Новая migration только добавляет
  session table и не меняет существующие данные.
- Browser authentication, публичная регистрация и client SDK не входят в
  текущий контракт.
- Первый domain write и общий HTTP operation receipt откладываются до
  появления реального mutation consumer; `processed_telegram_updates` не
  переименовывается и не переиспользуется.
