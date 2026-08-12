# Ежедневный checklist пилота Community Bot

Дата и время UTC:

Проверяющий:

## Release и состояние

- Reviewed commit:
- Immutable image digest:
- Alembic revision (`0011` ожидается):
- `postgres`: `healthy|unhealthy`
- `community-worker`: `healthy|unhealthy`
- `community-bot`: `healthy|unhealthy`
- Свежесть heartbeat:

## Ошибки и очереди

- Новые очищенные ошибки по техническим кодам:
- Terminal `failed` outbox:
- Terminal `failed` notifications:
- Повторы Telegram updates без дублированного доменного эффекта:
- Открытые Jira Bugs с label `cb16-regression` по severity:

Не копировать сюда Telegram payload, токены, invite-коды, комментарии кармы,
материалы спора, meeting notes или доказательства выполнения.

## Экономика и восстановление

- Ledger/cache mismatch count (`0` ожидается):
- Время последнего успешного backup UTC:
- Возраст backup (`<=24h` ожидается):
- Последний restore drill UTC и длительность (`<=4h` ожидается):
- Остаточный риск same-host backup принят и не изменился: `да|нет`

## Продуктовые агрегаты

Период `[from,to)` UTC:

- `task_fill_rate`:
- `assignment_completion_rate`:
- `repeat_action_rate`:
- Регистрации и завершённый onboarding:
- Уникальные оплаченные пары:
- Споры и отмены:
- Открытые/закрытые interaction alerts по исходам:
- Задания сообщества и выпущенные по ним кредиты:

Использовать только `community_bot.pilot_metrics.v1`. Не добавлять ручные
списки участников или расшифровку малых bucket.

## Ручные решения

- Нужна встреча или модерационное действие:
- Jira-ключ и безопасное основание:
- Ответственный и срок:

## Итог дня

Решение: `continue|pause|stop`

Причина:

Следующий конкретный шаг:
