# Отчёт о реализации CB-32

## Результат

Корневая причина устранена в существующей транзакции moderation: при первом
успешном approval terminal registration conversation удаляется вместе с
изменением статусов заявки и участника, аудитом, receipt и стартовым грантом.
Повторная обработка использует сохранённый receipt и approved context,
восстановленный из заявки даже после допустимого последующего изменения
статуса участника, поэтому новая сущность или отдельный cleanup-сервис не
понадобились.

Для уже одобренных участников migration `0011` удаляет только строки с
`flow_type IN ('registration', 'registration_paused')`. Незавершённый
`profile_edit`, audit events, receipts и прочие данные сохраняются.

## Критерии Jira

| Критерий | Результат |
|---|---|
| Атомарное завершение conversation | Закрыто в `decide_registration` до commit. |
| Replay и concurrent approval | Два approval дают один grant; replay после нового подключения и перевода участника в `paused` не дублирует эффект; state отсутствует. |
| Reject/edit/resubmit | Существующая ветка preview сохранена и проходит targeted tests. |
| Production-composed E2E | Fake Bot + реальный Dispatcher: callback approval → `/profile` → извлечённый callback города → сохранение `Mendoza`. |
| Repair старых состояний | `0010→0011→0011`: stale registration удалён, profile edit/audit/receipts сохранены. |

## Проверки

- Targeted PostgreSQL после consolidated fix: `25 passed`; skip/deselect
  отсутствуют, coverage отключён только для узкого набора.
- Ruff format/check и `ty`: успешно.
- `uv build`: sdist и wheel собраны.
- `community-bot --check`, `community-worker --check` и product-config CLI:
  успешно.
- Alembic head: `0011`; migration cycle входит в targeted tests.
- `git diff --check`: успешно.

Полная регрессия намеренно не повторялась. Один общий прогон всех цепочек
остаётся в CB-29 после слияния всего пакета CB-30…CB-33.
