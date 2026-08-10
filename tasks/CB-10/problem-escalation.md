# CB-10 — эскалация двух непройденных ревью плана

Режим: `review_cycle`, фаза `plan`.

## Попытки

- `reviews/plan/attempt-01.md` — `Status: changes_requested`;
- `reviews/plan/attempt-02.md` — `Status: changes_requested`.

## Общая причина

Первый вариант плана корректно описывал продуктовый цикл, но смешал standalone
services с caller-owned transaction и преждевременно сослался на assignments из
CB-11. После исправления архитектурной границы повторное ревью выявило две уже
точечные неоднозначности: неполный oracle двух сериализаций catalog race и
отсутствующий authoritative level во входе чистой eligibility-функции.

## Собранные замечания

- все draft paths должны быть реализуемы без пустой economy batch;
- publish повторно читает catalog в том же UoW под catalog mutation gate;
- assignments/slot occupancy и accept/cancel race остаются CB-11;
- несколько drafts делают разные publish keys достижимыми публично;
- catalog race должен проверять mutation-first и publish-first отдельно;
- eligibility получает `ResolvedLevel` с exact config identity, не cached level;
- terminal draft не остаётся current.

## Решение владельца и процесса

После двух непройденных ревью не запускать новые узкие циклы. Собрать обе
попытки, выполнить одно консолидированное исправление, затем одну контрольную
проверку. Если она снова не одобрена, остановиться для решения владельца.

## Одно консолидированное исправление

- задать два детерминированных race schedules и точный допустимый результат
  каждого;
- изменить eligibility contract на
  `validate_acceptance_actor(task, actor, resolved_level)` и добавить stale-cache
  доказательство;
- зафиксировать снятие `is_current` у published draft;
- проверить весь плановый пакет одним снимком без расширения области и без
  полной регрессии.

---

# Эскалация двух непройденных финальных проверок

Режим: `review_cycle`, фаза `final`.

## Попытки

- `reviews/final/attempt-01.md` — `Status: changes_requested`;
- `reviews/final/attempt-02.md` — `Status: changes_requested`.

## Собранный результат

Первая проверка нашла четыре разрыва identity, acceptance и доказательной
матрицы. Одно консолидированное исправление закрыло M-001—M-003 и почти весь
M-004. Повторная проверка локализовала остаток: новый update после terminal
cancel создавал receipt, хотя сценарий 18 требует отказ без любого нового
эффекта. Дополнительно paused actor был доказан на read path, а не cancellation.

## Причина остатка

Тест проверял отсутствие второго refund/audit/outbox, но не считал receipts и
тем самым закрепил противоположную terminal-семантику. Конкурентная и
последовательная отмена также были описаны неоднозначно: exact replay должен
вернуть сохранённый outcome, но другой update не является replay.

## Одно финальное исправление

- exact replay того же update остаётся успешным через сохранённый receipt;
- новый или проигравший конкурентный update после `cancelled` получает
  `TaskError` до `prepared.apply` и без receipt;
- тест считает ledger/audit/outbox/receipt для concurrent, sequential terminal
  и paused-owner cancellation;
- сценарий 17 уточнён без ослабления сценария 18;
- после одного полного targeted gate выполняется одна эскалационная контрольная
  проверка. Если она не одобрена, работа останавливается для решения владельца.
