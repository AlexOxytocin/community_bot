# CB-20 — план исправления bootstrap первого администратора

## Цель

Добавить в существующий image отдельную CLI-команду, которая атомарно создаёт первого active
administrator на чистой базе, повторяется без эффекта для того же Telegram ID и закрывается с
ошибкой для любого конфликтующего состояния.

## Контракт

1. Оператор передаёт положительный PostgreSQL `BIGINT` `telegram_user_id` и одну из двух
   allowlisted причин: `initial_install` или `clean_recovery`; произвольный текст запрещён.
2. В транзакции сначала берётся `pg_advisory_xact_lock` с фиксированным namespace
   `initial_administrator_bootstrap`.
3. Если active administrator отсутствует и identity ещё не существует, создаётся один active
   administrator с полным набором принятых административных permissions.
4. Создаваемое состояние детерминировано: `display_name=Administrator`, `timezone=UTC`,
   `role=administrator`, `status=active`, `approved_at` установлен, caches равны нулю, permissions
   равны `interaction_review`, `karma_review`, `member_read`; starting grant отсутствует.
5. В той же транзакции добавляется системное audit-событие: `actor_member_id=NULL`,
   `action=initial_administrator_bootstrapped`, `entity_type=member`, `entity_id` равен внутреннему
   UUID, `reason` равен allowlisted коду, `before_json=NULL`, `after_json` содержит только роль,
   статус и permissions. Telegram ID, username, CLI argv и токены не сохраняются и не логируются.
6. Идемпотентный успех разрешён только если найден тот же active administrator и его точное
   bootstrap audit-событие. Любой active administrator или target member любого role/status без
   такого provenance приводит к conflict без изменений.
7. Порядок операции: lock → чтение bootstrap outcome, active administrators и target → вставка
   member → вставка audit → один commit. Любой сбой откатывает обе записи и освобождает lock.
8. Два конкурентных bootstrap получают сериализованный результат: один winner, второй idempotent
   только для того же ID либо conflict для другого.

## Изменения

- прикладной сервис и узкий Unit of Work для bootstrap;
- PostgreSQL-адаптер и CLI entry point `community-bootstrap-admin`;
- один сквозной PostgreSQL CLI → production Dispatcher → invite → `/start` тест и отдельные
  concurrency/fault targeted tests;
- точная команда первого запуска в `docs/operations/PILOT_RUNBOOK.md`;
- отчёт реализации и одна финальная проверка готового исправления.

## Вне области

- обычное повышение участников до администратора;
- выдача стартовых кредитов bootstrap-администратору;
- изменение регистрации, экономики или продуктовой конфигурации;
- полная регрессия MVP в ветке бага.

## Готовность

Все критерии Jira имеют прямое доказательство; targeted tests, Ruff, ty, build и entry point
успешны; секретоподобные данные отсутствуют; `final-review.md` имеет `Status: approved`.
