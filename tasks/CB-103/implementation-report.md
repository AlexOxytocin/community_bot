# CB-103 — отчёт о реализации

## Результат

- Один memory-only owner рядом с `getJson()` хранит успешные JSON GET DTO 60 секунд,
  нормализует path/query и объединяет одинаковые in-flight запросы.
- Fresh cache возвращается без сети и loading; stale DTO остаётся в DOM, пока один
  background GET обновляет только актуальный `screenRevision`.
- Успешная mutation, 401 и auth/session mutation очищают весь cache и отсоединяют
  старые Promise через generation token. Ошибки, abort и non-JSON не кэшируются.
- Catalog, Profile, Participants, Assignments и Moderation используют общий owner;
  их локальный diff ограничен cached-first render и существующими revision guards.
- Persistent storage, service worker, dependency, backend cache и новый router/store
  не добавлены.

## Проверки

- Focused browser: `7 passed, 13 deselected` — 375×812/430×932, fresh hit,
  controlled TTL, stale settled DOM, dedup, mutation/401 invalidation, hash-route и
  Telegram one-retry.
- `ruff check tests/browser/test_mini_app.py` — green.
- `node --check src/community_bot/transport/static/app.js` — green.
- `git diff --check` — green.
- Full browser suite оставлен CI по решению владельца.

## Ponytail

Production diff: один `app.js`, net +141 строк. Test diff: net +149 строк, включая
адаптацию существующих error/race oracles к fresh/stale-cache контракту. Общий
cache owner — два native `Map`, одна TTL-константа и generation counter; adapters
пяти root loaders не создают отдельные cache policies или duplicated engines.
