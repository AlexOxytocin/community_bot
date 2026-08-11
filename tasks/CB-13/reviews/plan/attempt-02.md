# CB-13 — вторая попытка plan review

Status: changes_requested

B-001 и M-003 закрыты. Остались три обязательных исправления:

1. admin-only путь открытия fraud-case для уже оплаченного assignment с единым
   gate/replay и `insufficient_reversible_balance`;
2. effective expiry санкции во всех status-dependent read и mutation paths;
3. удаление устаревшего барьера P-001–P-003 из `plan-source-context.md`.

Полная аргументация сохранена в актуальном `plan-review.md` перед
эскалационной контрольной проверкой.
