# CB-30 — целевая проверка непрерывных Telegram-цепочек

## Правило E2E

Production `_dispatcher` работает с PostgreSQL и fake Bot API. После исходного
`/start` или кнопки главного меню каждый следующий пользовательский text/callback
извлекается только из реально захваченного предыдущего ответа. Тест не импортирует
новые callback-константы, не читает UUID/revision из БД для следующего input и не
собирает callback вручную. БД разрешена только для начальной тестовой когорты,
управления временем/worker и итоговых инвариантов.

## Сценарии

1. Active member принимает member-задачу из видимой карточки и получает действия
   без UUID.
2. Exact replay accept не создаёт второе назначение, receipt или outbox.
3. Исполнитель после restart открывает `Мои задания`, начинает результат,
   отправляет обычный текст, подтверждает preview и видит submitted.
4. Невладелец не может применить перехваченный submit/cancel callback; эффектов
   нет.
5. Автор из своей карточки видит submitted-выполнение и подтверждает full;
   награда, reserve и aggregate task согласованы.
6. Повторить отдельные цепочки partial и reject; partial округляется по текущему
   правилу, reject сохраняет резерв и открывает только 24-часовой dispute path.
7. Исполнитель вводит комментарий спора обычным текстом, подтверждает его и после
   restart видит открытый спор без утечки комментария.
8. Moderator из очереди получает case callback из ответа и применяет разрешённое
   решение; forbidden administrator-only решение отклоняется без эффектов.
9. Performer либо creator как active case party получает кнопку запроса и
   открывает appeal в `[resolved_at, resolved_at + 7d)`. Затем другой
   conflict-free active administrator получает решение из собственной очереди;
   оно атомарно отменяет прежний ledger/reliability effect и применяет новый.
   Outsider и administrator, применивший первое конфликтное решение, отклоняются.
10. Администратор применяет и отменяет видимую ограниченную sanction; member и
    moderator не могут применить administrator-only вариант.
11. После превышения interaction threshold администратор открывает alert из
    меню и выбирает legitimate/monitor/penalty. Penalty ограничен доступным
    незарезервированным балансом и exact replay не удваивает списание.
12. Administrator из выданной карточки оплаченного назначения открывает fraud
    case. Member/moderator не видят действие; insufficient reversible balance
    откатывает case/audit/receipt, replay не дублирует reversal.
13. Administrator с `karma_review` из карточки участника читает raw karma;
    приватный ответ содержит только требуемые author/comment/history, чтение
    аудируется. Exclude и restore точной revision берутся из этого ответа.
    Member/moderator, stale revision и перехваченный callback не дают данных и
    эффектов.
14. Member catalog возвращает безопасные карточки. Оценщик выбирает участника и
    karma value кнопками, вводит комментарий текстом, подтверждает; self,
    ineligible и запрещённая роль не получают эффекта.
15. Member создаёт задачу без JSON/ISO/UUID: шаблон из каталога, обычное описание
    и материалы, кнопки срока/формата/слотов, preview и publish. Резерв создаётся
    один раз.
16. Active administrator тем же видимым потоком выбирает другого active
    administrator reviewer и публикует community task без личного резерва;
    member, creator-as-reviewer и performer-as-reviewer отклоняются.
17. Только сохранённый reviewer проверяет community result. Неактивный/conflicted
    reviewer переводит assignment в `reviewer_required`; видимая replacement
    команда назначает независимого reviewer с принятыми deadline semantics.
18. Performer принимает community task и проходит submit -> full. Итог содержит
    только `community_task_reward`, без member reserve/refund.
19. Community reject -> dispute -> resolution/appeal проходит допустимую ветку;
    reversal не создаёт отрицательный резерв автора.
20. Deadline worker создаёт no-show по принятому member assignment. После
    повторного входа пользователь видит итоговый статус, авторский резерв
    возвращён, paid-slot retention не нарушен. При ограничении пачки старое
    `settling`-задание без `accepted` assignment не блокирует более новое
    просроченное задание с `accepted` assignment.
21. `/cancel` по очереди отменяет task, result, dispute и karma text flow, не
    затрагивая чужой flow и не оставляя недостижимого текущего состояния.
22. Collision oracle: у member остаётся незавершённый task draft, затем он
    начинает result, dispute и karma flow. Каждый обычный текст попадает только
    владельцу из `conversation_states`; старый task draft не меняется. После
    restart owner сохраняется, switch детерминирован, registration/profile-edit
    нельзя вытеснить без явной отмены.
23. Перехваченные stale callback, неверная роль, paused member и concurrent
    повтор одного действия завершаются безопасно без второго ledger/audit/outbox.
24. Карточки и справка не содержат UUID, revision, JSON-команд и приватных данных;
    callback payload укладывается в 64 байта.
25. Migration `0011 -> 0012 -> 0011 -> 0012` проходит; legacy draft получает
    `origin=member`, legacy task сохраняется, community task сохраняет
    `created_by_admin_id`/`reviewer_admin_id`, published tasks/assignments/ledger
    не меняются.
26. Targeted suite проходит без skip/deselect, затем Ruff format/check, ty,
    `uv build`, bot/worker/bootstrap `--check`, diff-check и secret scan.

Полная регрессия всех модулей и реальный Telegram-коннектор запускаются один раз
в CB-29 после слияния CB-30 и остальных regression Bugs.
