# CB-11 — точечная заключительная финальная проверка

`community_bot.final_review.verdict.v1`

Status: approved

Проверенный staged tree: `ba94f94a2860b8b4291c52c09bb09e214f5bf11d`.
База: `origin/main=fe05276e9a8bd2b0c67ac895ce864346435f3990`.
Ветка: `task/CB-11`.

## Область заключительной проверки

Владелец 10 августа 2026 года явно выбрал уже реализованное правило M-007:
`approved` и `partially_approved` slot остаётся занятым, replacement разрешён
только после `cancelled`. Датированное решение и разрешение точечной проверки
записаны в final-секции `tasks/CB-11/problem-escalation.md`.

От предыдущего контрольного staged tree изменены только:

- `docs/mvp/06_DATA_MODEL.md`;
- `tasks/CB-11/problem-escalation.md`.

Код, миграция и тесты не менялись. По прямому решению владельца ранее зелёные
targeted gates не перезапускались, а полная регрессия по-прежнему относится к
CB-16.

## Закрытие M-007-DOC

Каноническая модель данных теперь однозначно говорит:

- любая assignment-строка сохраняется как история;
- только `cancelled` освобождает slot и разрешает replacement;
- все остальные состояния защищены partial unique index;
- paid `approved` и `partially_approved` slot остаётся занятым.

Прежнего взаимоисключающего утверждения о незанятом terminal slot больше нет.
Формулировка совпадает с решением владельца, `OCCUPIED_SLOT_STATUSES`, partial
unique index migration `0007` и прошедшим multi-slot PostgreSQL test, где после
оплаты slot 1 следующий участник получает slot 2.

## Итоговая матрица

| Контроль | Результат |
|---|---|
| M-004 exact terminal command | закрыто |
| M-005 durable v2 и stale callback | закрыто |
| M-007 paid slot, общий task cancel gate и каноническая документация | закрыто |
| M-006 targeted evidence matrix | закрыто |
| M-008 `ty` | закрыто |
| Восемь критериев Jira CB-11 | закрыты целевыми доказательствами |
| Telegram privacy/replay/restart | пройдено synthetic fake-session сценарием без внешних отправок |
| Scope/diff/secrets | два ожидаемых документа; diff checks и targeted secret scan чисты |

## Сохранённые независимые доказательства контрольного review

```text
Compose PostgreSQL affected suite                 75 passed, exit 0
Testcontainers tests/integration/test_assignments.py
                                                  14 passed, exit 0
Alembic 0006→0007→0006→0007                       exit 0
ruff format --check .                             exit 0
ruff check .                                      exit 0
ty check                                          exit 0
uv build                                          exit 0, sdist + wheel
community-bot --check / community-worker --check  оба exit 0
```

## Итог

Критических, существенных и незакрытых замечаний нет. M-007-DOC устранён ровно
в разрешённой владельцем области; обязательные барьеры CB-11 закрыты.
