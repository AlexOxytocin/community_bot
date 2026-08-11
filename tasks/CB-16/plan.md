# CB-16 — план общей регрессии и готовности пилота

## Статус и цель

Уровень процесса: 3. Цель — один раз проверить собранный MVP целиком на
актуальном `main`, подготовить воспроизводимые инструменты пилота и не допустить
когорту при критическом дефекте, нарушении ledger или непроверенном
восстановлении.

План не добавляет новую инфраструктуру и не превращает пилот в корпоративный
релизный поезд. Он соединяет существующие проверки в один доказательный контур,
закрывает только отсутствующие E2E/метрики/операционные доказательства и
фиксирует найденные регрессионные дефекты отдельно.

## Область задачи

Входит:

1. Автоматизированные сквозные сценарии A–D на PostgreSQL 18 с обезличенными
   участниками и синтетическими Telegram updates.
2. Единая матрица существующих проверок критических гонок, идемпотентности,
   авторизации, приватности, outbox и повторной доставки; новые тесты только для
   реально отсутствующих сквозных границ.
3. Миграции пустой базы и обновление поддерживаемого снимка `0009 → 0010` с
   сохранением репрезентативных данных.
4. Свежий backup → isolated restore drill на self-hosted PostgreSQL и сверка
   ledger/cache на восстановленной базе.
5. Read-only агрегированный отчёт метрик пилота без персональных данных.
6. Обезличенный тестовый seed, ежедневный checklist, условия остановки,
   rollback/завершение и шаблон ретроспективы.
7. Production smoke существующего deployment без реальных пользовательских
   сообщений.

Не входит:

- проведение самого пилота продолжительностью 4–6 недель;
- добавление функциональности вне уже принятого MVP;
- реальные приватные чаты, копирование production-данных в тесты и автоматическая
  загрузка тестовых участников в production;
- external backup, object storage, webhook, новая админ-панель и новый брокер;
- реальная Telegram-отправка без отдельного разрешения владельца.

## Артефакты и изменения

### 1. Обезличенный E2E seed

- Добавить `tests/fixtures/pilot_e2e_seed.json` с техническими Telegram ID,
  профилями администратора, модератора и участников A/B/C. Значения не
  совпадают с реальными пользователями и помечены как test-only.
- Категории и шаблоны не дублировать: E2E использует канонический seed
  `migrations/data/task_catalog_v1.json` и проверяет его восемь категорий и
  восемь активных шаблонов.
- Loader тестового seed размещается только в `tests/`; runtime не получает
  команду массовой загрузки тестовых пользователей.

### 2. Сквозные сценарии A–D

- Создать `tests/e2e/test_pilot_scenarios.py` и общий fixture настоящей
  временной PostgreSQL 18.
- Каждый test получает собственную пустую временную DB и самостоятельно создаёт
  все предусловия. Общие helpers переиспользуют шаги, но не разделяют mutable
  state между A–D и не зависят от порядка pytest.
- Пользовательские действия проходят через реальный aiogram
  `Dispatcher`/зарегистрированные routers и callbacks с fake Bot API. Прямые
  application-вызовы допустимы только для setup и DB-oracle после transport
  flow; fake Bot фиксирует ответы и доказывает отсутствие сетевой отправки.
- Сценарий A проходит: invite → обе регистрации → одобрение и ровно один
  `starting_grant` → публикация member-task за 2 кредита → принятие →
  версионируемый результат → полное подтверждение → ledger/cache/опыт/уровень/
  лидерборд/eligibility/outbox.
- Сценарий B публикует и отменяет незанятое задание, проверяет один refund,
  неизменный опыт и отсутствие доступного задания после отмены.
- Сценарий C отклоняет результат, открывает durable dispute, разрешает его
  частичной выплатой уполномоченного независимого модератора и проверяет
  assignment, reserve, ledger, reliability, audit и notifications.
- Сценарий D после оплаченного member-assignment создаёт и меняет карму,
  проверяет анонимный aggregate для получателя, обе immutable revision для
  администратора с `karma_review` и audit raw-read. Paid interaction создаётся
  внутри D общим helper, а не берётся из состояния сценария A.
- Каждый сценарий повторяет хотя бы один сохранённый update/callback и
  подтверждает отсутствие второго необратимого эффекта.

### 3. Регрессионные дефекты

После воспроизводимого сбоя готового функционала:

1. Сохранить минимальный автоматический reproducer и определить влияние.
2. Через Atlassian Rovo API проверить дубликаты и создать отдельный тип `Баг`
   под `CB-2`. Каждый новый regression Bug получает label `cb16-regression`,
   ровно один label `severity-critical|severity-high|severity-medium|severity-low`
   и Jira-связь `Relates` с `CB-16`. Только critical/high, блокирующий запуск или
   сценарии A–D, дополнительно получает связь `Blocks` в направлении bug →
   `CB-16`.
3. Исправлять баг в отдельной ветке `task/<BUG-KEY>` от актуального `main`, с
   целевыми тестами, отчётом, final review, PR и CI.
4. После слияния обновить `task/CB-16` из `main`. Полную регрессию не повторять
   после каждого бага: в баге выполняются только затронутые проверки, а один
   финальный полный проход идёт после слияния всего blocking-набора.

Критическими считаются: утечка приватных данных/прав, нарушение ledger или
двойная выплата, потеря доменных данных, невозможность регистрации/полного
обмена либо невозможность восстановить базу. High-дефект, ломающий A–D или
безопасный запуск пилота, также блокирует завершение. Остальные дефекты получают
Jira-запись, оценку риска и явное решение владельца. Для оставленного open
medium/low после решения владельца добавляется ровно один label
`decision-accepted|decision-deferred`; дефекты не маскируются в CB-16.

Финальный discovery set строится JQL `project = CB AND labels = cb16-regression`.
Он полностью сопоставляется с таблицей дефектов в `implementation-report.md`.
Отдельный JQL по `severity-critical|severity-high AND statusCategory != Done`
должен вернуть пустой набор; каждый оставшийся open medium/low обязан иметь
decision label и ссылку на решение владельца.

### 4. Миграции и восстановление

- В `tests/integration/test_pilot_readiness.py` проверить чистое
  `alembic upgrade head`, полный цикл `head → base → head` на пустой базе и
  обновление репрезентативной базы `0009 → 0010` без потери members, ledger,
  assignments, moderation и reputation history.
- Fixture `0009` содержит два `outbox_events` с разными business key/payload/
  timestamps: unpublished (`published_at IS NULL`) и published. После upgrade
  первый получает `pending`, второй `materialized`; их прежние данные не
  меняются. Проверяются defaults, `ck_outbox_*`, `ix_outbox_due`, ограничения и
  индексы `notifications`, `process_heartbeats`, отклонение невалидных lease/
  failed/materialized состояний и идемпотентный повтор `upgrade head`.
- Дополнить `ops/restore_drill.sh` fail-closed SQL-проверкой:
  `alembic_version=0010`, наличие обязательных таблиц и нулевое число
  расхождений `members.*_cached` с `SUM(account_transactions.*_delta)`.
- Скрипт по-прежнему восстанавливает только отдельную временную базу, не
  переключает production и удаляет drill DB через trap.
- На сервере создать свежий backup, выполнить isolated restore, измерить UTC
  начало/конец, возраст backup и длительность; значения секретов, IP и строки
  подключения в отчёт не включать.

### 5. Метрики пилота

- Добавить `src/community_bot/application/pilot.py` с DTO
  `community_bot.pilot_metrics.v1` и read-only портом агрегатов.
- Добавить PostgreSQL-адаптер `src/community_bot/infrastructure/db/pilot.py` и
  CLI `src/community_bot/bootstrap/pilot_report.py` / entry point
  `community-pilot-report`.
- CLI принимает явный UTC-полуинтервал `[from,to)`, не меняет БД и выводит JSON
  без имён, Telegram ID, UUID участников, комментариев или материалов.
- JSON schema использует `additionalProperties=false`, фиксированные ключи и
  только агрегаты. Participant-shaped dynamic keys, UUID/Telegram ID, raw
  labels, event timestamps, тексты и массивы сущностей запрещены.

Точная семантика `community_bot.pilot_metrics.v1`:

| Поле | Числитель / знаменатель | Event time и правила |
|---|---|---|
| `invite_conversion_rate` | redemptions закрытых invitation / `SUM(max_uses)` этих invitation | invitation создан в `[from,to)` и к `to` истёк, отозван или исчерпал uses; denominator `0` → `null` |
| `onboarding_completion_rate` | cohort members с `approved_at < to` / redemptions в `[from,to)` | cohort по `redeemed_at`; denominator `0` → `null` |
| `current_active_members` | count текущего `status=active` | snapshot на `generated_at`; не выдаётся за историческое состояние на `to` |
| `tasks_per_active_member` | published tasks в `[from,to)` / `current_active_members` | `published_at`; denominator `0` → `null` |
| `task_fill_rate` | matured tasks с хотя бы одним assignment / все matured tasks | task published в `[from,to)`, maturity = `MIN(published_at+48h, deadline_at) < to`; cancel до первого accept остаётся failure |
| `task_fill_rate_48h` | matured tasks с первым `accepted_at < published_at+48h` / все matured tasks | событие ровно в `+48h` не входит |
| `assignment_completion_rate` | assignments с effective paid full/partial outcome к `to` / assignments, принятые в `[from,to)` | denominator по `accepted_at`; cancel/reject/no_show/refund/fraud не completion |
| `median_time_to_first_completion_seconds` | median от member `approved_at` до первого ненулевого reward ledger | member approved в `[from,to)`; reward может быть member/community, event = transaction `created_at < to`; пусто → `null` |
| `repeat_action_rate` | performers с последующим task publish или assignment accept / performers с первым paid completion в `[from,to)` | действие строго после первого reward и `<to`; denominator `0` → `null` |
| `unique_paid_pairs` | distinct unordered creator/performer pairs | только ненулевой full/partial member-task reward ledger в `[from,to)`; community исключён |
| `community_tasks` | published, paid completed и `SUM(community_task_reward.credit_delta)` | task `published_at` и ledger `created_at` в `[from,to)`; только агрегаты |
| `interaction_alerts` | opened и closed counts по фиксированным outcomes | `opened_at`/`closed_at` в `[from,to)`; notes не читаются |
| `disputes_and_cancellations` | dispute opened и task/assignment cancel counts | соответствующий persisted timestamp в `[from,to)` |
| `weekly_retention_rate` | actors active в обеих неделях / actors active в предыдущей неделе | две соседние UTC-недели `[to-14d,to-7d)` и `[to-7d,to)`; activity = task publish, assignment accept/result submit или karma mutation; denominator `0` → `null` |
| `top_20_percent_completion_share` | paid completions top `ceil(0.2*N)` performers / все paid completions | `[from,to)` по reward ledger; rank count DESC, UUID ASC только внутри SQL tie-break, UUID не выводится; denominator `0` → `null` |

Все rates сериализуются decimal с четырьмя знаками, counts — integer, времена —
UTC. Порогам PRD соответствуют точные поля: `task_fill_rate >= 0.7000`,
`assignment_completion_rate >= 0.7500`, `repeat_action_rate >= 0.6000`.

Распределения имеют только фиксированные coarse buckets: credits
`0|1-4|5-9|10-19|20+`, experience `0|1-9|10-24|25-49|50-99|100+`.
Если bucket содержит `1` или `2` участника, он детерминированно объединяется со
следующим верхним bucket, а верхний — с предыдущим, пока merged cell не станет
`0` либо `>=3`; исходная label/count не выводится. При невозможности получить
cell `>=3` выводится только `suppressed_count` без диапазона. SQL может временно
использовать UUID для расчёта, но output и logs их не содержат.

- Unit/integration tests фиксируют каждую формулу, empty denominator, события
  ровно на `from`, `to`, `+48h`, full/partial/reject/cancel, cross-week
  retention, concentration tie, merge/suppression малых cells, отсутствие PII и
  ledger-authoritative credits/experience при намеренно испорченном кэше.

### 6. Операционный комплект

- Дополнить `docs/operations/PILOT_RUNBOOK.md` точными preflight, ежедневными,
  еженедельными, stop, rollback и closeout действиями.
- Создать `docs/operations/PILOT_CHECKLIST.md`: дата/релиз, health, migration,
  failed outbox, ошибки, reconciliation, backup age, продуктовые метрики,
  ручные решения и итог `continue|pause|stop` без приватного содержимого.
- Создать `docs/operations/PILOT_RETROSPECTIVE.md` как пустой шаблон результата
  4–6 недель: когорта, метрики против порогов, инциденты, экономика,
  взаимодействия, решения и следующий шаг. Не заполнять выдуманными данными.
- Условия stop совпадают с `09_IMPLEMENTATION_PLAN.md`: ledger corruption или
  duplicate, раскрытие raw-кармы, эскалация прав, нелокализуемый фарм,
  необратимая потеря заданий/результатов либо невозможность восстановления.

## Порядок реализации

1. Зафиксировать плановый пакет и получить независимый `Status: approved`.
2. Реализовать seed, E2E A–D, migration/restore и pilot-report/checklist одним
   законченным пакетом; запускать только узкие тесты изменяемого среза.
3. Выполнить targeted/integration/smoke проверки готового пакета.
4. Провести один полный регрессионный проход. Найденные баги оформить и
   исправить отдельными задачами/ветками по протоколу выше.
5. После слияния blocking-багов обновить ветку CB-16 и выполнить один итоговый
   полный regression + production operational smoke.
6. Заполнить `implementation-report.md`, получить независимый
   `final-review.md`, затем PR/CI/merge и синхронизацию Jira.

## Проверки готового результата

Локальный единый gate на PostgreSQL 18:

```powershell
uv sync --locked --all-groups
docker compose up -d --wait postgres
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests
uv run pytest
uv run alembic downgrade base
uv run alembic upgrade head
uv build
uv run community-bot --check
uv run community-worker --check
uv run community-pilot-report --from 2026-08-01T00:00:00Z --to 2026-08-08T00:00:00Z
```

Требования к gate: PostgreSQL 18, `0 skipped`, `0 deselected`, coverage не ниже
80%, все A–D и migration tests входят в обычный `pytest`, а отчёт метрик
детерминирован и не содержит PII. После него выполняются secret scan,
`git diff --check`, проверка локальных Markdown-ссылок и CI на PR.

Production gate: текущий immutable digest, healthy `postgres/worker/bot`,
`migrate` code 0, свежий backup, успешный isolated restore, ноль ledger mismatch,
допустимый backup age и длительность ниже RTO. Реальные Telegram updates и
сообщения в этот gate не входят без отдельного разрешения.

## Критерий завершения

Каждый критерий Jira имеет воспроизводимое доказательство в
`implementation-report.md`; нет открытых critical и blocking high дефектов;
прочие известные дефекты перечислены с Jira-ключами и решением владельца;
финальное независимое ревью имеет `Status: approved`; PR и CI зелёные.

## Риски и меры

- Один сервер не переживает потерю хоста — принятый риск ADR-0009, не скрывается
  успешным logical restore.
- Синтетический Telegram E2E не доказывает сеть Bot API — production health и
  отдельный разрешённый ручной smoke различаются в отчёте.
- Агрегаты малой когорты могут косвенно раскрывать участника — CLI не выводит
  измерения по отдельным людям, сырые UUID и тексты.
- Общая регрессия дорогая — она выполняется после готовности пакета и повторно
  только один раз после слияния blocking-багов.
