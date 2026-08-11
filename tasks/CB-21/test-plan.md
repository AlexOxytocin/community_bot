# CB-21 — целевой план проверки

| № | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 | Active `/start` | Полное главное меню, без технических UUID |
| 2 | `/tasks`, кнопка и page callback | Только доступные карточки; 11-е задание достижимо, missing либо existing-unavailable cursor перезапускает актуальную первую страницу |
| 3 | `Взять` | Existing acceptance callback создаёт одно assignment; replay без дубля |
| 4 | `/create` и выбор шаблона | Durable draft открыт без ручного UUID |
| 5 | `/balance` | Собственный authoritative balance и безопасная история |
| 6 | `/help` | Короткая актуальная инструкция и команды |
| 7 | Active admin `/admin` | Собственный admin gate; invite отправляется plain-text deep link, registrations/moderation callbacks работают |
| 8 | Member/moderator/pending/unknown `/admin` и callbacks | Одинаковый отказ, без state leak/effects |
| 9 | Старые команды | `/catalog`, `/task_create`, `/my_tasks`, `/invite_create` совместимы |
| 10 | Restart/replay | Durable draft/assignment/invite сохраняются, exact update не дублирует effect |
| 11 | Callback tampering | Invalid/stale UUID даёт safe error без effects |
| 12 | Документация/runtime | Команды и кнопки совпадают |

Основной PostgreSQL E2E использует production `_dispatcher` и fake Bot API, проходит `/start`,
`/tasks`→`Взять`, `/create`→template, `/balance`, `/help`, admin menu→invite/queues и проверяет
persisted effects. Узкие PostgreSQL-сценарии проверяют 11-е задание, stale cursor, лимит активных
назначений, санкцию и полный admin denial. Существующие synthetic Telegram tests подтверждают,
что navigation router не ломает регистрацию, каталог, создание задания и отправку результата.
Дополнительно запускаются Ruff, ty, build и diff-check; full regression не запускается.
