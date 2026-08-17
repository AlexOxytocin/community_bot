# CB-61 — final review, попытка 2

Status: changes_requested

## Закрыто из предыдущей попытки

- точные locator, validation command, routes, consumers и continuation refs;
- запрет локальных extension/handoff budgets;
- canonical global graph validation и negative mutations;
- удаление project-копий graph/progress evidence.

## Новый finding

- `continuation.decision_owner` оставался одновременно в global и project
  policy; global validator не проверял canonical value.

## Дополнительные уточнения

- описания должны разделять project ref checks и global graph validation;
- validation command должна сама разрешать путь вместо буквального
  `user_codex_home`.
