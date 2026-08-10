# CB-6 — отчёт о реализации

## Статус

Обязательные замечания первого независимого финального ревью исправлены, полный локальный барьер повторён. Задача готова к новому независимому финальному ревью уровня 3. Публикация ветки, PR, CI и переход Jira в «На проверке» выполняются только после нового `Status: approved`.

## Что изменено

- Добавлена чистая доменная модель ролей `member/moderator/administrator`, семи статусов участника, маршрутов `/start`, чтения своего/чужого участника и точной матрицы административных переходов.
- Добавлен application-сервис, который первым DB-действием получает transaction-scoped advisory lock по 64-битному PostgreSQL-хешу полного `BIGINT update_id`, читает точный receipt, блокирует actor/target по UUID, повторно проверяет права, атомарно сохраняет member/audit/complete receipt и завершает транзакцию до ответа Telegram.
- Добавлен persisted read/ownership сценарий: member и moderator читают только себя, неактивный actor получает отказ, активный administrator читает любого участника, включая другого administrator.
- Добавлены управляемые async engine/session factory и SQLAlchemy-модели `members`, `audit_events`, `processed_telegram_updates`.
- Добавлена Alembic-миграция `0002` с CHECK/UNIQUE/NOT NULL/FK, индексом участника и PostgreSQL trigger, запрещающим `UPDATE/DELETE` audit events.
- Реализован минимальный aiogram-маршрут `/start` и кнопки `Обновить меню`; update без пригодного `from_user` отбрасывается до транзакции.
- Long polling не подключался: обе точки запуска сохраняют безопасный stub, а transport проверяется synthetic aiogram updates и fake Bot API session.
- Integration fixture использует заданный `DATABASE_URL` либо автоматически поднимает `postgres:18` через Testcontainers. Каждый тест создаёт отдельную временную database, применяет миграции и удаляет database целиком.
- DB-job GitHub Actions запускает полный pytest с PostgreSQL 18, а не узкий smoke-набор.
- Quality job запускает быстрый non-integration набор с `--no-cov`; обязательный coverage threshold проверяется полным PostgreSQL job, где исполняется инфраструктурный код.
- README, архитектурная документация и каноническая модель данных MVP приведены к реализованному состоянию и принятому ADR-0006.

## Отклонения от плана

Итоговая реализация соответствует одобренной области. Первое финальное ревью обнаружило и остановило лишнее подключение long polling; оно полностью удалено вместе с опубликованным runtime-контрактом. То же ревью выявило границу `int4` advisory lock, зависимость duplicate-команды от повторного payload, отсутствие persisted read-flow, fault hook до SQL flush и пропуск `docs/mvp/06_DATA_MODEL.md`. Все пять технических пробелов и документация исправлены до повторного ревью. Реальные Telegram-запросы и production provisioning администратора не выполнялись.

## Критерии приёмки и доказательства

| Критерий | Статус | Реализация | Проверка и доказательство |
|---|---|---|---|
| Новый и существующий Telegram user маршрутизируются детерминированно | Закрыт | `route_start`, persistent receipt, точные русские presentation и router `/start`/`Обновить меню` | Unit/property-based матрица и `test_unknown_and_all_member_status_routes_use_persistent_receipts`; synthetic aiogram update |
| Повтор одного update не создаёт второе доменное действие | Закрыт | `hashtextextended(namespace, BIGINT) → pg_advisory_xact_lock(bigint)` + exact PK receipt + complete insert в одной транзакции | Конкурентный двойной admin update: один member effect, audit и receipt; границы `2^31` и `2^63-1`; подмена повторного actor/target возвращает сохранённый outcome без чтения payload |
| Запрещённая роль или статус получает отказ после серверной проверки | Закрыт | Ordered `FOR UPDATE`, проверка actor/target после lock, закрытая матрица переходов и persisted read-flow | Полная unit-матрица, persistent actor role/status и read/ownership matrix; self/admin target и неизвестные значения отклоняются |
| Значимое административное действие оставляет audit event | Закрыт | Явный SQL flush member, append-only application operation и DB trigger | Fault после фактического `UPDATE members` откатывает member/audit/receipt; проверены actor/reason/before/after, конкурентная цепочка и запрет прямых `UPDATE/DELETE` |
| Перезапуск процесса не теряет сохранённое состояние | Закрыт | PostgreSQL как единственный источник member/audit/receipt | Dispose первого Database, создание второго, повтор команды: два member, один audit, один receipt |
| Unit, integration и migration tests проходят | Закрыт | Unit, property-based, architecture, smoke, PostgreSQL integration, migration cycle | `152 passed`, 0 skipped, 0 deselected, coverage 93.72%; полный Testcontainers integration-файл `15 passed` |

## Проверки

| Проверка | Команда или сценарий | Результат |
|---|---|---|
| Форматирование | `uv run ruff format --check .` | Успешно, 108 файлов отформатированы |
| Линтер | `uv run ruff check .` | Успешно |
| Типы | `uv run ty check src tests` | Успешно |
| Полная локальная регрессия | `DATABASE_URL=postgresql+asyncpg://... uv run pytest` | `152 passed`, без skip/deselect, coverage `93.72%` |
| Быстрый CI-срез без PostgreSQL | `uv run pytest -m "not integration" --no-cov` | `136 passed`, integration-тесты исключены намеренно, coverage оценивает полный DB-job |
| Автономный integration server | без `DATABASE_URL`: `uv run pytest tests/integration/test_member_foundation.py --no-cov -q` | Testcontainers `postgres:18`, `15 passed`, без skip |
| Compose | `docker compose config --quiet` и `docker compose exec ... SHOW server_version` | Конфигурация валидна, PostgreSQL `18.4` |
| Миграции | `upgrade head → downgrade 0001 → upgrade head` | Успешно, итоговая ревизия `0002` |
| Сборка | `uv build` | Созданы sdist и wheel |
| Точки запуска | `uv run community-bot --check`; `uv run community-worker --check` | Обе проверки успешны, внешних операций нет |
| Пробелы и окончания строк | `git diff --check` | Успешно |

## Документация

- ADR-0006 принят владельцем и включён в индекс ADR.
- Обновлены `README.md`, `docs/ARCHITECTURE.md`, `docs/mvp/06_DATA_MODEL.md` и `tasks/CB-6/test-plan.md`.
- Все смысловые артефакты и пользовательские Telegram-строки написаны по-русски; код, идентификаторы, логи и runtime errors — по-английски.

## Ограничения и остаточные риски

- Exactly-once относится только к зафиксированному доменному эффекту PostgreSQL. Без outbox безопасный ответ Bot API может повториться или потеряться после commit, как явно принято в ADR-0006.
- Таблица receipts пока не имеет retention policy; это осознанный долг до пилота.
- Первичное provisioning роли `administrator`, приглашения и полный профиль находятся вне области CB-6.
- Реальные Telegram-сообщения не отправлялись; transport проверен synthetic updates и fake Bot API session.

## Внешние изменения

- Jira CB-6 переведена через Atlassian API в «В работе».
- В Jira один раз добавлен комментарий о принятии ADR-0006, одобренном плане, ветке и локальном PostgreSQL 18.4.
- Jira-задачи, связи и Telegram не изменялись после начала реализации.

## Следующий шаг

Независимый final-review читает Jira и исходные артефакты, повторяет обязательные проверки и создаёт только `tasks/CB-6/final-review.md`. При `Status: approved` реализация фиксируется коммитом, ветка публикуется, создаётся PR и задача переводится в «На проверке» с точными ссылками и доказательствами CI.
