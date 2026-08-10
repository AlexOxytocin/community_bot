# CB-7 — отчёт о реализации

## Статус

Обязательные замечания первого независимого final review исправлены, все
локальные барьеры повторены. Реализация в ветке `task/CB-7` готова к новому
независимому ревью уровня 3. Публикация implementation-коммита, создание PR и
переход Jira в «На проверке» выполняются только после нового
`Status: approved`.

## Что реализовано

- Добавлен закрытый набор именованных операций экономики: стартовый грант,
  резерв, полная и частичная выплата, возврат, награда задания сообщества,
  штраф, административная корректировка и точный разворот.
- `account_transactions` стал append-only источником истины. PostgreSQL CHECK,
  уникальные ограничения и trigger проверяют типы дельт, единственность гранта,
  точность и единственность разворота; кэши кредитов и опыта переведены в
  `BIGINT`.
- Публичный `EconomyMutationPort.apply_batch` работает внутри переданного unit
  of work и не делает скрытый commit. Batch получает advisory gates по ключам,
  затем блокирует участников и исходные проводки в каноническом порядке;
  поддерживается только all-new или all-stored повтор.
- Фактический flush строк журнала отделён от обновления кэшей и audit. Тестовый
  fault hooks после journal flush и после cache flush доказывают полный rollback
  и безопасный retry на обеих границах.
- Добавлены авторизованная история с keyset cursor, read-only сверка кэшей с
  SUM журнала и версионно-осведомлённый `LevelResolver`.
- Добавлена строгая product config schema v1 и редактируемый non-secret снимок
  `config/product-config.v1.json`: десять уровней, настраиваемые названия и
  пороги, а также политика interaction alerts `3/7`.
- PostgreSQL хранит неизменяемые версии конфигурации и уровней, историю
  активаций, singleton active pointer и завершённые backfill runs. Ingest,
  activation, no-op, rollback к старой версии и bootstrap идемпотентны и
  сериализованы общим config gate.
- Activation и bootstrap блокируют всех участников по UUID до проверки actor;
  economy блокирует тот же набор в том же порядке и никогда не ожидает config
  gate. Конкурентные сценарии с обратным входным порядком завершаются без
  дедлока.
- Исправлен baseline-дефект CB-17: Alembic callback теперь принимает точный
  `sqlalchemy.engine.Connection`; `ty` и реальный async migration cycle зелёные.
- README, архитектура и физическая модель данных синхронизированы с кодом.

## Отклонения от плана

Функциональная область не расширена. Для удобства чтения PostgreSQL-матрица
разделена на два обычных integration-файла и отдельный stateful property-файл,
а Testcontainers fallback запускает все три. Плановый fault barrier реализован точнее исходной
первой версии: journal INSERT сначала реально flush-ится, затем вызывается
первый hook; после отдельного cache/level flush вызывается второй hook и только
потом добавляется audit. Для активации отдельный hook вызывается после flush
active pointer и до backfill.

Поля `task_id`, `assignment_id` и `interaction_alert_id` не добавлялись: целевых
таблиц пока нет, поэтому план сознательно запрещает висячие UUID. Telegram UI,
задания, реальные переводы по assignments и автоматическое исправление
рассогласований остаются вне CB-7.

## Исправления первого финального ревью

- Targeted Testcontainers-команда теперь явно использует `--no-cov` и
  завершается exit `0`; обязательный coverage остаётся на полном Compose suite,
  где измеряется весь пакет, а не узкий DB subset.
- Пустой `apply_batch` детерминированно отклоняется `EconomyError`; публичный UoW
  test доказывает rollback предварительно сохранённого marker.
- Добавлен настоящий Hypothesis sequence через PostgreSQL/UoW со всеми типами
  операций, проверкой `SUM=cache` после каждого commit и отсутствием эффекта при
  reject.
- Concurrent scale test теперь одновременно запускает activation, earning и
  resolver read, различает шкалы v1/v2 и проверяет итоговые
  `level_config_version_id` по обе стороны UUID actor.
- Расширены точечные матрицы type/reversal-source idempotency, credit/
  experience/both reconciliation, moderator/inactive/unknown authorization,
  config hash/schema, concurrent collisions, bootstrap и малые резервы.

## Критерии Jira и доказательства

| Критерий | Статус | Реализация | Доказательство |
|---|---|---|---|
| Баланс и опыт равны сумме журнала | Закрыт | Ledger и кэши изменяются одним UoW; сверка ничего не исправляет молча | Матрица всех операций, конкурентные batch/reserve, fault rollback, restart и reconciliation tests |
| Повтор не создаёт второй эффект | Закрыт | 64-битный advisory gate + exact key/payload read; all-new/all-stored batch | Последовательные и конкурентные grant, batch, reversal, config ingest/activation и restart retry |
| Грант/возврат/резерв/штраф не меняют опыт | Закрыт | Закрытые factory и PostgreSQL CHECK | Unit/property matrix и прямые invalid SQL inserts |
| Резерв не уводит баланс ниже нуля | Закрыт | Проверка промежуточного итога после member row lock | Одновременные reserve `7` и `6` при балансе `10`: один отклонён, SUM=cache |
| Разворот точен и единственен | Закрыт | Source lock, application revalidation, self-FK, trigger и unique | Service retry; wrong member/delta/missing/chained/second reversal отвергнуты |
| Уровни и пороги меняются конфигурацией | Закрыт | Строгий candidate, content hash без config version, immutable versions и active pointer | Все десять границ, stale cache, activation v2, rollback v1 и большой BIGINT |
| История и сверка авторизованы | Закрыт | Active member/moderator только self; active administrator — любой target и reconciliation | Полная role/status/ownership matrix и стабильный cursor с одинаковыми timestamps |
| Unit, property, migration и PostgreSQL regression проходят | Закрыт | Compose и Testcontainers PostgreSQL 18, отдельная временная database на test | Compose: `201 passed`, 0 skip/deselect, coverage `92.41%`; Testcontainers: `29 passed`, 0 skip/deselect |

## Матрица утверждённого test plan

| № | Результат | Основное доказательство |
|---:|---|---|
| 1 | Пройден | Чистый upgrade; BIGINT выше int32; legacy nonzero upgrade и nonempty downgrade отклонены; пустой cycle проходит |
| 2 | Пройден | Прямые UPDATE/DELETE ledger, config, level, activation, backfill и pointer отклонены |
| 3 | Пройден | Интеграционная матрица всех девяти типов, SUM=cache |
| 4 | Пройден | Trim/канонизация даёт stored retry; изменение каждого значащего поля даёт conflict без эффекта |
| 5 | Пройден | Два конкурентных grant и restart retry оставляют одну строку `+5/+0` |
| 6 | Пройден | Конкурентные резервы сериализуются, отрицательного итога нет |
| 7 | Пройден | Неизвестные типы, неверные дельты/XP и второй grant отклонены DB |
| 8 | Пройден | Точный reversal, retry и все прямые SQL-подделки проверены |
| 9 | Пройден | Согласованная база даёт пустой результат; отдельная порча credit, experience и обоих кэшей даёт точный mismatch без repair |
| 10 | Пройден | Member/moderator/admin/inactive/unknown actor matrix |
| 11 | Пройден | Hypothesis через PostgreSQL/UoW генерирует grant/reserve/refund/reward/penalty/adjustment/reversal, после каждого commit/reject проверяет SUM=cache и отсутствие частичного эффекта |
| 12 | Пройден | Admin credit/experience adjustment, audit, retry, authorization и отрицательная граница |
| 13 | Пройден | Fault после реального ledger flush и отдельный fault после cache flush откатывают transaction/cache/audit; retry создаёт один эффект |
| 14 | Пройден | JSON order/whitespace/level order независимы; version исключена из hash; product fields меняют hash; invalid schema отклонена |
| 15 | Пройден | Sequential/concurrent ingest, exact retry, hash/version collisions, authorization и monotonic v2 |
| 16 | Пройден | Activation retry, changed-target conflict, no-op, v2 switch и v1 rollback |
| 17 | Пройден | Concurrent first activation разных targets и concurrent exact retry сериализованы общим gate |
| 18 | Пройден | Member/moderator/inactive admin и неизвестная version не меняют pointer/history/cache |
| 19 | Пройден | Bootstrap: first missing, invalid, member/inactive-admin, valid, existing active и stable retry |
| 20 | Пройден | Config/activation против economy с обратным UUID-порядком завершаются по timeout без дедлока |
| 21 | Пройден | `threshold-1/threshold` для всех уровней, `0`, `1001` и `2^40` |
| 22 | Пройден | Concurrent v2 activation/backfill, earning и resolver видят целую v1/v2 scale; итоговые cache value/version проверены по обе стороны UUID actor |
| 23 | Пройден | Один backfill на switch, no-op без backfill, fault pointer rollback, append-only run |
| 24 | Пройден | Семь строк с одинаковым timestamp прочитаны страницами без дублей/пропусков |
| 25 | Пройден | Публичный UoW: empty/mixed/fault rollback marker, commit, stored retry и reverse-order concurrent batches без `_session` |
| 26 | Пройден | Новый Database читает active/history/cache и безопасно повторяет grant |
| 27 | Пройден | `Connection` annotation, `ty` exit 0 и async Alembic runtime |
| 28 | Пройден | Полный Compose regression: `201 passed`, coverage `92.41%`, без skip/deselect |
| 29 | Пройден | Без `DATABASE_URL`, с targeted `--no-cov`, Testcontainers `postgres:18`: `29 passed`, exit `0`, без skip/deselect; coverage закрыт сценарием 28 |
| 30 | Пройден | Ruff format/check, ty, build, architecture и bot/worker `--check` успешны |
| 31 | Пройден | Ссылки, diff-check, secret/runtime-key scan и русский язык проверены |

## Проверки

| Проверка | Результат |
|---|---|
| `uv sync --locked --all-groups` | Успешно, lock не изменён |
| `uv run ruff format --check .` | Успешно, 130 файлов |
| `uv run ruff check .` | Успешно |
| `uv run ty check` | Успешно, включая исправление CB-17 |
| Compose `uv run pytest` | `201 passed`, 0 skipped, 0 deselected, coverage `92.41%` |
| Testcontainers economy integration | Три файла с `--no-cov`: `29 passed`, exit `0`, 0 skipped, 0 deselected |
| Alembic `upgrade head → downgrade base → upgrade head` | Успешно, итог `0003` |
| `uv build` | Успешно, sdist и wheel |
| `community-bot --check`; `community-worker --check` | Оба exit 0, внешних запросов нет |
| `git diff --check` и secret/runtime-key scan | Успешно |

## Документация

- Обновлены `README.md`, `docs/ARCHITECTURE.md` и
  `docs/mvp/06_DATA_MODEL.md`.
- Добавлен версионируемый non-secret fixture `config/product-config.v1.json`.
- ADR не добавлялся: решение укладывается в принятые ADR-0005, D-008, D-011 и
  D-012.
- Смысловая документация написана по-русски; код, идентификаторы, runtime errors
  и поля PostgreSQL — по-английски.

## Остаточные риски и границы

- Массовый backfill проверен функционально на pilot-scale данных; отдельный
  эксплуатационный порог производительности продуктом не принят.
- Reconciliation только сообщает расхождение. Исправление выполняется новой
  авторизованной `admin_adjustment` или точным reversal после проверки.
- Конкретные task/assignment/alert FK и вызовы settlement появятся в задачах,
  владеющих этими таблицами; публичная batch-композиция уже проверена.
- Реальные Telegram и внешние сервисы не вызывались.

## Внешние изменения

- Jira CB-7 ранее переведена через Atlassian API в «В работе» и содержит ссылку
  на одобренный план.
- CB-17 остаётся открытым до merge CB-7; отдельная ветка по нему не создавалась,
  как зафиксировано в Jira после уточнения владельца.
- После начала реализации Jira, Git remote и Telegram не изменялись.

## Следующий шаг

Независимый final-review читает актуальную Jira CB-7/CB-17, весь пакет уровня 3,
фактическую разницу и повторяет критические проверки. Он изменяет только
`tasks/CB-7/final-review.md`. При `Status: approved` implementation snapshot
фиксируется коммитом, публикуется, получает PR/CI и только затем переводится в
«На проверке».
