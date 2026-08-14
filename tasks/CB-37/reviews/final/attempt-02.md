# CB-37 - final review, попытка 2

Status: changes_requested

## Подтверждённые исправления первой попытки

- deadline добавлен в request/respond/notification-current;
- `cancelled_creator` атрибутируется автору;
- двойной `callback.answer()` удалён;
- добавлены требуемые конкурентные, deadline, self-cancel и sender-сценарии.

## Обязательные замечания

1. P1: свободная отмена через `TaskService.cancel()` всё ещё возможна после
   deadline до запуска worker.
2. P2: `owned_card()` ищет карточку только среди первых 20 заданий, поэтому
   callback старой карточки перестаёт работать.
3. P2: transport не различает точные причины `obsolete`, хотя
   `resolution_reason` сохранён в БД.
4. P2: немедленная отмена из `request_cancellation()` после освобождения слота
   не создаёт audit-событие `task_cancelled`.

Вердикт независимого проверяющего: `changes_requested`.
