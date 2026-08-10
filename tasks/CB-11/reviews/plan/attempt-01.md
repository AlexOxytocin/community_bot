Status: changes_requested

# CB-11 — plan review, попытка 1

Проверены Jira CB-11, полный плановый пакет, D-013—D-015, ADR и публичные
контракты CB-7/CB-10.

Обязательные замечания:

- M-001: не задан immutable rollout `assignment_policy` через product config;
- M-002: абсолютный `UNIQUE(task_id, slot_number)` запрещает replacement;
- M-003: v2 результата недостижима при submit только из `accepted`;
- M-004: нет durable dispute/comment handoff для CB-13;
- M-005: нет публичного economy correlation/hash contract.

Восемь Jira AC, общий lock order и границы CB-12/15/16 признаны реализуемыми.
