# CB-49 — контекст и источники плана

## Jira

- **Задача:** CB-49 — зафиксировать capability-контракт и ADR multi-interface
  архитектуры Release 2.
- **Родительский эпик:** CB-48 — Release 2: единая платформа Community Bot с
  Telegram Mini App.
- **Связанная пилотная история:** CB-24. Её ограничение обновлено решением
  владельца от 2026-08-16 и связано с CB-48 через `Relates`.
- **Декомпозиция:** CB-50 — Release 1; CB-51 — `ActorContext` и идемпотентность;
  CB-52 — API/auth; CB-53 — frontend shell/read-only; CB-54 — транзакционные
  сценарии; CB-55 — администрирование; CB-56 — HTTPS/rollout; CB-57 — parity и
  выпуск; CB-58 — дизайн-система.
- **Комментарии:** отдельного уточнения по CB-49 нет; прямое решение владельца в
  текущем разговоре — «фиксируем и заводи» с обязательной готовностью к
  возможному полноценному браузерному интерфейсу.
- **Связи и блокирующие зависимости:** runtime-реализация не начинается этой
  задачей. CB-50 и CB-58 являются отдельными потоками; открытых blockers для
  фиксации capability и ADR нет.
- **Критерии приёмки:** capability, ADR, `ActorContext`, внутренняя сессия,
  сменяемые auth adapters, `PlatformBridge`, цена browser UI, release strategy,
  русская документация и независимая проверка.

## Документация и ADR

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — приоритет источников, Jira-first,
  ветки задач, ADR и release gates.
- `docs/AGENT_WORKFLOW.md` и `docs/JIRA_WORKFLOW.md` — процесс уровня 3,
  независимые plan/final review и внешняя передача.
- `docs/mvp/README.md` — карта канонической документации MVP.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md` — web/mobile app не входит в MVP.
- `docs/mvp/02_DOMAIN_RULES.md` — сохраняемые доменные инварианты.
- `docs/mvp/03_USER_FLOWS.md` и `docs/mvp/05_BOT_INTERFACE.md` — источник
  parity-матрицы Release 1.
- `docs/mvp/07_SECURITY_AND_PRIVACY.md` — права и приватность.
- `docs/mvp/TECH_STACK.md` — модульный монолит и отложенные FastAPI/public API.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md` — решения D-001 — D-032 и
  правило добавления новых решений.
- `docs/adr/0004-risk-tiered-development-workflow.md` — уровень 3.
- `docs/adr/0005-mvp-technology-stack.md` — Python/PostgreSQL монолит.
- `docs/adr/0006-telegram-update-transaction-boundary.md` — действующая
  идемпотентность Telegram updates.
- `docs/adr/0009-self-hosted-pilot-runtime.md` — отсутствие public ingress в R1.
- `docs/adr/0011-protected-single-ci-release.md` — release только из
  проверенного `main` и immutable digest.
- `docs/operations/PILOT_RUNBOOK.md` — deploy, acceptance и rollback.
- Официальная документация Telegram Mini Apps:
  <https://core.telegram.org/bots/webapps>. Критичны серверная проверка
  `initData`, launch modes, theme и safe area.
- Визуальный референс владельца:
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>. Решения по
  палитре вынесены в CB-58 и не принимаются ADR-0014.

## Факты о репозитории

- На старте CB-49 `main` и `origin/main` указывают на `1f2bfd76`.
- Рабочее дерево было чистым, ветка `task/CB-49` создана от актуального
  `origin/main`.
- Git tags отсутствуют; `pyproject.toml` содержит version `0.1.0`.
- Код организован в `domain`, `application`, `infrastructure`,
  `transport/telegram`, `worker` и `bootstrap`.
- `tests/architecture/test_import_boundaries.py` запрещает Telegram и
  infrastructure dependencies в `domain`/`application`.
- Application-контракты всё ещё широко используют `telegram_user_id` и
  `update_id`; это предмет CB-51, а не документационной подмены в CB-49.
- Production Compose и release pipeline сейчас запускают PostgreSQL, migrate,
  worker и bot без публичного HTTP ingress.
- На момент планирования актуальный workflow текущего `main` ожидал production
  Environment approval; поэтому SHA не объявляется Release 1 автоматически.

## Ограничения

- Русский язык всей смысловой документации.
- Нельзя считать предлагаемые API/frontend уже реализованными.
- Домен, ledger, audit, outbox и server-side authorization остаются источником
  истины для всех интерфейсов.
- PostgreSQL остаётся единственным транзакционным хранилищем; Redis, Celery и
  микросервисы не добавляются этой задачей.
- Telegram `initDataUnsafe` не является доверенным входом.
- Будущий browser client не получает автоматическую публичную регистрацию.
- Любая будущая миграция должна быть expand-only и совместимой с частичным
  rollback Release 1.
- Дизайн-референс задаёт направление, но не отменяет Telegram themes,
  accessibility и mobile-first ограничения.

## Открытые вопросы

- production domain и TLS terminator — решение CB-56;
- точный механизм внутренней сессии, CSRF и revocation без Redis — решение
  CB-52 после security review;
- будущий browser auth provider — отдельное продуктовое решение, не blocker R2;
- окончательные light/dark semantic tokens и typography — CB-58;
- необходимость самостоятельной ветки `release/1.x` — только после реального
  запроса на независимые patch-релизы;
- webhook для бота не требуется для Mini App и остаётся отдельным вопросом.
