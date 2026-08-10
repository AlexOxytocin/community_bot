# CB-10 — эскалационная контрольная финальная проверка

`community_bot.final_review.verdict.v1`

Status: approved

## Проверенная область

- Свежая Jira `CB-10` прочитана через Atlassian Rovo API без внешних изменений: статус `На проверке`, parent `CB-2`, семь критериев приёмки, завершённые блокеры `CB-7`/`CB-9` и исходящая блокировка `CB-11`.
- Проверены архивы двух непройденных попыток, обновлённый `problem-escalation.md`, одно финальное исправление, согласованность `test-plan.md`/`implementation-report.md` и фактический fix-diff.
- Ветка `task/CB-10` основана на `origin/main=5a174807cd5f3cec47920985dd73acdc211537d4`. Точный проверенный staged tree: `0cc455fc4ae5d401b759231018da648ec96f58c4`.
- Контроль ограничен закрытием остатка M-004 и отсутствием регрессии M-001—M-003. Jira, реализация, Git remote и Telegram во время проверки не изменялись; обновлён только настоящий артефакт.

## Результат эскалационного контроля

### M-004 — закрыто

Terminal cancellation теперь различает три требуемых случая:

- exact replay того же Telegram update завершается через сохранённый receipt и возвращает прежний terminal task;
- новый update после `cancelled` получает `TaskError` до `prepared.apply` и без ledger/audit/outbox/receipt;
- из двух конкурентных разных updates один выполняет cancel, проигравший после блокировки видит `cancelled` и отклоняется без частичных эффектов.

Integration test считает receipts до и после concurrent и sequential веток, подтверждает ровно один refund с `experience_delta=0`, один terminal audit/outbox/receipt и отсутствие новых эффектов у проигравшего и позднего update. Paused owner теперь проверен непосредственно через `TaskService.cancel`; ledger/audit/outbox/receipt до и после отказа совпадают.

Сценарии 17 и 18 в `test-plan.md` непротиворечиво разделяют exact replay и другой update. `implementation-report.md` фиксирует ту же terminal-семантику и фактические доказательства.

### M-001—M-003 — без регрессии

- конфликтующая revision business retry по-прежнему отклоняется, совпадающий retry возвращает один task/reserve;
- acceptance boundary принимает полный authoritative `ResolvedLevel`;
- synthetic Telegram пересоздаёт router/service, exact replay `/task_cancel` успешен, stale callback не создаёт эффектов.

## Критерии Jira

| Критерий | Результат | Доказательство |
|---|---|---|
| Недостаточный баланс не создаёт частичный reserve | Пройден | Общий UoW и полный rollback integration test |
| Повтор callback не создаёт второе задание/резерв | Пройден | Exact replay, business retry identity и conflict-revision barrier |
| Прошедший срок отклоняется | Пройден | Domain/application/DB checks |
| Автор не принимает своё задание | Пройден | Pure boundary с authoritative `ResolvedLevel` |
| Корректная отмена возвращает точную сумму без опыта | Пройден | Один refund, `experience_delta=0`, exact replay и terminal/concurrent barriers |
| Restart восстанавливает draft | Пройден | PostgreSQL draft и пересозданные service/router |
| Concurrent publishes сохраняют неотрицательный balance | Пройден | Два публичных drafts конкурируют за один баланс; успешна одна полная публикация |

## Независимо выполненные проверки

```text
uv run pytest -q --no-cov tests/unit/test_tasks_domain.py \
  tests/integration/test_task_creation.py                 12 passed, exit 0
                                                        0 skipped/deselected
uv run ruff format --check .                            exit 0, 183 files
uv run ruff check .                                     exit 0
uv run ty check                                         exit 0
git diff --cached --check; git diff --check             exit 0
Проверенный staged tree                                 0cc455fc4ae5d401b759231018da648ec96f58c4
```

Targeted-набор также сохраняет доказательства migration cycle, lock serialization, fault rollback, outbox privacy и synthetic aiogram без сетевого Bot API. Полная регрессия MVP намеренно не запускалась: она относится к `CB-16`.

## Секреты, документация и процесс

- Финальный fix не добавляет credentials, session data или реальные Telegram-данные.
- Архивы обеих неудачных попыток и причины эскалации сохранены; одно финальное исправление соответствует принятой процедуре.
- Смысловая документация написана по-русски и согласована с фактической terminal-семантикой.
- Staged snapshot, Jira, Git remote и Telegram не изменялись.

## Итог

Критических, существенных и обязательных незначительных замечаний в контрольной области не осталось. M-001—M-004 закрыты воспроизводимыми targeted-доказательствами; все семь критериев Jira подтверждены. Snapshot готов к дальнейшему процессу слияния.

Остаточный риск полной совместимости собранного MVP остаётся в `CB-16` и не блокирует `CB-10`.
