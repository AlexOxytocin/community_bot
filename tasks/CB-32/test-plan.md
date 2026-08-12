# План проверок CB-32

1. После первого approval строка `conversation_states` отсутствует, участник
   активен, заявка одобрена, стартовый грант ровно один.
2. Два конкурентных approval завершаются одинаковым результатом, оставляют
   одну транзакцию гранта и не оставляют conversation state.
3. Exact replay после нового подключения и допустимого последующего перевода
   одобренного участника в `paused` возвращает сохранённый результат и ничего
   не дублирует.
4. Reject сохраняет редактируемый preview, после reopen/resubmit последующий
   approval закрывает registration conversation.
5. Production-composed Dispatcher и fake Bot проходят output-driven цепочку:
   очередь → callback approval → `/profile` → callback редактирования города →
   новое значение; значение сохраняется без сообщения о чужом диалоге.
6. Миграция `0010→0011` удаляет только старые approved registration states,
   сохраняет profile-edit state, audit events и processed receipts; повторный
   upgrade идемпотентен.
7. Targeted PostgreSQL tests, Ruff, ty, migration cycle, build и entrypoints
   проходят. Full regression не запускается до CB-29.
