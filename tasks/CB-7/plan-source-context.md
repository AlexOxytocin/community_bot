# CB-7 — контекст и источники плана

`community_bot.plan_source_context.v1`

## Jira

- Задача: `CB-7` — «Реализовать журнал кредитов, опыт, уровни и сверку
  экономики» (`10039`).
- Родитель: эпик `CB-2` — «Реализовать и подготовить к пилоту Community Bot
  MVP», статус `В работе`.
- Статус и приоритет на начало планирования: `К выполнению`, `Medium`.
- Вложения и labels отсутствуют.
- Комментарии содержат только исходные записи зависимостей: CB-4 и CB-6
  блокируют CB-7.
- Входящие блокеры: `CB-4` и `CB-6`, оба имеют статус `Готово`; фактических
  открытых блокеров нет.
- Исходящие связи: CB-7 блокирует `CB-8`, `CB-10`, `CB-11`; все три пока
  `К выполнению`.
- Перед планированием Jira API вернул доступные переходы `К выполнению`,
  `В работе`, `На проверке`, `Готово`. Отдельного перехода, соответствующего
  «Планирование», нет, поэтому статус не изменён.

### Описание Jira

Контекст: кредиты и опыт — транзакционное ядро продукта, прямое изменение
баланса запрещено. Требуется immutable `account_transactions`, идемпотентное
начисление/резервирование/возврат/коррекция, обновление кэшей в той же
транзакции, уровни по утверждённым порогам, сверка и история операций.

Технические требования: PostgreSQL constraints и row locks, property-based
tests; коррекция выполняется обратной записью, а не изменением старой.

### Критерии приёмки Jira

1. Сумма журнала всегда равна кэшу после каждой поддерживаемой операции.
2. Повтор idempotency key не создаёт двойной эффект.
3. Starting grant и refund не увеличивают опыт.
4. Трата кредитов не уменьшает опыт.
5. Конкурентные резервы не приводят обычный баланс ниже нуля.
6. Reconciliation обнаруживает искусственно созданное расхождение.
7. Unit, property и PostgreSQL integration tests проходят.

## Документация и ADR

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: Jira-first, одна задача — одна
  ветка, детерминированное ядро, идемпотентность, запрет секретов и прямых
  правок `main`.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `agents/workflow.yaml`:
  уровень риска, статусы, обязательные артефакты и независимые ревью.
- `docs/adr/0004-risk-tiered-development-workflow.md`: CB-7 классифицирована как
  Level 3 из-за денежноподобного журнала, миграции и конкурентности.
- `docs/adr/0005-mvp-technology-stack.md`: Python 3.13, uv, modular monolith,
  PostgreSQL 18, SQLAlchemy 2 async, Alembic, Pydantic, pytest, Hypothesis,
  Testcontainers; одна session на прикладную транзакцию.
- `docs/adr/0006-telegram-update-transaction-boundary.md`: внешний Bot API не
  входит в транзакцию. CB-7 не отправляет Telegram-сообщения и не расширяет эту
  границу.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`: кредиты/опыт/уровни, история операций,
  административный аудит и восстановимость.
- `docs/mvp/02_DOMAIN_RULES.md`: формулы баланса/опыта, закрытый список операций,
  starting grant `5`, знаки дельт, no-negative penalty, пилотная шкала и
  version-aware `LevelResolver`.
- `docs/mvp/06_DATA_MODEL.md`: концептуальные таблицы
  `account_transactions`, `product_config_versions`, activations, singleton
  pointer и levels; append-only и reconciliation.
- `docs/mvp/07_SECURITY_AND_PRIVACY.md`: обычный участник не читает чужую
  историю; права всегда перепроверяются на сервере.
- `docs/mvp/09_IMPLEMENTATION_PLAN.md`: этап экономики после member foundation,
  acceptance требует ledger source of truth и отсутствие прямого balance edit.
- `docs/mvp/10_TEST_PLAN.md`: ledger/cache matrix, idempotency, concurrent spend,
  все границы уровней, stale cache, activation/backfill и no mixed scale.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`: D-001–D-003, D-008, D-009,
  D-011, D-012 и D-016 приняты 2026-08-10; единая product config включает
  levels и interaction policy `threshold=3/window=7`. Остальные открытые
  вопросы не разрешаются в CB-7.
- `tasks/CB-4/plan.md` и `tasks/CB-4/test-plan.md`: одобренный точный контракт
  ingest/activation identities, no-op, rollback, startup candidate, backfill и
  stale-cache поведения.
- `tasks/CB-6/final-review.md`: member/audit/UoW/PostgreSQL foundation
  независимо одобрена; полный regression прошёл.

## Факты о репозитории

- База ветки: merge commit `10c0fbb2eaf0e60471a1578acddd8cb9eb246f95`,
  одновременно `main` и `origin/main` на момент создания `task/CB-7`.
- Рабочая ветка: `task/CB-7`, создана до правок из чистого дерева.
- `MemberModel` содержит `level_number`, `credit_balance_cached`,
  `experience_total_cached`, но не содержит ledger/config cache version.
- `AuditEventModel` защищён PostgreSQL trigger от `UPDATE`/`DELETE`.
- `Database` владеет async engine и `async_sessionmaker`; каждый
  `SqlAlchemyUnitOfWork` создаёт отдельную session и transaction.
- Прикладной member foundation уже проверяет actor/target из сохранённых строк и
  блокирует участников в порядке UUID.
- Alembic head до задачи — `0002`; таблиц tasks, assignments, ledger, config и
  levels ещё нет.
- Integration fixture на каждый тест создаёт отдельную временную PostgreSQL
  database, применяет все миграции и удаляет database целиком. При отсутствии
  `DATABASE_URL` используется `postgres:18` Testcontainers без skip.
- `pyproject.toml` уже содержит Hypothesis, Pydantic, SQLAlchemy, asyncpg,
  Alembic, Ruff, ty и pytest-cov; новые dependencies не нужны.
- CI имеет jobs `Quality` и `PostgreSQL and Alembic`; предыдущий полный прогон
  main зелёный: run `31400993318`.
- Локальная среда: Docker Desktop, Compose и PostgreSQL 18.4 healthy; перед
  началом задачи baseline suite CB-4 составлял `152 passed`, `0 skipped`,
  `0 deselected`, coverage `93.72%`.
- На baseline этой ветки `uv run ty check` воспроизвёл defect `CB-17` в
  `migrations/env.py`: Alembic callback объявлен как `object`, а stub ожидает
  `Connection`. Владелец уточнил, что дефекты, найденные до финальной регрессии
  функционала, исправляются в текущей задаче; отдельной ветки CB-17 не будет.

## Ограничения

- Не использовать `CB-7` в runtime identifiers, test filenames, config keys,
  logs или metrics.
- Смысловые документы и Jira-комментарии — на русском; код, identifiers,
  docstrings и runtime messages — на английском.
- Баланс и опыт изменяются только append-only ledger; direct cache mutation
  допустима только как часть той же транзакции либо искусственная порча в
  integration test reconciliation.
- Удаление тестовых rows запрещено append-only trigger; очистка выполняется
  удалением отдельной временной database.
- Candidate config содержит единую строгую schema levels + interaction policy,
  не может стать runtime source of truth после активации и не содержит секретов.
- Пилотные level names/thresholds не hardcode в handlers, seed migration или
  resolver; они находятся в редактируемом candidate и immutable DB version.
- Один active pointer; ingest и activation — разные identities. Rollback — новая
  activation command, а не повтор старой identity.
- Все config mutations получают единый `product_config_mutation` advisory gate
  до actor row; bootstrap не вкладывает standalone orchestrators.
- Составной расчёт передаёт полный набор ledger entries одному публичному batch,
  который заранее сортирует все idempotency/member/source locks; последовательные
  одиночные apply внутри settlement запрещены.
- Устаревший `members.level_number` не принимает решения. Backfill — ускорение,
  а `LevelResolver` — correctness boundary.
- Колонки `task_id`, `assignment_id`, `interaction_alert_id` и их FK не
  создаются раньше задач, которым принадлежат эти aggregates; dangling UUID без
  referential integrity также запрещены.
- Реальные Telegram calls, токен и приватные данные не нужны и запрещены в
  тестах/артефактах.
- Обязательный PostgreSQL integration-контур должен завершиться ошибкой при
  недоступном Docker, а не `skip`.

## Открытые вопросы

Блокирующих вопросов нет. Принятые CB-4 правила достаточны для реализации
ledger и level configuration. В рамках CB-7 намеренно не решаются:

- Q-005 и Q-006 про доступ к карме;
- Q-011 про видимость профилей сверх уже принятой self/admin матрицы фундамента;
- production provisioning первого administrator и wiring runtime entrypoint:
  CB-7 поставляет и проверяет bootstrap coordinator с обязательной проверкой
  существующего active administrator, но не выдаёт роль и не запускает polling;
- конкретные FK и multi-entry atomic workflows заданий: будут добавлены
  CB-10/CB-11 поверх композиционного economy unit of work.
