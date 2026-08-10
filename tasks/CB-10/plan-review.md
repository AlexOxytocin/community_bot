# CB-10 — эскалационный контроль плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- сохранённые неизменяемые попытки
  `reviews/plan/attempt-01.md` и `reviews/plan/attempt-02.md`;
- `problem-escalation.md` с консолидированной причиной и решением процесса;
- полный актуальный пакет `plan-source-context.md`, `plan.md`, `test-plan.md`;
- ранее сверенные Jira `CB-10`/`CB-11`, семь критериев CB-10, завершённые
  блокеры CB-7/CB-9, канонические правила и фактические Catalog/Economy/UoW,
  `Member`/`ResolvedLevel` contracts.

Внешнее состояние, код, тесты, Jira и Git remote не изменялись. Секретов и
внешних блокеров нет.

## Закрытие эскалационного пакета

### V-001 — закрыто

Catalog race теперь имеет два отдельных принудительных schedule с hook/barrier
и timeout. В `mutation-first` admin mutation фиксируется первой, publish после
gate повторно читает exact version и откатывает reserve, task, task audit,
outbox и receipt. В `publish-first` publish удерживает gate до commit, сохраняет
неизменяемый snapshot прежней exact version, после чего admin mutation также
может commit. Для обоих порядков явно проверяется отсутствие deadlock. Oracle
соответствует реальной семантике сериализации, а не предполагает обязательного
проигравшего там, где обе операции допустимы.

### V-002 — закрыто

Чистая граница стала
`validate_acceptance_actor(task_snapshot, actor, resolved_level)`. CB-11
получает `ResolvedLevel` через caller-owned `resolve_member_level` и передаёт
его после task lock; cached `members.level_number` не участвует в решении.
Сценарий 15 проверяет self-accept, недостаточный и достаточный authoritative
level и намеренно устаревший cache. Это соответствует D-011 и фактическому
доменному `Member`, который уровня не содержит.

### Terminal current — закрыто

Успешная публикация атомарно переводит draft в `published` и устанавливает
`is_current=false`. Поэтому `/task_create` без аргумента не возобновляет
terminal row; новый current появляется только через явный create/resume.

## Отсутствие регрессии P-001–P-003

- Draft path не использует пустой economy batch. Publish выполняет caller-owned
  catalog revalidation в том же UoW под порядком
  `catalog gate → economy gates → canonical members → draft`; cancel сохраняет
  совместимый `economy → members → task` порядок для CB-11.
- CB-10 не читает ещё не существующие assignments и не заявляет slot occupancy.
  Static eligibility закрывает self-accept; assignment-aware cancel/accept race
  остаётся в CB-11.
- Несколько durable drafts при одном current, публичные create/resume и callback
  по draft UUID делают два preview с разными publish keys достижимыми через API.
  Сценарий 12 проверяет два конкурентных вызова, один полный результат,
  отсутствие частичных эффектов, deterministic retry и неотрицательный баланс.

## Семь критериев Jira

Все критерии имеют реализуемый путь и воспроизводимую проверку:

1. недостаточный баланс без частичного резерва — сценарии 8, 12–13;
2. повторный callback без второго task/reserve — 9–10 и 19;
3. прошлый или равный deadline отклоняется — 5 и повторная проверка 11;
4. автор не принимает своё задание — чистая граница и сценарий 15;
5. корректная отмена возвращает точный резерв без опыта — 16–18;
6. restart восстанавливает durable draft — 3 и 19;
7. две публикации сохраняют неотрицательный баланс — 12–13.

Формула `reward * slots`, atomic task/reserve/audit/outbox/receipt, same/different
update idempotency, rollback fault injection, member/community origin boundary,
миграция `0005↔0006` и direct-SQL invariants согласованы. Targeted-контур
достаточен; assignments, доставка outbox и полная регрессия обоснованно остаются
за пределами CB-10.

## Обязательные исправления

Обязательных исправлений плана нет. Реализация может начинаться по одобренному
полному пакету без нового узкого review-цикла.

## Остаточные риски

- Identity gate может сериализовать публикации одного автора раньше creator
  row; это сохраняет, а не ослабляет проверяемый инвариант баланса.
- Exactly-once внешний Telegram response не обещается: ADR-0006 гарантирует
  единственный внутренний эффект и сохранённый outcome.
- Future community creation и assignment lifecycle должны расширить общую
  модель и caller-owned UoW, не меняя snapshot/reserve semantics CB-10.
