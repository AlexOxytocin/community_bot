# CB-103 — план session-memory GET cache

## Уровень риска

Уровень 2: frontend-only изменение, но общий request boundary затрагивает auth,
mutation invalidation, конкурентные запросы и late-response routing.

## Подтверждённая причина

Существующий `getJson()` всегда выполняет новый `fetch`, а root loaders создают
пустой per-screen state и показывают loading до ответа. Отдельные GET обходят
`getJson`; успешные mutations не имеют единой frontend cache invalidation точки.
`screenRevision` уже является authoritative route/view token и должен остаться
единственным late-render guard.

## План

1. Добавить рядом с `getJson()` один memory-only Map успешных JSON DTO и один
   Map in-flight Promise. Нормализовать key через native `URL`/sorted query;
   TTL — одна константа 60 секунд.
2. Провести существующие frontend fetch через минимальный `apiFetch`: на 401
   очищать private cache; после успешной non-GET/non-auth mutation очищать весь
   GET cache. Ошибки, abort, non-JSON и auth responses не кэшировать.
3. `getJson()` возвращает fresh cache без сети; stale cache — сразу и запускает
   один deduplicated background refresh с optional callback. Callback каждого
   root loader проверяет текущий `screenRevision` перед render.
4. Перевести Catalog/Profile/Participants/Assignments/Moderation root loaders
   на cached-first settled render. Сохранить их существующие state, history,
   focus, scroll и error owners; stale refresh error не заменяет settled DOM.
5. Добавить browser oracles для fresh hit, controlled stale TTL, concurrent
   dedup, mutation invalidation, 401 clear/one auth retry и route-late guard в
   375×812/430×932.
6. Выполнить targeted checks, Ponytail review и независимый concurrency/security
   review, затем PR/CI/merge и обязательный immutable production delivery gate.

## Ponytail full

Без class/store/router framework, dependency, persistent storage, service worker,
backend cache, tags или per-resource invalidation graph. Два native `Map`,
`Date.now()`, `URL` и полная invalidation после mutation — весь новый механизм.
