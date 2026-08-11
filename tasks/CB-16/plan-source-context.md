# CB-16 — пакет источников плана

## Снимок задачи

- Jira: `CB-16` — «Подготовить сквозные проверки и запуск пилота».
- Родитель: `CB-2` — «Реализовать и подготовить к пилоту Community Bot MVP».
- Статус на 11 августа 2026 года: `В работе`.
- Ветка: `task/CB-16`.
- База: `origin/main`, commit `8b0be36812a65d790fb148b7d895461398424450`.
- Блокирующие связи: `CB-8` и `CB-15`; обе задачи имеют статус `Готово`.

## Критерии Jira

1. Регистрация, полный обмен, отмена, спор и карма проходят сквозную проверку.
2. Критические гонки и повторная доставка покрыты автоматическими тестами.
3. Миграции проходят на пустой и последней поддерживаемой схеме.
4. Восстановленная база сохраняет инварианты журнала экономики.
5. Открытых критических дефектов нет.
6. Метрики успеха и условия остановки доступны владельцу.
7. Проверен runbook запуска, мониторинга, отката и завершения пилота.

## Канонические процессные источники

- `AGENTS.md`.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`.
- `docs/AGENT_WORKFLOW.md`.
- `docs/JIRA_WORKFLOW.md`.
- `agents/README.md`.
- `agents/plan-reviewer/instruction.md`.
- `docs/adr/0004-risk-tiered-development-workflow.md`.
- `docs/adr/0007-review-escalation-after-two-failures.md`.

Из этих источников следует уровень процесса 3: это интеграционная, насыщенная
источниками общая регрессия. Полный план проверяется один раз после готовности
всего пакета. Полная регрессия выполняется одним финальным проходом после
слияния исправлений. Воспроизводимые дефекты, впервые найденные здесь, получают
отдельные Jira-баги и ветки.

## Продуктовые и технические источники

- Jira `CB-16`, её комментарии, связи и критерии; Jira `CB-2`.
- `docs/mvp/README.md`.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`.
- `docs/mvp/02_DOMAIN_RULES.md`.
- `docs/mvp/03_USER_FLOWS.md`.
- `docs/mvp/04_TASK_CATALOG.md`.
- `docs/mvp/05_BOT_INTERFACE.md`.
- `docs/mvp/06_DATA_MODEL.md`.
- `docs/mvp/07_SECURITY_AND_PRIVACY.md`.
- `docs/mvp/08_MODERATION_AND_ABUSE.md`.
- `docs/mvp/09_IMPLEMENTATION_PLAN.md`.
- `docs/mvp/10_TEST_PLAN.md`.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`.
- `docs/mvp/TECH_STACK.md` и `docs/mvp/HANDOFF.md`.
- `docs/adr/0005-mvp-technology-stack.md`.
- `docs/adr/0006-telegram-update-transaction-boundary.md`.
- `docs/adr/0008-pilot-runtime-and-operations.md` в части, не заменённой ADR-0009.
- `docs/adr/0009-self-hosted-pilot-runtime.md`.
- `docs/operations/PILOT_RUNBOOK.md`.

## Фактическая реализация на базе плана

- Миграции `0001`–`0010` и seed каталога
  `migrations/data/task_catalog_v1.json`.
- Доменные, прикладные, Telegram- и PostgreSQL-адаптеры в
  `src/community_bot/`.
- Автоматические unit, architecture, integration и smoke-проверки в `tests/`.
- `compose.yaml`, `compose.production.yaml`, `Dockerfile`.
- `ops/deploy_self_hosted.sh`, `ops/backup_postgres.sh`,
  `ops/restore_drill.sh` и systemd timer.
- `.github/workflows/ci.yml` и `.github/workflows/release.yml`.
- Развёрнутый self-hosted runtime из CB-15 служит целью операционного smoke, но
  прежние доказательства CB-15 не заменяют свежую проверку CB-16.

## Принятые ограничения

- Реальные приватные чаты не используются как данные или доказательства.
- Тестовые Telegram updates синтетические и не вызывают реальную отправку.
- Реальная Telegram-отправка возможна только после отдельного разрешения
  владельца; её отсутствие не подменяется утверждением об E2E.
- Тестовые участники и пилотные данные разделены; тестовый seed не загружается в
  production автоматически.
- External backup, R2, application object storage и webhook не входят в MVP.
- Полная потеря единственного сервера — принятый остаточный риск ADR-0009.
- Новая архитектурная форма не вводится: read-only отчёт метрик, тестовые
  фикстуры и дополнение существующего runbook не требуют нового ADR.

## Проверяемые исходные разрывы

- В текущем наборе есть сильные проверки отдельных модулей, но нет единого
  автоматизированного сценария A–D на одном согласованном наборе данных.
- В репозитории нет отдельного обезличенного seed тестовых участников и
  версионированного агрегированного отчёта метрик пилота.
- PRD называет метрики, но точные формулы, maturity, denominator и защита малых
  cells должны быть частью versioned report contract до реализации.
- Restore drill проверяет восстановление и базовые таблицы, но не завершает
  проверку равенства кэшей суммам immutable ledger.
- Главный supported-schema oracle миграции `0010` — backfill прежних
  `outbox_events`: published → `materialized`, unpublished → `pending`, плюс
  новые operational constraints/indexes.
- Канонический интерфейс и фактически зарегистрированные Telegram-команды
  требуют сверки как пользовательский контракт, а не только проверки функций.
- Путь первоначального администратора требует отдельной воспроизводимой
  проверки на чистой production-подобной базе.
