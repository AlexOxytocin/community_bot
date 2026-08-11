# CB-20 — целевой план проверки

| № | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 | Чистая схема, первый ID | Один active administrator и одно audit-событие |
| 2 | Точный повтор того же ID с bootstrap provenance | Успех без второго member/audit |
| 3 | Active admin или target без bootstrap provenance | Conflict, база не меняется |
| 4 | Существующий target любого role/status | Fail-closed без повышения роли |
| 5 | Два конкурентных разных ID | Ровно один administrator, второй получает conflict, без дедлока |
| 6 | Два конкурентных одинаковых ID | Один member/audit, created и idempotent outcomes |
| 7 | Невалидный ID или причина вне allowlist | CLI отклоняет запрос до транзакции |
| 8 | Сбой audit/commit | Полный rollback; безопасный повтор становится winner |
| 9 | Реальный CLI → production Dispatcher `/invite_create` | Администратор создаёт ограниченное hashed приглашение |
| 10 | Новый пользователь через тот же Dispatcher `/start` | Pending registration и receipts через штатный transport |
| 11 | Audit/privacy и member state | Точный safe schema/state, нет Telegram ID, username, token, argv или grant |
| 12 | CLI smoke | `community-bootstrap-admin --help` завершается успешно |

Команды: targeted `pytest` без full regression, `ruff format --check`, `ruff check`, `ty check`,
`uv build`, entry point smoke и `git diff --check`.

Сценарий 9–10 выполняется одним PostgreSQL-тестом на пустой схеме: он вызывает реальный CLI с
подменённым только Bot API transport, затем production `_dispatcher`, извлекает токен из ответа
`/invite_create` и передаёт его новому пользователю через `/start`.
