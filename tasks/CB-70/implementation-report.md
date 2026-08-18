# CB-70 — отчёт о реализации

## Реализованный результат

Mini App создаёт member free-form task через existing task engine: явный start,
одна fixed форма, atomic save→preview, recovery истёкшего preview и exact
publish с immutable `task_id`. Back/popstate только навигирует и не создаёт
новый draft.

## Границы изменения

- один `GET /api/v1/task-creation` и один `POST /api/v1/task-creation` с closed
  actions `start|save|publish`;
- actor берётся только из server session;
- exact receipt replay/conflict привязан к actor, canonical resource и payload;
- current draft и publish replay проверяют active test scope;
- template/community drafts скрыты и не публикуются через web;
- existing reserve/ledger/audit/outbox и Telegram semantics сохранены;
- новых schema/model/dependency/service/framework и browser storage нет.

Runtime ledger против `origin/main`: `467 net LOC` в шести approved файлах.
Conditional owner stop `500` не превышен; независимая проверка подтвердила, что
добавка обусловлена replay/isolation/closed transport, а не новой архитектурой.

## Проверки

- Ruff format/lint и `ty check src tests ops` — green;
- финальные unit/browser targets — `26 passed`;
- targeted PostgreSQL integration/unit до последних guards — `39 passed`;
- browser suite — `7 passed`;
- `git diff --check origin/main` — green;
- PostgreSQL test с новым retry-after-deadline oracle локально собран, но его
  финальный запуск требует недоступный sandbox Docker pipe; PR CI обязан
  исполнить exact integration matrix до merge.

## Delivery status

Локальная реализация завершена. Commit, rebase, push, PR/CI, merge, новый
immutable release, production activation, public smoke и Jira transition ещё
не выполнялись; задача до этих gates не считается доставленной.
