# CB-6 — план реализации фундамента участников, доступа и идемпотентности

`community_bot.developer.plan.v1`

## Цель

Создать минимальный транзакционный фундамент этапа 1: сохранённого участника с ролью и статусом, серверные проверки доступа и владения, защищённые от изменения audit events, PostgreSQL-дедупликацию доменных эффектов Telegram updates и безопасную маршрутизацию `/start` для нового и существующего пользователя.

## Уровень процесса

Уровень 3 по ADR-0004: задача одновременно интеграционная и чувствительная к безопасности, конкурентности и сохранности данных. Обязательны `plan-source-context.md`, `test-plan.md`, независимый `plan-review.md`, полный локальный PostgreSQL-прогон и независимый `final-review.md`. Сквозная транзакционная граница update receipt и внешнего Telegram-ответа зафиксирована в принятом владельцем ADR-0006.

## Область изменений

- конфигурация SQLAlchemy async engine и `async_sessionmaker` с отдельной сессией на прикладную операцию;
- доменные типы роли, статуса, разрешения, решения маршрутизации и ошибки отказа;
- SQLAlchemy-модели и миграция для `members`, `audit_events`, `processed_telegram_updates`;
- порты репозиториев и инфраструктурные адаптеры для чтения участника, аудита и атомарного receipt-протокола update;
- прикладные сервисы авторизации, проверки владения, выбора стартового маршрута и выполнения не более одного зафиксированного PostgreSQL-эффекта на `update_id`;
- минимальный aiogram router `/start` и главное меню без реальной регистрации и внешних отправок в тестах;
- unit, integration, migration, architecture и transport-тесты;
- обновление README, архитектуры и концептуальной модели данных фактическими контрактами.

## Вне области изменений

- создание участника по приглашению, анкета, модерация регистрации и FSM онбординга;
- стартовый грант, журнал кредитов, опыт, уровни и лидерборд;
- категории, шаблоны и жизненный цикл заданий;
- точные продуктовые разрешения для статуса `restricted`;
- карма, споры, санкции, outbox и production worker;
- real Telegram token, long-polling и отправка сообщений в пользовательский аккаунт;
- exactly-once доставка внешнего ответа Telegram и outbox критических уведомлений;
- выбор hosting, error reporting, backup policy и решения открытых продуктовых вопросов.

## Текущее состояние

- CB-3 завершена и слита; локальный и CI PostgreSQL-контур зелёный.
- Пакеты слоёв существуют, но модели и прикладные контракты пусты.
- `Settings` содержит URL БД, healthcheck создаёт engine напрямую, а общего жизненного цикла engine/sessionmaker нет.
- Миграция `0001` не создаёт таблиц.
- Точки запуска работают только в безопасном `--check` режиме.

## Предлагаемое решение

### 1. Домен и доступ

- Определить `MemberRole`: `member`, `moderator`, `administrator`.
- Определить `MemberStatus`: `pending`, `active`, `paused`, `restricted`, `suspended`, `left`, `banned`.
- Определить минимальные действия фундамента: открыть собственное состояние, прочитать member record, изменить статус и изменить роль.
- Разрешать обычные действия только `active`; `restricted` и остальные неактивные статусы получают явный отказ до появления утверждённых ограниченных разрешений.
- Роль не выводится из уровня. В CB-6 модератор не получает изменяющих member-команд: точные ограниченные модераторские права остаются следующим этапам.
- Проверку владения выполнять по сохранённому `member.id`, а не по входному payload. Администраторский обход владения разрешён для чтения любой target-записи; изменяющие команды имеют отдельные узкие переходы ниже.

| Действие | Допустимая роль actor | Статус actor | Target и владение | Администраторский обход |
|---|---|---|---|---|
| открыть своё стартовое состояние | любая сохранённая роль | только `active` для главного меню | только actor; новый и `pending` используют отдельные безопасные маршруты | нет |
| прочитать member record | `member`, `moderator`, `administrator` | только `active` | member/moderator — только собственная запись | administrator может читать любую чужую запись, включая другого administrator |
| изменить статус | только `administrator` | только `active` | target не равен actor; target role — `member` или `moderator`; разрешены только `active → paused` и `paused → active` | явная команда администратора |
| изменить роль | только `administrator` | только `active` | target не равен actor; target status — `active` или `paused`; разрешены только `member ↔ moderator` | явная команда администратора |

Self-target, target с текущей ролью `administrator`, назначение роли `administrator`, все остальные переходы статуса/роли и любая изменяющая команда moderator/member в CB-6 возвращают отказ. Первичное provision роли administrator остаётся контролируемой эксплуатационной операцией вне CB-6; сервис не создаёт необратимо «неуправляемого» администратора. Так план закрывает матрицу безопасности без молчаливого выбора будущей модели регистрации, санкций и управления администраторами.

### 2. Модель хранения

- `members`: UUID PK, уникальный `telegram_user_id BIGINT`, основные поля концептуальной модели, текстовые role/status с `CHECK`, timezone-aware UTC timestamps и безопасные значения кэшей.
- `audit_events`: UUID PK, nullable actor FK, action, entity type/id, JSONB before/after, reason, UTC timestamp. Прикладной API предоставляет только append, а PostgreSQL trigger отклоняет row-level `UPDATE` и `DELETE`.
- `processed_telegram_updates`: `update_id BIGINT PRIMARY KEY` в области единственного MVP-бота, тип update, nullable actor, обязательные `outcome_code`, `received_at` и `processed_at`. Полуготовая запись не вставляется; прямой incomplete insert отклоняют `NOT NULL` constraints.
- Использовать обычные текстовые значения с DB `CHECK`, а не PostgreSQL native enum: это сохраняет явный доменный enum и упрощает будущие обратимые миграции без смены утверждённой модели.
- Обновить `docs/mvp/06_DATA_MODEL.md` таблицей дедупликации и точными принятыми типами этапа 1.

### 3. Транзакции и дедупликация

- Создать единый объект БД, владеющий async engine и session factory; каждая операция получает новую сессию и явную транзакцию.
- Следовать принятому ADR-0006: первой DB-операцией получать transaction-scoped advisory lock по hash namespace `telegram_update` и точному `update_id`, затем читать receipt. Hash collision может только сериализовать независимые updates и не меняет проверку точного PK.
- Через receipt проходят все принятые transport updates, включая read-only `/start`: для него сохраняется только детерминированный outcome без member mutation. Update без `from_user` отбрасывается до receipt.
- Если готовый receipt уже существует, повтор читает сохранённый `outcome_code` и не повторяет доменное действие.
- Если receipt отсутствует, application выполняет действие/audit, вставляет полностью заполненный receipt в конце транзакции и commit фиксирует всё вместе.
- Если действие завершается ошибкой до commit, rollback удаляет все доменные изменения и освобождает advisory lock; receipt не существует, поэтому повтор может выполниться снова.
- Exactly-once не заявляется для Telegram: гарантируется только «не более одного зафиксированного PostgreSQL-эффекта».
- Bot API запрещён внутри транзакции. Transport отправляет ответ после commit по `outcome_code`; безопасный ответ может быть повторён или потерян. Критические сообщения получат outbox в последующей задаче.
- Для изменяющей member-команды после advisory lock и точного чтения receipt по неизменяемому `telegram_user_id` разрешается UUID actor без принятия решения о доступе. Actor и target блокируются одним `SELECT ... ORDER BY id FOR UPDATE`; только после блокировки заново проверяются роль, статус, self/admin-target и владение, выполняются действие/audit и вставляется полностью заполненный receipt.
- Все member-команды соблюдают порядок `advisory update lock → receipt read → member UUID ASC FOR UPDATE → изменение → audit → complete receipt insert → commit`. Два изменения одного target сериализуются; `before` каждого audit event берётся из уже заблокированной актуальной строки.
- Не держать SQLAlchemy session в aiogram state, глобальных singleton handlers или конкурентных задачах.

### 4. Маршрутизация Telegram

- При `/start` или точной кнопке `Обновить меню` извлечь только `telegram_user_id`, передать его прикладному сервису и получить одно из решений: `registration_required`, `registration_pending`, `main_menu`, `account_unavailable`.
- Отсутствующий участник направляется к будущей регистрации без создания записи; `pending` получает статус ожидания; `active` — минимальное главное меню; остальные статусы — безопасный отказ.
- Зафиксировать русский UI-контракт без неработающих функций: новый — `Для регистрации потребуется приглашение.` без клавиатуры; pending — `Заявка ожидает подтверждения.` без клавиатуры; active — `Главное меню` с единственной рабочей reply-кнопкой `Обновить меню`; остальные — `Аккаунт недоступен. Обратитесь к администратору.` без клавиатуры.
- Update без пригодного `from_user` игнорируется без транзакции, записи receipt и ответа.
- aiogram handler отвечает только за адаптацию входа/выхода. Все выборы маршрута, роли и статуса остаются в application/domain.
- Проверять router через синтетические aiogram updates и fake session; тест подтверждает, что fake Bot API вызывается только после возврата application service, когда транзакция уже закрыта.

### 5. Аудит

- Административный application service изменения роли/статуса не имеет Telegram callback в CB-6. Он вызывается типизированной командой, блокирует actor/target по протоколу выше, повторно авторизует actor, применяет изменение и добавляет audit event в одной транзакции.
- Audit event содержит actor, действие, entity, before/after и причину; отказ не изменяет участника и не создаёт ложное событие успеха.
- Fault injection после изменения target, но до append audit, должен откатывать target, receipt и audit. DB trigger отдельно доказывает невозможность обычного `UPDATE/DELETE` audit row.
- Это минимальный application-сценарий для доказательства критерия; admin transport/UI остаётся вне области.

## Ключевые решения и альтернативы

| Решение | Выбранный вариант | Отклонённая альтернатива и причина |
|---|---|---|
| Идентификатор участника | UUID внутри домена, Telegram user ID как уникальный внешний ключ | Telegram user ID как PK связывает домен с transport |
| Роли и статусы в БД | `TEXT/VARCHAR` + `CHECK` | Native enum усложняет обратимые изменения без пользы для MVP |
| Дедупликация | transaction-scoped advisory gate, затем чтение/вставка только полного receipt в одной транзакции с действием | in-memory set теряется после restart; nullable claim конфликтует с немедленными constraints; ранний отдельный commit теряет retry |
| Авторизация | чистая доменная policy + чтение актуального участника в application service | скрытие кнопок и доверие callback не являются защитой |
| Конкурентное изменение member | actor/target `FOR UPDATE` в порядке UUID и повторная проверка после lock | обычный read допускает stale authorization, lost update и неверный audit `before` |
| Неизменяемость аудита | append-only port + PostgreSQL trigger против `UPDATE/DELETE` | один прикладной интерфейс не защищает от другого ORM/SQL-кода |
| Integration harness | отдельная временная database на каждый integration test; сервер берётся из Compose URL либо автоматического `postgres:18` Testcontainers | DELETE-cleanup конфликтует с immutable audit trigger; skip при отсутствии БД запрещён |
| Telegram-тест | synthetic update + fake Bot session после commit | реальный токен и отправка не нужны для детерминированной проверки |
| Сквозное решение | принятый владельцем ADR-0006 | ADR-0005 не фиксирует конкретную границу update receipt и Bot API |

## Шаги реализации

1. Уточнить текущую схему settings/engine и добавить управляемый жизненный цикл БД без дублирования engine в healthcheck.
2. Добавить чистые доменные enums, решения маршрутизации, permission policy и типизированные ошибки.
3. Согласно принятому ADR-0006 добавить SQLAlchemy metadata/models и Alembic `0002` с ограничениями, индексами, audit trigger, UTC timestamps и симметричным downgrade.
4. Добавить application ports и SQLAlchemy repositories для участника, complete update receipt и append-only аудита.
5. Реализовать unit-of-work сервис по ADR-0006: advisory gate, чтение/вставка complete receipt, сохраняемый outcome, PostgreSQL-эффект и audit в одной транзакции; Telegram-ответ только после commit.
6. Реализовать полную матрицу авторизации, ordered locking actor/target и application-команду изменения роли/статуса с audit event.
7. Реализовать детерминированный start-route service и тонкий aiogram `/start` router с минимальным меню.
8. Подключить router и жизненный цикл БД к bootstrap без запуска long polling в `--check` и без требования токена в тестах.
9. Добавить unit, integration, migration, architecture и transport-тесты; использовать Compose URL или автоматический Testcontainers без `pytest.skip`.
10. Обновить README, `docs/ARCHITECTURE.md`, `docs/mvp/06_DATA_MODEL.md` и отчёт задачи.
11. Выполнить полный локальный прогон на PostgreSQL 18.4, независимый final-review, PR и CI согласно процессу.

## Матрица критериев и доказательств

| Критерий Jira | Ожидаемый результат | Автоматическое доказательство | Дополнительная проверка |
|---|---|---|---|
| новый и существующий Telegram user маршрутизируются детерминированно | отсутствие member, `pending`, `active` и запрещённые статусы дают стабильные разные маршруты | unit property/table tests start-route service; synthetic aiogram `/start` tests | сценарии 1–4 `test-plan.md` |
| повтор update не создаёт второе действие | одинаковый `update_id` фиксирует ровно одно реальное изменение member, один audit и один receipt; Bot API вне гарантии | PostgreSQL integration tests последовательного/конкурентного изменения статуса и retry-after-fault rollback | сценарии 6–7 |
| запрещённая роль или статус получает отказ | полная role/status/current→requested/self/admin-target/ownership матрица проверена после DB lock | parameterized unit policy и integration tests application command по актуальным строкам | сценарий 8 |
| административное действие оставляет audit event | изменение и event атомарны, before/after/reason воспроизводимы; audit row нельзя update/delete | success, fault-injection, concurrent-chain и trigger integration tests | сценарии 9–11 |
| restart не теряет состояние | новый engine/sessionmaker видит member, audit и processed update | integration test dispose/recreate database object | сценарий 12 |
| unit, integration и migration tests проходят | нет skip, миграция обратима, статические проверки зелёные | локальные команды и два CI jobs на точном commit | сценарий 14 и implementation report |

## Риски и меры снижения

- Гонка одинаковых updates: уникальный PK, отдельные сессии и реальный конкурентный member+audit integration test.
- Потерянный retry после ошибки: advisory lock, действие и complete receipt находятся в одной транзакции; rollback и повтор проверяются тестом.
- Потеря/повтор Telegram-ответа: честно оставить best-effort/at-least-once за границей транзакции; критические сообщения позднее проходят через outbox.
- Расхождение domain enum и DB constraints: единый перечень значений проверяется migration/integration test.
- Неполный receipt: application вставляет запись только в конце, все итоговые поля `NOT NULL`; прямой incomplete insert должен падать.
- Lost update и stale authorization: блокировать actor/target в UUID-порядке и повторно авторизовать после lock; проверить конкурентную цепочку audit.
- Утечка transport в domain: расширить AST architecture tests и оставить aiogram только в transport/bootstrap.
- Слишком широкая модель этапа: создавать только `members`, `audit_events`, `processed_telegram_updates`; будущие сущности не добавлять.
- Случайное решение `restricted`: безопасный deny зафиксирован как временная граница, без выдумывания granular permissions.
- Фальшивый зелёный integration: без `DATABASE_URL` Testcontainers сам поднимает PostgreSQL; недоступный Docker даёт ошибку, а DB job CI выполняет полный набор без skip/deselect.
- Реальные Telegram-эффекты: использовать fake session, не читать токен и не запускать polling.

## Проверки

- `uv sync --locked --all-groups` и `uv lock --check`;
- `docker compose config --quiet` и healthy PostgreSQL 18;
- Alembic `upgrade head → downgrade 0001 → upgrade head` на реальной БД;
- `uv run ruff format --check .` и `uv run ruff check .`;
- `uv run ty check src tests`;
- `DATABASE_URL=... uv run pytest` на Compose без deselected/skipped и контрольный `uv run pytest` через Testcontainers fallback;
- отдельные unit, architecture, transport и integration срезы;
- persistent member+audit duplicate test, incomplete receipt constraint, rollback/retry fault injection, concurrent admin chain, audit immutability и restart-persistence;
- `community-bot --check`, `community-worker --check`, `uv build`;
- `git diff --check`, поиск секретов, Jira key в runtime-именах и сетевых Telegram-вызовов;
- GitHub Actions `Quality` и `PostgreSQL and Alembic` на точном merge-candidate.

## Критерии готовности

- Каждый критерий Jira имеет воспроизводимое доказательство без skip.
- Миграция `0002` проходит вперёд, назад до `0001` и повторно вперёд на PostgreSQL 18.
- Домен не импортирует SQLAlchemy/aiogram; transport не принимает решений доступа.
- Один update даёт максимум одно зафиксированное PostgreSQL-действие даже при гонке и restart; внешняя отправка не называется exactly-once.
- Отказ по роли, статусу и владению основан на актуальной записи БД.
- Административное изменение атомарно связано с audit event.
- ADR-0006 явно принят владельцем до первого изменения реализации.
- Документация и implementation report отражают фактическое поведение.
- Независимый `final-review.md` содержит `Status: approved`, CI зелёный, а PR слит только после отдельного разрешения.
