# CB-30 — вторая независимая финальная проверка

Status: changes_requested

- M-001 закрыт exact `0011 → 0012 → 0011 → 0012` manifest.
- Visible partial/reject закрыты.
- M-002 остался: no-show тест напрямую вызывал service, но production
  `community-worker` не вызывал deadline finalizer, поэтому automatic
  `accepted → no_show` был недостижим в runtime.

Остальные targeted gates были зелёными; frozen staged tree:
`8e8d22503d0af6ef62bfb220007270c69f62789b`.
