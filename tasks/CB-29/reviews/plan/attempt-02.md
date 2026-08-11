# CB-29 — архив второй проверки плана

Status: changes_requested

Файл восстановлен из результата независимой повторной проверки, полученного до
создания обязательного каталога архива. Ниже сохранён полный набор активных
замечаний второй попытки.

## Закрыто

- Полный Jira discovery/reconciliation contract.
- Partial settlement, reject-only dispute, appeal/reversal и karma eligibility.

## Осталось исправить

1. Stop point реального Telegram не соответствовал фактическому UI: кнопка
   `Создать приглашение` сразу создаёт запись без confirm, а выбор task template
   уже создаёт durable draft. Без отдельного поручения smoke должен останавливаться
   до первого durable-write действия.
2. Активная сводка плана всё ещё обещала dispute window для full/partial/reject.
   Требовалось зафиксировать немедленный full/partial, reject-only интервал
   `[rejected_at, rejected_at+24h)` и appeal
   `[resolved_at, resolved_at+7d)`.

## Итог попытки

После второй непройденной проверки требовались архив попыток,
`problem-escalation.md` и одно консолидированное исправление.
