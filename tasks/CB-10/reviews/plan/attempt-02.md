# CB-10 — plan review, попытка 2

Status: changes_requested

## Закрыто

- caller-owned UoW и lock order;
- реализуемая граница CB-10/CB-11 без отсутствующей assignment schema;
- публично достижимые разные publish keys через несколько drafts.

## Обязательные замечания

1. Concurrent oracle publish против catalog mutation не различал две допустимые
   сериализации: mutation-first должен отклонить publish без эффектов;
   publish-first допускает commit обеих операций с сохранением task snapshot.
2. `validate_acceptance_actor(task_snapshot, actor)` не получал authoritative
   `ResolvedLevel`; доменный `Member` уровня не содержит, а кэш использовать
   нельзя.

## Результат попытки

Сработал барьер двух непройденных review. Дальнейшее исправление выполняется
одним эскалационным проходом по `problem-escalation.md`.
