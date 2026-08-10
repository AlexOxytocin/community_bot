# CB-11 — план принятия, выполнения и подтверждения задания

## Цель

Реализовать один сквозной и атомарный цикл свободного слота:
`accept → submit version(s) → full/partial/reject/dispute`, включая отказ,
истечение, автоподтверждение и агрегирование многоместного задания. Повтор и
конкуренция не должны дублировать место, выплату, возврат, audit, outbox или
receipt.

## Уровень и границы

Уровень 3. Нужны migration `0007`, домен, application/UoW, Telegram transport,
PostgreSQL integration и synthetic aiogram. Новый ADR не требуется: транзакции
следуют ADR-0005/0006 и принятым D-013—D-015.

В CB-11 входят member-origin assignments, а generic settlement сразу различает
`origin=member|community`. Создание community task и смена независимого reviewer
не входят. Открытие спора переводит слот в `disputed` без расчёта; решение спора
и санкции — CB-13. Доставка outbox/reminders — CB-15. Карма, статистика,
interaction alerts и leaderboard — CB-12. Полная регрессия — CB-16.

## Схема `0007`

### `assignments`

- UUID, task/performer FK, `slot_number`, status, accepted/cancelled/submitted/
  reviewed/approved timestamps;
- `review_deadline_at`, `reject_dispute_deadline_at`, reviewer generation;
- immutable acceptance identity и mutable lifecycle fields;
- `UNIQUE(task_id, performer_id)` сохраняет одну историческую попытку участника
  на task. Slot защищает partial unique index по `(task_id, slot_number)` только
  для занимающих состояний `accepted|submitted|rejected_pending_dispute|disputed|
  reviewer_required`; terminal/cancelled история остаётся append-only, а
  освобождённый slot получает новую assignment-строку;
- статусы: `accepted`, `submitted`, `rejected_pending_dispute`, `disputed`,
  `approved`, `partially_approved`, `rejected`, `cancelled`, `no_show`,
  `reviewer_required`;
- terminal decision command/outcome сохраняются для business replay.

### `assignment_result_versions`

Append-only UUID, assignment FK, последовательная version, payload JSONB,
submit command ID UNIQUE, timestamp; `UNIQUE(assignment_id, version)`. Trigger
запрещает UPDATE/DELETE. Первая версия фиксирует review deadline; следующие его
не продлевают. Первая версия разрешена из `accepted`, следующие — из `submitted`
до terminal decision. Каждая новая версия выбирается текущей. Task/assignment
lock сериализует номера версий; одинаковый submit command возвращает сохранённую
версию, а другой payload под тем же command ID отклоняется.

### `assignment_disputes`

Минимальный durable handoff для CB-13: UUID, `UNIQUE(assignment_id)`, performer
FK, приватный нормализованный comment, open command ID UNIQUE и `opened_at`.
Строка неизменяема; UPDATE/DELETE запрещены trigger. Outbox и логи содержат
только dispute UUID/assignment UUID и не содержат comment.

### `reliability_events`

Append-only событие `accepted|cancelled_performer|cancelled_creator|no_show|
approved|partially_approved|rejected`, assignment FK, optional supersedes FK,
reason/actor/timestamp. Поздняя коррекция no-show добавит новое событие в CB-12/
CB-13, не изменяя старое.

`account_transactions` получает nullable настоящие FK `task_id` и
`assignment_id`; settlement-команды обязаны заполнять их через application
metadata. Task status CHECK расширяется до `published`, `settling`, `expired`,
`partially_completed`, `completed`, `cancelled`; snapshot trigger по-прежнему
разрешает только lifecycle fields.

### Product config v2

Строгая schema-v1 дополняется объектом
`assignment_policy.maximum_active_assignments` (`int >= 1`). Новый неизменяемый
`config/product-config.v2.json` имеет `config_version=2` и значение `3`; v1-файл
не изменяется. Поле входит в canonical payload/hash и публичные config snapshots.
Accept читает exact active snapshot после config gate. Активация v2 и rollback
на v1 меняют только последующие accept decisions и не отменяют существующие
assignments. Для `config_version=1` исходный документ без поля сохраняет прежнюю
canonical projection и прежний content hash; runtime snapshot вычисляет
effective default `3`, не переписывая payload. Для `config_version>=2` поле
обязательно и входит в payload/hash. Поэтому повторный ingest неизменённого v1
остаётся replay, а v2 получает отдельную identity.

## Состояния и переходы

- accept: только active actor, published task, future deadline, authoritative
  `ResolvedLevel`, не creator, один assignment на performer, свободный slot и
  лимит active assignments из active product config: стартовое значение `3`,
  поле `assignment_policy.maximum_active_assignments`; изменение действует на
  новые accept decisions и не отменяет существующие assignments;
- performer cancel: только `accepted`, обязательная причина и responsibility;
  до submit. Возврат слота задания участника выполняется только если весь task
  отменяется/истекает, а обычный отказ исполнителя освобождает slot без refund
  резерва — новый исполнитель может занять тот же slot;
- submit: только owner assignment в `accepted|submitted` и строго до task deadline;
  payload валидируется по exact historical result schema; version append-only;
- full/partial/reject: только creator member для member task. Full/partial сразу
  settlement; partial допустим при reward ≥2 и равен `ceil(reward/2)`;
- reject: открывает `[rejected_at, rejected_at+24h)` без выплаты/возврата;
- dispute: только performer в этом полуинтервале, атомарно вставляет immutable
  `assignment_disputes` с приватным comment, переводит в `disputed` и
  замораживает settlement до CB-13;
- review finalizer: на `review_deadline_at` один раз full-autoconfirm, если слот
  всё ещё `submitted`;
- rejection finalizer: на границе 24h переводит в `rejected` и возвращает
  полный per-slot reserve author для member task;
- deadline finalizer: незанятые slots закрывает логически; `accepted` получает
  no-show и per-slot refund, `submitted` остаётся в review.

## Атомарная экономика

Member full settlement создаёт один `task_reward_earned` исполнителю на полную
награду; автор уже заплатил reserve при публикации, второго debit нет. Partial
создаёт `partial_task_reward` исполнителю и `task_reward_refunded` автору на
остаток. Rejected/no-show создаёт только полный per-slot refund автору.
Community full/partial создаёт единственный `community_task_reward` на
фактическую сумму; reject/no-show ничего не выпускает. Experience всегда равен
фактической выплате, refund даёт ноль опыта.

Публичный `EconomyCommand` получает optional `task_id` и `assignment_id`, а
`EconomyMutationResult` возвращает их. Correlation входит в canonical
payload/hash и пишется сразу при append, поэтому тот же idempotency key с иными
UUID конфликтует. Для прежних команд оба поля `None`, их исторический hash/replay
сохраняется. Migration добавляет nullable настоящие FK в
`account_transactions`; settlement/refund CB-11 всегда передаёт оба UUID.

Business keys основаны на assignment и terminal outcome. Same command replay
возвращает сохранённый outcome; новый command после terminal state отклоняется
без receipt/effect. Failure до commit откатывает assignment, ledger/cache,
reliability event, task aggregate, audit, outbox и receipt.

## Блокировки

Все task mutations используют общий порядок:

1. Telegram update gate и exact receipt (для scheduler — stable finalizer gate);
2. Telegram identity gate для пользовательской команды;
3. task command gate по task UUID;
4. economy idempotency gates, если есть settlement/refund;
5. canonical member rows;
6. task row;
7. assignment rows по canonical UUID/slot;
8. result/reliability/audit/outbox/receipt и один commit.

Accept и cancel task разделяют task command gate. Task lock сериализует count и
выбор минимального свободного slot, поэтому два пользователя не занимают
последнее место. Submit/deadline и decision/cancel/finalizer используют тот же
префикс и затем один assignment row, исключая mixed outcome и deadlock.

## Агрегат задания

Task aggregate пересчитывается только из заблокированных slots:

- пока возможны accept/submission/review — `published`;
- при deadline finalization — `settling`;
- все slots без выплаты → `expired`;
- есть terminal paid slot и есть unpaid terminal slot → `partially_completed`;
- все фактически занятые terminal slots оплачены и свободных slots больше нет →
  `completed`.

Переход выполняется в той же транзакции, что terminal slot. Для задания
участника сумма всех payout + refund по slots должна ровно исчерпать исходный
reserve; это проверяется integration oracle.

## Telegram

- callback `task:accept:<task>`;
- `/my_assignments`, `/assignment_cancel <id> <reason>`;
- `/assignment_submit <id>` запускает persistent input flow и preview;
- callback submit фиксирует новую version;
- author card предлагает full/partial/reject с expected assignment state;
- `/assignment_dispute <id> <comment>` открывает спор в защищённом окне.

Callbacks ≤64 bytes. Exact replay, stale callback и restart проверяются без
сетевого Bot API. Пользователь видит понятный следующий шаг; технические errors
остаются английскими.

## Документация

Синхронизировать README, flows, bot interface, data model и общий test plan.
Implementation report строит матрицу восьми Jira AC. Полный regression не
запускается.

## Готовность

- все восемь Jira AC и целевой test-plan закрыты;
- migration empty/`0006↔0007`, targeted PostgreSQL/Telegram tests без skip;
- Ruff, ty, build, entrypoints, diff/link/secret checks зелёные;
- один final review готового staged diff — `approved`, затем PR/CI/merge/main и
  Jira `Готово`.
