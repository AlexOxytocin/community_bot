# CB-61 — final review, попытка 1

Status: changes_requested

## Findings

- Project drift-test не запрещал локальные значения
  `max_auto_extensions`/`max_fresh_context_handoffs` и не проверял точные refs.
- Не проверялись точные global locator/validation command, обязательный набор
  conditional routes и consumers.
- Global validator не проверял конечность canonical continuation graph и
  фактический список `Policy.consumers`.
- Global/project policy дублировали graph и progress evidence без
  cross-validation.

## Решение

Закрыть весь пакет одним циклом: оставить graph/evidence только глобально,
усилить оба валидатора и добавить negative mutation cases перед повторным
независимым review.
