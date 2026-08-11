# CB-23 — целевой план проверки

| № | Сценарий | Ожидаемый результат |
|---|---|---|
| 1 | Создать отдельную DB и `alembic upgrade 0009` | Чистая поддерживаемая исходная схема |
| 2 | Вставить representative domain chain | Все FK/check/unique constraints revision 0009 принимают fixture |
| 3 | `alembic upgrade 0010` | Upgrade успешен, revision = `0010` |
| 4 | Counts и exact values | Members, ledger, task/assignment/result, `karma_votes`/`karma_vote_history`, `moderation_cases`/`dispute_resolutions` совпадают с manifest |
| 5 | FK joins | Orphan count равен нулю для ledger, assignment, karma history, case и resolution; `moderation_cases.current_resolution_id` указывает на resolution той же case |
| 6 | Outbox backfill | Unpublished=`pending`, published=`materialized`, прежние identity/payload/timestamps сохранены |
| 7 | Operational guards | Constraints/indexes присутствуют, invalid states отклоняются |
| 8 | Повтор `upgrade head` | Без изменений и ошибок; полный oracle проходит повторно |
| 9 | Изоляция | Временная DB удалена в `finally`, порядок suite не влияет |

Команды: один targeted PostgreSQL migration test, `ruff format --check`, `ruff check`, `ty check`, `git diff --check`. Полный `pytest` не запускается.
