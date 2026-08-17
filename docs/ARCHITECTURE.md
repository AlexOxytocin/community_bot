# Архитектура

## Текущая граница

Community Mini App строится поверх сохранённого Python-монолита и PostgreSQL. Старый Telegram inbound transport удалён. Новый web UI не получает отдельную бизнес-логику и не создаёт второй backend.

```text
Telegram Mini App / browser
          |
versioned HTTPS API
          |
application use cases
          |
domain + PostgreSQL UoW
          |
ledger / audit / outbox
          |
notification worker -> Telegram Bot API
```

## Слои

1. `domain` содержит состояния, значения и инварианты без FastAPI, aiogram и SQLAlchemy.
2. `application` координирует права, operation identity, транзакции и доменные операции.
3. `infrastructure` реализует PostgreSQL repositories/UoW, outbox, observability и внешние sender-адаптеры.
4. Будущий HTTP transport проверяет Telegram auth proof, создаёт внутренний actor context и вызывает application.
5. Worker обрабатывает дедлайны и отправляет только короткие allowlisted-уведомления.

## Неизменяемые свойства

- PostgreSQL — источник состояния, прав и допустимых переходов.
- `account_transactions` — append-only источник кредитов и опыта; кэши сверяются с ledger.
- Доменное изменение, audit, receipt и outbox фиксируются одной транзакцией.
- Exact replay возвращает прежний outcome, конфликт payload не создаёт эффект.
- Исторические Alembic-миграции не переписываются.
- Секреты и Telegram sessions находятся вне репозитория.
- Test-run строки остаются изолированы от обычных запросов и получателей уведомлений.

Стек и будущая web-граница описаны в [TECH_STACK.md](mvp/TECH_STACK.md), решение об отказе от старого UI — в [ADR-0016](adr/0016-mini-app-only-runtime.md).
