# CB-70 — независимая проверка 20/80 плана

**Status: approved**

План после owner decision проверен повторно. Hard ledger точен:
`170 + 15 + 140 + 125 = 450 net runtime LOC`; новые границы остаются тонким
web adapter поверх существующего task engine.

Проверены и приняты: один GET/POST resource path с закрытыми
`start/save/publish`, canonical operation identity и fingerprint, exact replay,
active test-run isolation, expired-preview recovery, immutable publish result,
web-only отказ от `conversation_states` и неизменность legacy Telegram
семантики. DELETE/REUSE map исключает экспериментальные per-step routes,
renderer и actor-native изменения `advance`/`edit_draft_step`.

Ponytail: `Lean plan`; повторно используются existing validators, draft/publish,
receipt и static primitives; новый framework, owner, table, migration,
dependency или generic renderer не вводятся.

Implementation разрешена только после явного принятия владельцем сужения
durable-granularity. Это продуктовое решение не заменяется данным review.
Перед implementation весь экспериментальный runtime/test diff должен быть
полностью удалён.
