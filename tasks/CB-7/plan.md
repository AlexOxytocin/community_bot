# CB-7 — план реализации журнала экономики и версионных уровней

`community_bot.developer.plan.v1`

## Цель

Создать транзакционное ядро экономики MVP: неизменяемый журнал кредитов и опыта,
атомарные кэши участника, идемпотентные именованные операции, безопасное
резервирование, обратные коррекции, сверку и историю операций. Одновременно
реализовать принятую в CB-4 версионную продуктовую конфигурацию уровней и единый
`LevelResolver`, чтобы названия и пороги менялись конфигурацией без изменения
кода и устаревший кэш никогда не принимал решение о доступе.

## Уровень процесса

Уровень 3 по ADR-0004: задача меняет денежноподобный журнал, PostgreSQL-схему,
конкурентные транзакции и конфигурацию, влияющую на будущие решения о доступе.
Обязательны `plan-source-context.md`, `test-plan.md`, независимый
`plan-review.md`, полный PostgreSQL-прогон без пропусков,
`implementation-report.md` и независимый `final-review.md`.

Новое ADR не требуется: модульный монолит, PostgreSQL, SQLAlchemy async,
Alembic и unit of work уже приняты ADR-0005, а журнал и версионная шкала приняты
решениями D-008, D-011 и D-012. План не вводит новую межсервисную или внешнюю
границу.

## Область изменений

- доменные типы экономических операций, валидация дельт, результат уровня и
  детерминированный расчёт уровня;
- прикладные команды для стартового гранта, резерва, выплаты, возврата, штрафа,
  технической корректировки и обратной записи;
- PostgreSQL-модели и Alembic-миграция журнала, версий конфигурации, уровней,
  активаций, активного указателя и запусков backfill;
- идемпотентность по точному бизнес-ключу и защита конкурентных операций;
- атомарное обновление `credit_balance_cached`,
  `experience_total_cached`, `level_number` и версии кэша уровня;
- загрузка и строгая проверка редактируемого non-secret candidate-файла
  `config/product-config.v1.json`, содержащего уровни и принятую политику
  interaction alerts; канонический runtime source of truth после активации
  остаётся в PostgreSQL;
- административные ingest/activation-команды с историей, audit events,
  безопасным повтором, no-op и rollback к прежней неизменяемой версии;
- авторизованное чтение истории и административная сверка кэшей с журналом;
- unit, property-based, PostgreSQL integration, migration и regression tests;
- синхронизация README, архитектуры и точной физической модели данных.

## Вне области изменений

- регистрационный FSM, приглашения и вызов гранта из Telegram-онбординга
  (CB-5); CB-7 предоставляет готовую идемпотентную команду;
- каталог, шаблоны, задания, слоты, assignments, подтверждение результата и
  жизненный цикл резервов (CB-9–CB-11);
- поля и внешние ключи на `tasks`, `assignments` и interaction alerts:
  соответствующие таблицы ещё не существуют и будут добавлены только их
  миграциями вместе с проверяемой ссылочной целостностью;
- карма, надёжность, лидерборд, алерты взаимодействий, споры и UI администратора;
- Telegram handlers, реальные сетевые отправки, outbox и production worker;
- автоматическое исправление найденного рассогласования: сверка сообщает
  расхождение, а исправление выполняется отдельной проверяемой операцией;
- редактирование или удаление существующей операции журнала.

## Текущее состояние

- `main@10c0fbb` содержит фундамент CB-6: `members`, append-only
  `audit_events`, receipts Telegram updates, async unit of work и PostgreSQL 18
  integration fixture с отдельной временной базой на тест.
- В `members` уже есть кэши баланса, опыта и номера уровня, но нет журнала,
  версии кэша уровня и активной продуктовой конфигурации.
- Jira CB-7 имеет статус `К выполнению`; блокеры CB-4 и CB-6 имеют статус
  `Готово`. CB-7 блокирует CB-8, CB-10 и CB-11.
- Локальная Compose-среда PostgreSQL 18.4 доступна; Testcontainers fallback и CI
  с PostgreSQL/Alembic уже работают без `skip`.
- Baseline-проверка выявила `CB-17`: `ty` отклоняет слишком широкую аннотацию
  `object` у Alembic sync callback. По уточнённому владельцем правилу дефект,
  найденный до завершения функционала, исправляется и проверяется в CB-7 без
  отдельной ветки; Jira-баг закроется только после фактического исправления.

## Предлагаемое решение

### 1. Доменный контракт журнала

Определить закрытый `TransactionType`:

```text
starting_grant
task_reward_reserved
task_reward_earned
task_reward_refunded
partial_task_reward
community_task_reward
penalty
admin_adjustment
fraud_reversal
```

Исполняемый API не предоставляет общий публичный метод «изменить баланс на
произвольную дельту». Он предоставляет именованные команды, которые строят
валидную запись:

| Операция | `credit_delta` | `experience_delta` | Дополнительный инвариант |
|---|---:|---:|---|
| `starting_grant` | `+5` | `0` | один раз на участника |
| `task_reward_reserved` | `-N` | `0` | `N > 0`, остаток неотрицателен |
| `task_reward_earned` | `+N` | `+N` | `N > 0` |
| `task_reward_refunded` | `+N` | `0` | `N > 0` |
| `partial_task_reward` | `+N` | `+N` | `N > 0`; размер рассчитывает workflow задания |
| `community_task_reward` | `+N` | `+N` | `N > 0`, системный выпуск без автора |
| `penalty` | `-N` | `0` | `N > 0`, остаток неотрицателен |
| `admin_adjustment` | любое целое | любое целое | хотя бы одна дельта ненулевая; итоговые баланс и опыт неотрицательны |
| `fraud_reversal` | точная обратная дельта | точная обратная дельта | одна обратная запись на исходную операцию |

Трата, резерв, возврат, грант и штраф не дают и не уменьшают опыт. Только
авторизованная `admin_adjustment` с обязательной причиной может исправить
пропущенный или ошибочно сохранённый опыт без связанной кредитной дельты;
отрицательная adjustment не уводит итоговый опыт ниже нуля и пересчитывает
уровень. `fraud_reversal` остаётся предпочтительным способом точного
аннулирования существующего ошибочного начисления.

Каждая запись содержит точный `idempotency_key`, хэш канонического payload,
автора административного действия, обязательную для административных операций
причину и UTC timestamp. CB-7 вообще не создаёт `task_id`, `assignment_id` и
`interaction_alert_id`: до появления целевых таблиц эти значения не нужны ни
одному критерию и не могут быть достоверно проверены. Миграции CB-10/CB-11 и
anti-abuse добавят колонки одновременно с настоящими FK и начнут передавать их
в расширенную версию named primitive. Фиктивные aggregates и dangling UUID не
создаются.

Canonical projection ledger payload имеет версию схемы `1` и ровно поля:
`transaction_type`, `member_id`, `credit_delta`, `experience_delta`,
`actor_member_id`, `reason`, `comment`, `reversed_transaction_id`. UUID
сериализуются в lowercase canonical form, enum — своим value, отсутствующие
значения — JSON `null`; reason/comment предварительно trim, административная
reason не может быть пустой; ключи сортируются, пробелы JSON незначимы.
`idempotency_key`, созданный timestamp и представление входного JSON в hash не
входят. Изменение любого перечисленного значащего поля
при том же key даёт conflict; иное форматирование того же typed command — нет.
Для `starting_grant` caller не передаёт key: сервис всегда строит
`starting_grant:{member_id}` и фиксированный canonical payload `+5/+0`.

### 2. Неизменяемость и ограничения PostgreSQL

Миграция `0003` сначала проверяет legacy precondition: каждый существующий на
`0002` участник обязан иметь оба кэша `0` и `level_number = 1`, потому что
источника для ненулевых значений до ledger нет. Нарушение явно прерывает upgrade
без изменений вместо молчаливого обнуления или выдуманной opening transaction.
После проверки оба кэша переводятся из `INTEGER` в `BIGINT`.

Затем миграция создаёт `account_transactions` с `BIGINT`-дельтами, а пороги
`levels.experience_required` также хранит как `BIGINT`,
уникальным `idempotency_key`, индексами истории и self-FK
`reversed_transaction_id`. PostgreSQL CHECK ограничивает допустимые знаки и
соотношения дельт по типу там, где правило выражается одной строкой. Частичный
unique index гарантирует одну `starting_grant` на `member_id`, а другой — одну
`fraud_reversal` на исходную запись.

`BEFORE INSERT` trigger для reversal блокирует source row и отклоняет ссылку на
отсутствующую запись, другого участника, уже обратную запись, несовпадающие
обратные credit/experience deltas и `reversed_transaction_id` у любого другого
типа. Partial unique index дополнительно гарантирует единственную reversal.

Row-level trigger отклоняет `UPDATE` и `DELETE` журнала. Коррекция всегда
добавляет новую строку. Кэш не является источником истины и меняется только в
той же транзакции, что и append журнала. Тесты очищают данные удалением всей
временной database, а не обходом append-only trigger.

Downgrade `0003 → 0002` допускается только при пустых новых economic/config
таблицах и исходных нулевых кэшах/level 1; иначе он явно отказывается терять
историю. Пустой reversible cycle возвращает типы кэшей в `INTEGER`.

### 3. Транзакция и конкурентность

Публичная mutation primitive принимает непустой batch команд. Для batch порядок
фиксирован до первого append:

1. полностью валидировать canonical payload каждой команды и уникальность ключей
   внутри batch;
2. вычислить одноаргументные signed `BIGINT` advisory lock IDs для всех полных
   idempotency keys, убрать повторы и получить gates по числовому lock ID, затем
   по exact key как стабильному tie-breaker;
3. выполнить exact reads всех `idempotency_key`; changed payload отклонить;
   если сохранены все команды — вернуть все stored results, если ни одной —
   продолжить, а смешанный набор stored/new отклонить как inconsistent batch
   retry без новых эффектов;
4. собрать `member_id` всех новых entries и заблокировать строки через
   `SELECT ... FOR UPDATE` в порядке canonical UUID;
5. собрать reversal sources и заблокировать transaction rows в порядке UUID
   после member rows;
6. применить новые команды в исходном business order batch, каждый раз проверяя
   текущий промежуточный неотрицательный баланс/опыт;
7. append entries, flush, обновить кэши/уровни и добавить административные audit;
8. внешний владелец UoW выполняет единственный commit.

Хэш advisory lock может только избыточно сериализовать коллизию; идентичность
всегда проверяется exact read. Используется одноаргументная `BIGINT`-сигнатура,
чтобы не повторить границу signed `int32`, найденную и исправленную в CB-6.

Application layer определяет публичный `EconomyMutationPort` с методом
`apply_batch(commands) -> tuple[EconomyMutationResult, ...]`, который не
открывает transaction и не делает commit. Convenience `apply_one(command)`
делегирует batch из одного элемента. `EconomyUnitOfWork` предоставляет свойство
`economy: EconomyMutationPort` и единственный `commit()`. Infrastructure
`SqlAlchemyEconomyMutation` получает уже активную `AsyncSession`, но session не
выходит в application API. Standalone `EconomyService` владеет UoW, вызывает
`unit_of_work.economy.apply_one(...)` и один commit. Будущие task workflows
владеют расширенным UoW, меняют task-like state, передают полный набор named
entries одному `economy.apply_batch(...)` и выполняют тот же единственный
commit. Последовательные `apply_one` для составного settlement запрещены:
только полный batch гарантирует общий prelock. Вложенный service/UoW, доступ к
`_session` и скрытый commit запрещены.

Fault-injection hooks располагаются после фактического SQL flush журнала и до
обновления/commit, а также после переключения active pointer до завершения
backfill. Исключение должно откатывать весь набор эффектов.

### 4. Версионная конфигурация уровней

Файл `config/product-config.v1.json` имеет строгую schema version `1`, содержит
identity metadata `config_version`, ровно десять элементов `levels` с
`level_number`, `experience_required`, `display_name`, nullable `description`,
nullable `level_up_message`, `permissions`, а также top-level поля
`interaction_alert_threshold = 3` и `interaction_alert_window_days = 7`. Это
единый product snapshot для D-011 и
D-016; CB-7 хранит и версионирует policy, а вычисление алертов остаётся будущей
задаче.

`content_hash` не задаётся оператором. SHA-256 вычисляется по канонической
projection из `schema_version`, нормализованных `levels`,
`interaction_alert_threshold` и `interaction_alert_window_days`, но без
`config_version`. Поэтому один product snapshot
под v1 и v2 имеет одинаковый hash и второй ingest отклоняется, а изменение
любого level/policy field меняет hash. JSON keys сортируются, уровни
нормализуются по `level_number`, whitespace исходного файла незначим.

Pydantic loader до открытия изменяющей транзакции проверяет:

- положительную `config_version`; монотонность относительно сохранённых версий
  проверяет ingest внутри сериализованной PostgreSQL-транзакции;
- ровно десять уникальных последовательных номеров `1..10`;
- непустые русские display names;
- строго возрастающие неотрицательные пороги, `level 1 = 0`;
- JSON-совместимый объект permissions;
- целый alert threshold `>= 0`, где `0` отключает новые алерты, и window days
  `> 0`;
- отсутствие неизвестных полей во всей schema version `1`.

Любая config mutation — standalone ingest, standalone activation или composite
bootstrap — сначала берёт один общий fixed transaction-scoped advisory gate
`product_config_mutation`, и только затем блокирует actor row. Внутренние
`ingest_locked`/`activate_locked` принимают уже полученный guard и сами gates или
actor row повторно не получают. Bootstrap получает общий gate один раз,
блокирует/проверяет actor один раз и последовательно вызывает обе locked
primitives в том же UoW. Другого допустимого порядка config locks нет.

После общего gate ingest повторно читает известные versions/hashes и проверяет
монотонность. Это сериализует same-version/different-hash,
same-content/different-version и coordinator против standalone commands без
deadlock или необработанного `IntegrityError`.

Новый ingest выполняет только active administrator: после gate строка actor
блокируется и серверно проверяется до любой вставки, а созданная version получает
`created_by_member_id` и audit. Idempotent retry существующей той же пары
возвращает stored result без второго audit. Отсутствующий, inactive или
non-admin actor не создаёт version/levels/audit.

Ingest имеет identity
`product_config_version:{version}:{content_hash}`. Повтор той же пары возвращает
существующую версию; тот же номер с другим хэшем и тот же snapshot под новым
номером отклоняются. После ingest `product_config_versions` и `levels`
неизменяемы на уровне PostgreSQL.

Activation имеет отдельную identity
`activate_product_config:{activation_command_id}` и целевую уже загруженную
версию. Команду выполняет только текущий активный administrator. Повтор того же
command id и target возвращает сохранённый outcome; тот же command id с иным
target отклоняется. Новая команда может вернуть указатель к старой версии.
Target, который уже active, создаёт activation outcome и audit, но не backfill.

После общего `product_config_mutation` gate и actor check activation выполняет
exact command lookup, target validation и `SELECT ... FOR UPDATE` существующего
pointer. Поэтому две первые команды при отсутствующей singleton row, команды
разных targets, конкурентные retry и composite bootstrap сериализованы;
отсутствие строки больше не считается блокировкой.

При реальном переключении одна транзакция:

1. сериализует singleton active pointer;
2. записывает activation и audit;
3. переключает pointer;
4. создаёт ровно один `level_backfill_run`;
5. пересчитывает всем участникам `level_number` и
   `level_config_version_id`;
6. завершает run и commit.

Ошибка в любом пункте сохраняет прежний pointer и кэши. Изменение шкалы не
создаёт ledger operations и массовые уведомления. Для первого bootstrap нужны
валидный candidate и существующий active administrator.

CB-7 поставляет `ProductConfigBootstrapCoordinator`, а не скрытый seed. Его
явные входы: optional candidate path, optional `actor_member_id` и optional
stable `activation_command_id`, который оператор сохраняет для безопасного
retry. Coordinator работает так:

- active version есть, candidate отсутствует — вернуть active version без
  actor и DB mutation;
- active version есть, candidate невалиден — config error до DB mutation,
  прежний pointer сохранён;
- active version отсутствует, candidate отсутствует — config error;
- candidate валиден — actor ID и activation command ID обязательны; в одном UoW
  actor повторно читается и блокируется, обязан быть active administrator, затем
  выполняются ingest и activation с их отдельными identities и одним commit;
- отсутствующий/inactive/non-admin actor отклоняется без ingest, activation,
  audit или pointer mutation.

Coordinator является поставляемой bootstrap-границей для будущего runtime и
полностью integration-тестируется сейчас. Текущий runtime entrypoint остаётся
безопасным stub до отдельной задачи запуска, но ему не потребуется обход
авторизации или новый контракт. Candidate path и IDs — non-secret operator
inputs; coordinator никогда сам не выдаёт administrator role и не генерирует
новый activation ID при retry.

`product_config_versions`, `levels`, `product_config_activations` и завершённые
`level_backfill_runs` защищаются от `UPDATE`/`DELETE` общим append-only trigger.
Backfill run сразу вставляется с итоговым outcome в той же синхронной
транзакции, поэтому промежуточное mutable состояние не требуется. У singleton
pointer запрещены `DELETE` и смена singleton key; разрешено только атомарное
обновление ссылок/UTC timestamp.

### 5. `LevelResolver` и кэш

`LevelResolver` принимает `experience_total`, активную immutable шкалу и
опциональный кэш `(level_number, level_config_version_id)`. Если версия кэша
совпадает, допустимо вернуть кэш; иначе уровень синхронно рассчитывается как
последний порог `<= experience_total`. Значение выше последнего порога остаётся
на уровне 10.

Прикладной query всегда читает active pointer и одну связанную шкалу в одном
PostgreSQL snapshot. Ни профиль, ни будущая проверка `minimum_level`, ни
лидерборд/уведомление не должны читать `members.level_number` напрямую для
решения. Архитектурный тест запрещает обход через новый прикладной код, а
публичный результат resolver содержит номер, отображаемое имя и config version.

### 6. История и сверка

История участника возвращается только после серверной проверки актуальных
actor/target: активный участник или модератор читает только себя, активный
administrator — любого участника. Пагинация использует стабильный cursor
`(created_at, id)` и порядок `created_at DESC, id DESC`, не пропуская записи с
одинаковым timestamp.

Сверка доступна только активному administrator и одной repeatable-read
транзакцией сравнивает `SUM(credit_delta)`, `SUM(experience_delta)` с кэшами
участников. Она возвращает структурированные mismatches, включая ожидаемые и
фактические значения, но ничего не исправляет. Ручное искусственное изменение
кэша должно быть обнаружено. Пустой журнал считается суммой `0`.

## Ключевые решения и альтернативы

| Решение | Выбрано | Отклонено и почему |
|---|---|---|
| Источник баланса | append-only PostgreSQL ledger | прямой mutable balance не даёт истории и сверки |
| Идемпотентность | advisory gate + exact unique key + payload hash | только unique constraint не даёт детерминированного stored outcome и удобной проверки конфликта |
| task/assignment связи | полностью отсутствуют до миграций владельцев aggregates | dangling UUID допускают недостоверные значения; фиктивные таблицы расширяют scope |
| Кэш уровня | номер + config version, resolver при stale | без версии кэш может молча принять неверное access decision |
| Candidate config | строгий JSON `schema_version=1` с levels и top-level interaction policy fields | YAML потребовал бы новую зависимость; отдельный policy source нарушил бы атомарность общей версии |
| Runtime source | immutable PostgreSQL version + singleton pointer | файл не обеспечивает атомарную активацию, историю и согласованный snapshot |
| Backfill | синхронно в activation transaction для MVP | фоновой worker/outbox пока не нужен и создаст промежуточные состояния; resolver всё равно остаётся correctness boundary |
| Reconciliation | read-only report | автоматический repair скрывает причину и создаёт неаудированную экономическую мутацию |

## Шаги реализации

1. Добавить доменные enum/dataclasses, правила дельт, канонизацию payload и
   чистый расчёт уровня.
2. Добавить Pydantic-схему и explicit JSON candidate-файл с принятой пилотной
   шкалой и interaction policy `3/7`.
3. Расширить SQLAlchemy models и создать reversible Alembic migration `0003`
   со всеми constraints, indexes и append-only triggers.
4. Добавить публичные `EconomyMutationPort.apply_batch`/`EconomyUnitOfWork`,
   standalone orchestrator и SQLAlchemy adapter над уже активной session без
   nested commit, с общим prelock всего batch.
5. Реализовать именованные economy services, точный idempotency protocol,
   атомарные cache updates, correction и fault hooks.
6. Реализовать сериализованные ingest/activation/backfill,
   `ProductConfigBootstrapCoordinator` и `LevelResolver` с административной
   авторизацией и audit.
7. Реализовать авторизованную историю и read-only reconciliation.
8. Добавить unit/property/integration/migration/architecture tests по
   `test-plan.md`.
9. Исправить тип Alembic callback из CB-17 в этой ветке и обновить документацию
   фактической схемой, bootstrap contract и будущими task/assignment columns/FK.
10. Выполнить полный Compose и Testcontainers-контуры без пропусков, quality,
    migration cycle, build, entrypoints, diff/link/secret checks; оформить
    `implementation-report.md` и независимое final review.

## Риски и меры снижения

- **Double spend при конкуренции.** Advisory gate не заменяет row lock;
  отрицательные операции всегда блокируют member и проверяют баланс после lock.
- **Deadlock составных операций.** Product config использует один общий gate до
  actor; economy batch заранее сортирует объединённые idempotency/member/source
  locks. Конкурентные обратные input orders проверяются с жёстким timeout.
- **Дубль с изменённым payload.** Сохранённый SHA-256 сравнивается при каждом
  retry; конфликт не возвращается как успех.
- **Расхождение ledger/cache.** Append и cache update находятся в одной
  транзакции; property tests проверяют длинные последовательности, сверка
  обнаруживает искусственное нарушение.
- **Неполная correction.** Reversal строится только из сохранённой исходной
  записи и проверяется cross-row trigger; admin adjustment опыта требует active
  administrator, причины и неотрицательного итога.
- **Смешанная шкала при активации.** Pointer, activation, backfill и cache
  version commit атомарны; read query использует согласованный snapshot.
- **Долгий backfill.** В MVP ожидается малое число участников; измеряется число
  обновлений. При росте отдельная Jira-задача сможет вынести backfill в batches,
  не меняя resolver correctness boundary.
- **Слишком широкое ядро.** Task lifecycle и Telegram orchestration явно
  исключены; CB-7 предоставляет композиционные transaction primitives.
- **Секреты в config.** Candidate содержит только product values; loader
  запрещает неизвестные поля, а secret scan охватывает новый файл.

## Матрица критериев Jira и доказательств

| Критерий Jira | Реализуемый результат | Воспроизводимая проверка |
|---|---|---|
| Сумма журнала равна кэшу после каждой операции | единая транзакция append + cache | сценарии 3, 8, 9, 11 `test-plan.md` |
| Повтор idempotency key не создаёт двойной эффект | gate, exact lookup, stored result/hash | сценарии 4, 5, 12 |
| Грант и возврат не дают опыт | именованные invariants + DB CHECK | сценарии 3, 5, 11 |
| Трата не уменьшает опыт | reserve/penalty имеют exp `0`; admin correction отделена и аудируется | сценарии 3, 6, 11, 12 |
| Конкурентные резервы не дают отрицательный баланс | member row lock и post-lock check | сценарий 6 |
| Сверка обнаруживает искусственный mismatch | read-only aggregate report | сценарий 9 |
| Unit/property/PostgreSQL integration проходят | полный набор автоматических тестов | все сценарии `test-plan.md` и финальный regression |

## Проверки

Полная матрица находится в `tasks/CB-7/test-plan.md`. Обязательный финальный
минимум:

```text
docker compose up -d postgres
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv build
uv run community-bot --check
uv run community-worker --check
```

Отдельно полный economy integration-файл запускается без `DATABASE_URL`, чтобы
доказать Testcontainers fallback. Ни один обязательный test не может быть
`skipped` или `deselected`.

## Критерии готовности

- независимый `plan-review.md` имеет `Status: approved` до первого изменения
  кода;
- все семь критериев Jira сопоставлены с зелёными доказательствами;
- журнал и версии конфигурации невозможно изменить или удалить row-level SQL;
- все именованные операции атомарны, идемпотентны и сохраняют cache invariants;
- составные economy batch и конкурентные config paths завершаются без deadlock,
  partial effect и скрытого commit;
- starting grant ровно `+5/+0`, конкурентно один раз;
- LevelResolver корректен на всех границах и не доверяет stale cache;
- ingest, activation, no-op, retry, rollback и fault rollback воспроизведены;
- первая конкурентная activation и ingest collision имеют детерминированный
  исход, а общий product snapshot включает levels и interaction policy;
- migration согласует ledger/cache `BIGINT` и отклоняет недостоверные legacy
  кэши без молчаливой потери;
- публичный composition API доказывает общий commit/rollback без `_session`;
- reconciliation находит искусственное расхождение и не исправляет его молча;
- Compose и Testcontainers PostgreSQL 18 проходят без skip/deselect;
- миграция проходит empty/populated upgrade и полный downgrade/upgrade cycle;
- Ruff, ty, coverage, build, entrypoints, diff, links и secret scan зелёные;
- документация синхронизирована, `implementation-report.md` завершён,
  независимый `final-review.md` имеет `Status: approved`.
