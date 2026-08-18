# CB-65 — независимое ревью плана, попытка 1

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

deployment_simplicity: fail

## Проверенные источники

Reviewer прочитал Jira snapshot CB-65, полный planning package, proposed
ADR-0018, project/release/architecture rules, current CI/CODEOWNERS/Dockerfile/
Compose/ops, CB-56 implementation report и exact Git inventory
`origin/main=81b090b348798d6f44e19f09ccedd856ea70cda8`.

Подтверждено: три R1 paths отсутствуют; planning diff не содержит runtime,
production, Jira, SSH или server mutations.

## Обязательные замечания

1. `ops/_runtime.py` читает независимый mutable `current-image` и не выставляет
   `COMMUNITY_BOT_RELEASE`; speculative reuse мог смешать package B с image A
   в backup/restore.
2. `stdlib-first` не доказывает обязательный standalone `stdlib-only` contract.
3. Direct root invocation не фиксирует absolute isolated interpreter,
   sanitized environment и absolute executable lookup.
4. План противоречиво обещает все mismatches до Docker mutation, хотя actual
   image identity проверяется только после `docker pull`.
5. Последовательные `current`/`previous` link replacements не задают полную
   crash-recovery state machine для deploy, explicit rollback и automatic
   recovery.

## Обязательные действия

- Связать backup/restore с тем же atomically selected manifest; если нужен
  второй modified production path, включить его в owner re-approval ceiling.
- Сделать contract строго stdlib-only и добавить import/isolated-run gate.
- Harden direct forced command без wrapper.
- Разрешить противоречие bounded pull против Compose/DB/runtime mutation.
- Задать один crash-safe state record, exact replay и fault matrix для deploy,
  rollback и recovery без второго history slot.

## Остаточные риски

Production filesystem, SSH/interpreter, Docker, `.env`, GitHub Environment и
branch protection не проверялись и остаются fail-closed preflight CB-57.
ADR-0018 остаётся `Предложено` и требует решения владельца.
