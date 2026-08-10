# CB-8 — повторное ревью плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- актуальные `tasks/CB-8/plan.md`, `plan-source-context.md`, `test-plan.md`;
- два обязательных замечания P-001 и P-002 из предыдущего ревью;
- ранее проверенные критерии Jira `CB-8` и публичные контракты UoW/economy.

## Область повторной проверки

Проверены только исправления P-001 и P-002. Новых замечаний вне этой области нет.

## Логика решения

### P-001 — закрыто

Публичный `EconomyMutationPort.prepare_batch(commands, additional_member_ids)` делает заявленный approve/grant реализуемым без приватных SQLAlchemy-вызовов: economy idempotency gates берутся до общего канонического lock actor/target, locked snapshots доступны для проверки active moderator/administrator и состояния заявки, а ledger и кэши не меняются до `PreparedEconomyBatch.apply()`. Grant, activation, решение, audit и receipt остаются в одном внешнем UoW и фиксируются одним commit. Обычный `apply_batch()` использует тот же путь, поэтому конкурирующего lock order не появляется.

### P-002 — закрыто

Для всех изменяющих шагов закреплён единый протокол `update gate → exact receipt → telegram identity gate → locked state + expected_step → mutation → receipt → commit`. Он сериализует разные `/start` одного `telegram_user_id`, повторно читает member/application до расходования invite и не позволяет запоздавшему ответу с прежним `expected_step` загрязнить следующий шаг FSM. Тот же контракт явно распространён на submit, reject-resume и редактирование профиля.

## Стратегия проверки

Сценарий 4 прямо проверяет разные конкурентные `/start` и replay одного update: ожидаются один member/redemption и сохранённый outcome. Сценарий 5a проверяет два разных update для одного `expected_step`: второй получает `stale_step` без изменения payload. Сценарии 10–12 проверяют authorization до ledger effect, конкурентное одобрение, единственный grant, retry и полный rollback при fault. Этого достаточно, чтобы воспроизводимо проверить оба исправления и связанные критерии Jira.

## Обязательные исправления

Отсутствуют.

## Остаточные риски

- Реализация должна сохранить описанный единый lock order во всех новых адаптерах; это проверяется целевыми конкурентными тестами и финальным review.
- Q-011 по-прежнему не затрагивается: маршрута чтения чужого профиля в плане нет.
