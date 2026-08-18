# CB-65 — escalation двух manual-first plan reviews

## Причина

Две последовательные проверки manual-first плана вернули
`changes_requested`, поэтому применён
`agents/workflow.yaml#/review_retry_policy`.

## Попытка 1

Обнаружены shared-lock gap existing backup/restore callers, неоднозначная state
schema, schema-changing lifecycle и недоговорённая manual artifact trust
boundary. Owner disposition разрешил изменения existing callers, объявил
manual exact-green-run trust boundary и исключил migration orchestration.

## Попытка 2

Все substantive simplicity/design замечания закрыты. Осталась одна точная
durability boundary: parent directory не был fsync после atomic state replace.

## Consolidated fix

- release-directory rename fsync parent до state reference;
- pending/ready/rollback используют temp same-directory, fsync file, replace,
  fsync parent;
- process runner вызывается только после successful durable pending write;
- один ordering test, без crash framework.

## Следующий и последний review gate

Один post-escalation recheck проверяет только полный актуальный пакет. Новый
обязательный finding после него останавливает planning до owner decision.
Runtime/Jira/Git remote/SSH/server mutations не выполнялись.
