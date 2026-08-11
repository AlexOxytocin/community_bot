# CB-13 — целевой план проверки

## Контур

PostgreSQL 18, реальные assignment/result/dispute/ledger/karma данные, общий UoW
и synthetic aiogram. Один targeted gate после полной реализации; полная
регрессия MVP остаётся CB-16.

## Сценарии

1. Empty migration и `0008→0009→0008→0009`, backfill и append-only triggers.
2. Open dispute сохраняет reserve/system issuance frozen и показывает все result
   versions/evidence только authorized queue.
3. Exact replay и payload conflict resolution; concurrent moderators — один
   winner без двойного ledger/reliability/audit/receipt.
4. Каждый P-002 code по applicability matrix member/community: exact assignment
   status, payout/refund/no-issuance, folded reliability, paid-slot occupancy и
   outbox; запрещённые сочетания отклоняются без эффектов.
5. Fault injection между resolution row и economy/audit: полный rollback.
6. Conflict matrix creator/performer/reviewer/inviter/prior-sanction/declared;
   unrelated active moderator проходит, inactive/forged callback — нет.
7. Appeal before/at/after 7-day boundary, exact replay, second appeal rejection,
   different administrator, `resolution_reversal` source links, folded
   reliability, permanent paid-slot occupancy и full reverse→new outcome
   atomicity; insufficient available balance/experience оставляет case без
   изменений.
8. Notice/warning/restriction/suspension/ban permission matrix, required
   reason/end, administrator-only `karma_vote`, elapsed suspension without
   worker через status-dependent mutation и profile/read projection, revoke/
   expire, overlap и защита более нового member status.
9. Restricted `create_task|accept_task|karma_vote` blocks only exact action without
   deleting historical data; forged client permission has no effect.
10. Interaction count boundaries threshold `0`, `3→4`, rolling window edges,
    both directions, partial/full, community excluded; resolution/appeal
    reversal lowers count и корректно close/rearm episode.
11. Concurrent payout crossing and alert review: one episode, no deadlock,
    latest links/count/config exact; close/rearm/new crossing works.
12. Alert outcomes and notes privacy; penalty none/one/both, available-balance
    boundary, idempotency, no reserve/experience effect, all-or-nothing fault.
13. P-003 karma signals at below/at thresholds, mutual dispute pair, normalized
    comments, exact rule/entity/UTC-bucket replay; no automatic credits/status
    effect и no raw comment в signal/outbox/log.
14. Exclude/restore exact karma vote revision under pair gate, race with new
    revision and stale-decision semantics; aggregate delta, raw/history immutable
    and still admin-readable.
15. Fraud against unpaid dispute и paid assignment через admin-only
    `OpenFraudCaseCommand`: exact replay/payload conflict, race с appeal/другим
    case-open, no issuance либо exact one-time reversal, source links,
    ledger/cache equality, interaction alert recompute и atomic
    `insufficient_reversible_balance` без частичных эффектов.
16. Synthetic Telegram queue/preview/confirm/restart/stale/forged callbacks;
    callback ≤64 bytes and no private data in logs/outbox/participant output.
17. Direct SQL rejects second appeal, duplicate resolution command, history
    mutation, invalid sanction and penalty without eligible alert outcome.
18. Итоговый targeted gate: tests без skip/deselect, migration cycle, Ruff, ty,
    build, entrypoints, links/diff/secrets зелёные.

## Матрица Jira AC

- freeze до решения: 2, 4–5;
- resolution statuses/ledger: 3–5, 7, 15;
- conflict of interest: 6;
- authored/reasoned/timed/revocable sanction: 8–9, 17;
- karma no automatic punishment: 13–14;
- reproducible resolution/appeal audit: 3, 5, 7, 16–17;
- full/partial/refund/fraud integration: 4, 15.

## Правило дефектов

До завершения CB-13 дефекты исправляются в этой ветке. Дефекты полной регрессии
готового MVP в CB-16 получают отдельные Jira issues и ветки.
