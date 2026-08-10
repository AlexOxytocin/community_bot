# CB-10 — отчёт о реализации

## Статус

Реализация завершена и готова к независимой финальной проверке. Полная
регрессия намеренно не выполнялась: она выделена в CB-16. Дефекты, найденные во
время разработки и целевой проверки CB-10, исправлены в этой ветке.

## Результат

- добавлена миграция `0006` с долговечными черновиками, неизменяемыми снимками
  заданий и transactional outbox;
- реализован PostgreSQL FSM создания с expected step/revision, несколькими
  черновиками и одним текущим;
- публикация объединяет reserve, task, draft terminal state, audit, outbox и
  Telegram receipt в одной транзакции;
- exact replay и совпадающий повтор business command возвращают сохранённый
  результат без второго резерва; конфликтующая revision отклоняется;
- отмена до появления assignments возвращает точный резерв с нулевым опытом;
  exact replay успешен, новый update после terminal state отклоняется без receipt;
- реализованы приватный список собственных заданий, status filter и keyset;
- статическая eligibility будущего принятия использует authoritative
  `ResolvedLevel` и запрещает self-accept;
- добавлен synthetic aiogram flow без обращения к Bot API;
- синхронизированы README и документы MVP о flow, интерфейсе, данных и тестах.

## Матрица критериев Jira

| Критерий | Реализация | Воспроизводимая проверка |
|---|---|---|
| Недостаточный баланс не создаёт частичный резерв | Economy batch применяется перед task INSERT в общем UoW; исключение откатывает всё | `test_invalid_deadline_and_insufficient_balance_leave_no_publish_effects`, `test_two_public_drafts_compete_for_one_balance` |
| Повтор callback не создаёт второе задание/списание | Exact update receipt и стабильный `publish_command_id`; cross-update retry сверяет terminal draft revision | `test_persistent_preview_publish_replay_and_cancel`, `test_publish_business_retry_concurrent_cancel_and_private_listing`, synthetic Telegram test |
| Прошедший срок отклоняется | Проверка при вводе и повторная проверка перед publish; DB CHECK | unit boundary test, invalid deadline integration test |
| Автор не принимает своё задание | Чистая eligibility-функция и application boundary | `test_acceptance_uses_authoritative_level_and_rejects_creator`, основной publish/cancel test |
| Корректная отмена возвращает точную сумму без опыта | Идемпотентный `task_reward_refunded`, status/audit/outbox/receipt в одном UoW | основной publish/cancel test, concurrent cancel test |
| Перезапуск восстанавливает создание | Источник истины — `task_creation_drafts`, а не память aiogram | основной restart test и synthetic Telegram test |
| Конкурентная публикация сохраняет неотрицательный баланс | Разные command gates сходятся на canonical member row; второй видит committed balance | `test_two_public_drafts_compete_for_one_balance` |

## Дополнительные доказательства

- четыре fault injection после ledger flush, task INSERT, outbox flush и receipt
  flush откатывают всю публикацию; повтор той же команды успешен;
- mutation-first и publish-first расписания catalog gate дают согласованный
  результат и завершаются с timeout без deadlock;
- конкурентная activation product config и publish сериализуются через member
  rows; итог относится к одной полной config version, без смешанного решения;
- stale draft revision, чужой доступ, приватный список и keyset проверены
  напрямую;
- намеренно завышенный legacy `members.level_number=9` не обходит минимальный
  уровень шаблона: решение использует активную product config;
- direct SQL UPDATE/DELETE неизменяемого task отклоняется PostgreSQL;
- direct SQL нарушения origin/reserve и уникальности outbox business key
  отклоняется PostgreSQL; outbox payload проверен на отсутствие input/materials;
- цикл Alembic `0005 → 0006 → 0005 → 0006` выполняется в integration test.

## Исправления после первого final review

- M-001: existing task возвращается только после блокировки terminal draft и
  сверки исходной preview revision; добавлен негативный PostgreSQL-тест;
- M-002: pure acceptance boundary принимает полный `ResolvedLevel` с
  `config_id`, `config_version` и `level_number`;
- M-003: Telegram `/task_cancel` различает draft и task outcome также на exact
  replay; synthetic flow пересоздаёт router/service и повторяет тот же update;
- M-004: добавлены activation/publish race, paused/terminal cancel, stale
  callback, SQL constraints, outbox uniqueness и privacy assertions; после
  повторного review устранён новый receipt для already-cancelled task.

## Целевой прогон перед отчётом

```text
uv run ruff format --check .             — 180 files already formatted
uv run ruff check .                       — успешно
uv run ty check                           — успешно
uv run pytest -q --no-cov \
  tests/unit/test_tasks_domain.py \
  tests/integration/test_task_creation.py — 12 passed, без skip/deselect
uv build                                  — sdist и wheel собраны
uv run community-bot --check              — успешно
uv run community-worker --check           — успешно
git diff --check                          — успешно
```

Миграционный цикл выполнен внутри integration-набора. Полная регрессия не
запускалась. После этого отчёта фиксируется точный staged snapshot для final
review; изменение snapshot потребует повторного gate.
