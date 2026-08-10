Status: changes_requested

# CB-11 — plan review, попытка 2

M-002—M-005 закрыты, восемь Jira AC и сценарии 1—22 не регрессировали.

Остаточное замечание M-001-R1: общий default
`assignment_policy.maximum_active_assignments=3` в canonical projection меняет
hash неизменённой сохранённой v1. Нужны version-aware projection и повторный
ingest исходного v1 в сценарии 21.

После этой попытки обязателен escalation protocol и одно консолидированное
исправление перед контрольным review.
