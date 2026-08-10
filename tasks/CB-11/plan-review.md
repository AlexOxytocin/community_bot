Status: approved

# Эскалационная контрольная проверка плана CB-11

## Проверенные источники

Проверены сохранённые `reviews/plan/attempt-01.md` и `attempt-02.md`, `problem-escalation.md`, актуальные `plan-source-context.md`, `plan.md`, `test-plan.md`, `needs-info.md`, восемь критериев Jira CB-11, решения D-013–D-015, правила ADR-0005/0006/0007 и фактические публичные контракты product config, economy и task/UoW из CB-7/CB-10.

## Итог

Эскалационное исправление M-001-R1 закрыто однозначно и реализуемо:

- для `config_version=1` исходный документ без `assignment_policy` сохраняет прежнюю canonical projection и прежний `content_hash`;
- effective default `maximum_active_assignments=3` вычисляется в runtime snapshot и не переписывает исторический payload/hash;
- для `config_version>=2` `assignment_policy` обязателен, сохраняется и входит в новый payload/hash;
- сценарий 21 повторно ingest-ит исходный v1 в существующую БД и требует прежний hash/replay без конфликта, затем проверяет v2 ingest/activate и rollback на ту же v1.

Прежние M-001–M-005 не регрессировали: configurable accept limit и его конкуренция, replacement освобождённого слота, последовательные result versions, immutable private dispute handoff и публичная economy correlation с legacy hash compatibility имеют конкретные контракты и целевые проверки.

Все восемь Jira AC сопоставлены сценариям 1–22. Порядок блокировок, exactly-once settlement, D-013–D-015, privacy, rollback, миграции и границы CB-12/13/15/16 согласованы. Обязательных исправлений и внешних блокеров не осталось.

## Остаточные риски

Риски реализации контролируются заявленными PostgreSQL concurrency/fault tests и synthetic Telegram сценарием. Полная регрессия обоснованно остаётся CB-16 и не блокирует начало реализации CB-11.
