# UI vNext: parity-контракт интерфейса заданий

Документ относится к `CB-114` и является входным gate для `CB-115`.
Он фиксирует существующее поведение Mini App, которое новый интерфейс обязан
сохранить. Визуальные макеты не могут отменять перечисленные состояния, поля,
права или переходы.

## Правила parity

- Backend DTO остаётся единственным источником permissions, eligibility,
  доступных действий и текущего статуса.
- Новый renderer не вычисляет status transitions и не восстанавливает скрытые
  actions по строковому статусу.
- Idempotency key, expected revision, exact replay и conflict handling
  сохраняются для каждой mutation.
- Каждый экран сохраняет loading, content, empty, error, confirm и success там,
  где эти состояния существуют сейчас.
- `?ui=next` включает только preview нового renderer. URL без параметра остаётся
  legacy runtime до release-gate.

## Экранная карта T: каталог и создание

| ID | Текущий владелец UI | Маршрут | Обязательный контракт |
|---|---|---|---|
| T01 | `showCatalog` / `loadCatalog` | `#/catalog` | Фильтруемый список, empty, загрузка, ошибка, восстановление focus |
| T02 | `showCatalogFilters` | `#/catalog` | Формат, минимальная награда, применить и сбросить фильтры |
| T03 | `showTaskDetail` | `#/tasks/:task_id` | Автор, срок, награда, места, город, описание, критерии, инструкции, public input, материалы |
| T03A | `showActionConfirmation` | `#/tasks/:task_id` | Явное подтверждение принятия, неизменный operation key при retry, conflict outcome |
| T04B | `showTaskRecovery` | `#/compose/tasks/:draft_id?` | Продолжить либо начать заново, stale/needs-edit, retry без потери доступного draft |
| T05 | `showTaskCreation` | `#/compose/tasks/:draft_id?` | Полная форма, зависимые поля, reserve, validation и save retry |
| T06 | `showTaskCreation` preview branch | `#/compose/tasks/:draft_id?` | Безопасный preview, criteria, publish, возврат к редактированию |
| T08 | publish success | `#/compose/tasks/:draft_id?` | Подтверждённый success и возврат к заданиям |

### Поля T05

| Поле | Правило |
|---|---|
| Тип задания | `solo` либо `group`; переключатель синхронизирован с native select |
| Число исполнителей | `1` и disabled для solo; минимум `2` для group; group value восстанавливается |
| Формат | online/offline |
| Город | Обязателен только для offline; combobox выбирает каноническое значение из `/api/v1/task-cities` |
| Категория | Обязательный server-provided option |
| Название | Обязательное значение; вывод только через безопасный text rendering |
| Что нужно сделать | Обязательное значение |
| Критерии приёмки | Обязательное значение |
| Размер | Обязательный server-provided time size |
| Награда за исполнителя | Положительное число; допустимость подтверждает backend |
| Резерв | `performer_slots × reward`, только пояснение, не business authority |
| Срок | Будущее datetime; `aria-invalid`, текстовая ошибка, preview disabled для прошедшего срока |
| Материалы | Необязательный единый текст либо legacy URL, передаётся как `materials` |

Команды `/api/v1/task-creation`: `start`, `start_new`, `save`, `publish`.
Каждая retryable попытка повторяет тот же operation key и body. `save` и
`publish` передают `expected_revision`.

## Экранная карта M: работа, результат, проверка, отмена и спор

| ID | Текущий владелец UI | Маршрут | Обязательный контракт |
|---|---|---|---|
| M01 | `showAssignments` / `loadAssignments` | `#/work` | Сводка активной работы, empty/loading/error, вкладки взятых и созданных |
| M02 | `showTakenAssignments` | `#/work` | Список назначений, status projection, deadline, result summary, focus return |
| M03 | `showAssignmentDetail` | `#/work/:resource_id` | Server-owned `can_submit`, `can_cancel`, `can_dispute`; сроки, result/review/dispute state |
| M04 | `openSubmissionEditor` / `submissionPanel` | `#/work/:resource_id` | Begin/update draft, обязательный result, preview, retry и revision handling |
| M05 | submission preview | `#/work/:resource_id` | Просмотр сохранённой версии и переход к confirm |
| M06 | `showActionConfirmation` | `#/work/:resource_id` | Confirm отправки существующей revision |
| M07 | submission success | `#/work/:resource_id` | Подтверждённая отправка и возврат к назначению |
| M08 | `openCancellationEditor` | `#/work/:resource_id` | Обязательная причина отказа, confirm, retry, освобождение слота только backend-командой |
| M09 | `renderCreatedAssignments` / `loadCreatedReviews` | `#/work` | Созданные задания и очередь review; empty/loading/error, scroll/focus restore |
| M10 | `showOwnedTask` | `#/work/:resource_id` | Статус, слоты, assignees, server-projected cancellation action/status |
| M11 | `showCreatedReview` | `#/work/:resource_id` | Результат, private comment, допустимые server-projected решения |
| M12 | `showActionConfirmation` | `#/work/:resource_id` | Confirm решения review с точным consequence copy |
| M13 | review success | `#/work/:resource_id` | Подтверждённое решение и возврат в очередь |
| M14 | `openDisputeEditor` | `#/work/:resource_id` | Обязательный приватный comment, deadline/availability с backend, confirm и retry |
| M15 | dispute status внутри M03 | `#/work/:resource_id` | Передан модерации; действие повторно не предлагается |

## API-контракт task-flow

| Метод и endpoint | Использование UI |
|---|---|
| `GET /api/v1/tasks` | Каталог доступных заданий |
| `POST /api/v1/tasks/{task_id}/assignments` | Принятие задания |
| `GET/POST /api/v1/task-creation` | Draft, recovery, save, preview и publish |
| `GET /api/v1/task-cities` | Канонический город offline-задания |
| `GET /api/v1/assignments` | Активные назначения исполнителя |
| `GET /api/v1/assignments/{assignment_id}` | Деталь и server-owned actions |
| `POST /api/v1/assignments/{assignment_id}/submission-drafts` | Начало результата |
| `PUT /api/v1/submission-drafts/{draft_id}` | Сохранение версии результата |
| `POST /api/v1/submission-drafts/{draft_id}/confirm` | Отправка на проверку |
| `GET /api/v1/owned-tasks` | Созданные задания и cancellation projection |
| `POST /api/v1/owned-tasks/{task_id}/cancellation` | Отмена либо запрос отмены собственного задания |
| `GET /api/v1/assignment-reviews` | Очередь результатов автора |
| `GET /api/v1/assignment-reviews/{assignment_id}` | Деталь результата и допустимые решения |
| `POST /api/v1/assignment-reviews/{assignment_id}/decision` | Решение автора |
| `POST /api/v1/assignments/{assignment_id}/cancellation` | Отказ исполнителя |
| `POST /api/v1/assignments/{assignment_id}/disputes` | Открытие спора |

## Обязательные состояния для fixtures и визуальной проверки

1. Каталог: content, empty, filter-empty, loading, transport error.
2. Деталь: доступно, permission closed, stale/full slot, network retry.
3. Создание: blank, recovered, stale deadline, offline city, invalid city,
   preview, publish retry, success.
4. Назначение: active submit, submitted waiting, rejected disputable,
   dispute expired, dispute open, cancellation available/unavailable.
5. Submission: new draft, saved revision, update conflict, confirm retry,
   confirmed success.
6. Review: queue empty/content, full/partial/reject where разрешено сервером,
   private comment, conflict, success.
7. Owned task cancellation: immediate cancel, request to active performers,
   pending response, conflict, success.

## Проверочный gate каждого следующего среза

- Ручной URL через `?ui=next` и конкретный hash route.
- Light и dark используют один DOM; geometry diff не превышает 0.5 CSS px.
- На 375×812 и 430×932 отсутствует horizontal overflow.
- Native label/role и visible focus сохранены.
- API request method, path, body, idempotency key и revision совпадают с legacy.
- Legacy URL без `ui=next` остаётся green до отдельного release-gate.
