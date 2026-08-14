# CB-37 - final review, попытка 3

Status: changes_requested

## Подтверждённые исправления

- deadline действует для реального callback свободной отмены;
- owned-card читается напрямую и не зависит от top-20;
- `resolution_reason` проходит через БД, outcome, receipt и Telegram;
- немедленная отмена пишет авторский audit;
- исправления первой попытки, миграция, privacy и callback limit сохранены.

## Оставшиеся замечания

1. P1: submit-first concurrency test ожидает старый `TaskError`, хотя новый
   контракт корректно возвращает `TaskCancellationOutcome(status="obsolete",
   reason="work_started")`; контрольный запуск reviewer: `12 passed, 1 failed`.
2. P2: test-plan обещает многоместную гонку после частичного согласия и проверку
   assignment, receipt, refund, audit, reliability и outbox, но текущий тест
   покрывает только однослотовые задания и неполный набор побочных эффектов.

Вердикт независимого проверяющего: `changes_requested`.
