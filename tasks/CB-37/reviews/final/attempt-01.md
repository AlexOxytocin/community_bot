# CB-37 - final review, попытка 1

Status: changes_requested

## Обязательные замечания

1. P1: request/respond и проверка актуальности уведомления не учитывали deadline.
2. P2: `cancelled_creator` ошибочно записывал исполнителя как actor.
3. P2: при освобождении слота между вопросом и подтверждением transport сообщал
   «запрос отправлен», хотя задание уже отменялось немедленно.
4. P2: ошибки отмены скрывали фактические причины, а handler мог дважды вызвать
   `callback.answer()`.
5. P2: отсутствовали тесты обоих порядков последнего согласия и
   `confirm_submission_draft`, post-deadline response, self-cancel и callback из
   фактического notification sender.

Все замечания были собраны в один пакет и исправлены перед попыткой 2.
