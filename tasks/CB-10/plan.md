# CB-10 — план создания задания и атомарного резерва

## Цель

Дать активному участнику возобновляемый путь от выбора доступного шаблона до
preview и публикации задания, при которой задание, полный резерв, audit, outbox
и Telegram receipt фиксируются одной транзакцией. Повтор, ошибка и конкуренция
не создают частичных эффектов.

## Уровень процесса

Уровень 3: новая схема заданий/черновиков/outbox, композиция каталога и
экономики, persistent FSM и конкурентные публикации. Нужны контекст, этот план,
целевой test-plan, независимый plan review, полная реализация, один targeted
контур, implementation report и один final review готового staged diff. Новый
ADR не нужен: решение следует ADR-0005, D-007 и уже принятой UoW-композиции.

## Область

- доменные состояния черновика и задания, preview и проверки публикации;
- PostgreSQL `task_creation_drafts`, `tasks`, `outbox_events`, ограничения и
  миграционный цикл `0006`;
- application API старта/заполнения/preview/publish/list/cancel и eligibility
  для будущего принятия;
- атомарная композиция exact Telegram receipt, ledger reserve/refund, task,
  audit и outbox;
- Telegram-команды и callbacks создания, preview, публикации, отмены и списка;
- синхронизация модели данных, flow/interface и тестовой документации.

## Вне области

- assignment, принятие места, отправка/проверка результата и settlement — CB-11;
- community-card и административный reviewer flow;
- фактическая доставка outbox и уведомлений;
- лидерборд, споры, алерты и полная регрессия — следующие задачи/CB-16.

## Данные

### `task_creation_drafts`

Черновик: UUID, creator FK, template FK,
`input_payload_json`, `deadline_at`, выбранный `format`, `city`,
`materials_json`, `performer_slots`, `current_step`, optimistic `revision`,
`is_current`, стабильный `publish_command_id`, timestamps. Статусы шага:
`input → deadline → format → materials → slots → preview → published`.

У автора может быть несколько незавершённых черновиков с разными command ID,
но partial unique разрешает только один `is_current=true`. Создание нового
черновика атомарно снимает current с прежнего; старый остаётся возобновляемым.
`/task_create` без аргумента открывает current, `/task_create <template_id>`
создаёт новый, `/task_resume <draft_id>` выбирает принадлежащий actor draft.
Publish callback содержит draft UUID и поэтому остаётся валиден для любого
preview draft, даже если current переключён.

Каждый мутирующий шаг содержит `expected_step` и `expected_revision`. Несовпадение
даёт stale callback без изменения. `/cancel` удаляет только незавершённый
черновик. После commit новый процесс читает ту же строку и продолжает с
`current_step`; состояние aiogram в памяти не является источником истины.
При успешном publish draft получает `published`, `is_current=false`; если он был
current, current остаётся пустым до явного `/task_resume` или нового create.

### `tasks`

Модель соответствует `06_DATA_MODEL.md`: `origin`, точный `template_id`,
`template_version`, creator/category, неизменяемый снимок title/description/
criteria/input/materials/reward/minimum level/format/deadline/slots/safety,
`reserved_credit_total`, status, published/cancelled timestamps и
`publish_command_id UNIQUE`.

CB-10 создаёт только `origin=member`, `creator_id NOT NULL`,
`reserved_credit_total = reward * slots`, статус `published|cancelled`.
PostgreSQL CHECK запрещает отрицательные суммы, прошлый/равный моменту публикации
deadline, slots вне `1..10`, несовместимые origin/creator/reserve и изменение
неизменяемого снимка после INSERT. До assignment отмена меняет только status и
cancelled_at; DELETE опубликованного задания запрещён trigger.

### `outbox_events`

UUID, `event_type`, `aggregate_type`, `aggregate_id`, JSON payload,
`business_key UNIQUE`, created/published timestamps. В CB-10 записываются
`task.published` и `task.cancelled`. Payload содержит только task/member UUID и
публичные поля, без приватного input/materials.

## Проверки черновика и preview

Старт с UUID шаблона создаёт новый current draft, старт без UUID возвращает
current, resume выбирает существующий draft автора. Каждый
последующий шаг валидирует данные до записи:

- input — через `CatalogService.for_creation` по точной активной версии;
- deadline — timezone-aware UTC и строго позже DB `transaction_timestamp()`;
- format — точный `online|offline`, для template `any` допустим любой; для
  fixed format только совпадение; для offline требуется непустой city;
- materials — закрытый JSON object в пределах размера;
- slots — `1..template.maximum_performers`;
- preview — только после заполнения всех полей, показывает reward per slot,
  slots, полный резерв, deadline и format, но не меняет баланс.

Publish повторно проверяет active member, текущий level, active category/template,
input schema, deadline, format и slots после всех блокировок. Для этого task UoW
получает публичные caller-owned primitives `acquire_catalog_mutation_gate()` и
`template_for_creation_locked(...)`: они используют ту же AsyncSession и не
открывают вложенную транзакцию. Удерживаемый до commit catalog gate не позволяет
admin deactivate или выпустить новую version между revalidation и task INSERT.

## Единый порядок блокировок и публикация

Предварительное неблокирующее чтение черновика используется только для
построения команд; решение принимается после блокировок. Есть два явных
совместимых пути, без фиктивной economy-команды.

Обычная draft mutation:

1. update gate → exact receipt;
2. task identity gate по Telegram ID;
3. для start/template revalidation — catalog mutation gate, затем canonical
   member lock и caller-owned catalog read; для остальных шагов этот gate не
   нужен;
4. draft row lock, expected step/revision, изменение, audit/receipt и commit.

Publish:

1. advisory update gate по `update_id`;
2. exact receipt; полный replay возвращается немедленно;
3. advisory identity gate по Telegram user ID;
4. advisory task-command gate по `publish_command_id`;
5. catalog mutation gate;
6. economy idempotency gates в каноническом порядке;
7. creator/member rows в каноническом UUID-порядке через
   `EconomyMutationPort.prepare_batch`;
8. draft row lock;
9. caller-owned revalidation actor/template/category/schema/level и всех полей;
10. apply economy effect, INSERT task, audit, outbox и complete receipt;
11. один commit.

Cancel не ждёт catalog gate: update → receipt → identity → task-command gate →
economy gates → canonical members → task row → checks/effects → commit.

Ни публикация, ни отмена не блокируют draft/task до economy gates/member rows.
Catalog admin уже использует `catalog gate → member/version rows`; publish
использует тот же префикс. CB-11 обязана использовать порядок `task command →
economy → members → task → assignment`, что исключает инверсию с отменой.

Гонка publish с catalog mutation проверяется в двух принудительных расписаниях
с test hook/barrier и timeout:

- mutation-first: admin deactivate или new-version удерживает gate и commit;
  publish затем видит неактивную exact version и полностью откатывает reserve,
  task, task-audit/outbox/receipt;
- publish-first: publish удерживает gate до commit, фиксирует task и неизменяемый
  snapshot старой exact version; admin mutation затем также commit. Оба эффекта
  допустимы, опубликованный task не меняется.

В обоих расписаниях нет deadlock. Отдельно activation новой product config
сериализуется canonical member lock: publish разрешает уровень внутри того же
UoW через `resolve_member_level`, поэтому решение соответствует одной полностью
зафиксированной config version, а не stale cache.

### Publish

`reserve_reward` использует стабильный key
`task_publish:{publish_command_id}:reserve`, сумму `reward * slots` и нулевой
опыт. После `prepare_batch` блокируется draft, сверяются `expected_revision` и
`preview`, затем в одной транзакции применяются reserve, task INSERT, перевод
draft в `published`, audit, outbox и receipt.

Другой update с тем же `publish_command_id` получает существующее task по UNIQUE
и сохранённый ledger outcome; несовпадающий payload/revision отклоняется как
idempotency conflict. Недостаточный баланс откатывает task/outbox/audit/receipt,
ledger и cache целиком.

### Конкурентные публикации

Два preview draft одного creator создаются последовательно только через API и
имеют разные publish keys. Их callbacks берут разные economy gates, но оба затем
ждут одну creator row. Первый commit уменьшает cache; второй проверяет уже новый
баланс. При недостатке средств он полностью откатывается. Доступный баланс не
становится отрицательным; частичного резерва нет.

## Отмена опубликованного задания

В области CB-10 автор может отменить своё `published` задание: это единственное
нетерминальное состояние task, которое создаёт текущая миграция, а assignments
ещё не существуют.
Команда использует стабильный key `task_cancel:{task_id}:refund`, готовит
`refund_reward` на точный `reserved_credit_total`, затем блокирует task и
проверяет owner/status. Одной транзакцией применяются
refund с `experience_delta=0`, status `cancelled`, audit, outbox и receipt.

Exact replay возвращает тот же outcome; другой callback после отмены не создаёт
второй refund. Чужой, paused или неактивный actor и уже cancelled task
отклоняются без эффекта. CB-11 до включения принятия расширяет эту транзакционную
границу блокировкой assignments и проверяет гонку accept/cancel.

## Собственные задания и запрет self-accept

`list_owned_tasks` возвращает только задания actor, с keyset по
`(created_at, id)`, фильтром status и без приватных данных других участников.
Публичная чистая функция
`validate_acceptance_actor(task_snapshot, actor, resolved_level)` проверяет
active actor, `status=published`, `resolved_level.level_number >= minimum_level`
и явно отклоняет `creator_id == actor.id`. `ResolvedLevel` содержит identity
точной active product config; cached `members.level_number` не читается. Функция
не заявляет свободный слот и не открывает UoW. CB-11 получает actor и
`ResolvedLevel` в caller-owned UoW, вызывает функцию после task row lock, а затем
добавляет assignment count/row locks.

## Telegram

- `/task_create` — возобновить current;
- `/task_create <template_id>` — создать новый current;
- `/task_resume <draft-id>` — выбрать сохранённый черновик;
- последовательные ответы сохраняются в PostgreSQL FSM;
- `/task_preview` — карточка и callback `task:publish:<draft-id>:<revision>`;
- `/my_tasks` — собственные задания;
- `/task_cancel <task-id>` — отмена черновика или опубликованного задания.

Callback укладывается в 64 bytes. Invalid/replay/stale callbacks и restart
проверяются synthetic aiogram без сетевого Bot API.

## Изменяемые компоненты

- `domain/tasks.py`, `application/tasks.py`, `infrastructure/db/tasks.py`;
- `database.py`, `models.py`, Telegram task router;
- миграция `0006`, документация MVP и `tasks/CB-10/*`;
- unit, PostgreSQL integration и synthetic Telegram tests.

## Критерии готовности

- закрыты семь Jira AC и все сценарии test-plan;
- empty DB и `0005→0006→0005→0006` проходят;
- targeted unit/PostgreSQL/Telegram/UoW tests без skip/deselect;
- Ruff, ty, diff/secret scan чисты;
- implementation report содержит матрицу AC → результат → тест;
- final review готового staged diff имеет `Status: approved`;
- полная регрессия не запускается и остаётся в CB-16.
