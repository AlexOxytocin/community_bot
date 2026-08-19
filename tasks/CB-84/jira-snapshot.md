# CB-84 — снимок Jira для ревью

`community_bot.jira_issue_snapshot.v1`

- Получен через Atlassian Rovo: `2026-08-19`.
- `updated_at`: `2026-08-19T01:13:07.445-0300`.
- Статус: `В работе`.
- Родитель: `CB-48` — «Community Mini App: основной пользовательский цикл поверх общего backend».
- Связи и блокирующие зависимости: отсутствуют (`issuelinks: []`).

## Критерии приёмки

- Владелец `accepted` assignment может указать непустую ограниченную причину и отказаться.
- Существующий `AssignmentService.cancel` атомарно переводит assignment в `cancelled`, освобождает слот и сохраняет прежние outbox, receipt и task aggregate effects.
- Exact replay не создаёт второй persistent effect; несовпадающий replay закрывается.
- Чужое или уже не `accepted` назначение не изменяется.
- Mini App после успеха возвращает пользователя к актуальному списку.
- Production diff не добавляет новые tables, migrations, models, repositories, services, dependencies, frameworks или generic UI abstractions.

## Зафиксированная область

Один actor-native Web endpoint над существующим application owner и одна форма в текущей карточке назначения. Creator/group cancellation, templates/catalog management, community publication, CB-76—CB-80, appeals, sanctions, alerts, cosmetics, pagination, rare admin edge cases и второй экран исключены.
