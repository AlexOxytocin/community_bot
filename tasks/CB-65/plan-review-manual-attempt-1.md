# CB-65 — fresh manual-first review, попытка 1

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

deployment_simplicity: fail

## Проверенные факты

- Exact `origin/main` и HEAD:
  `81b090b348798d6f44e19f09ccedd856ea70cda8`; parents/tree совпадают с
  source context.
- Три R1 paths отсутствуют; runtime implementation и external mutations не
  выполнялись.
- Proposed ADR остаётся `Предложено`.

## Обязательные замечания

1. Неизменённые backup/restore callers не могли явно удерживать одну selected
   tuple/shared lock через все subprocess; hidden module-global coordination
   запрещена.
2. Не был определён declared trust source manual artifact/tool transfer.
3. Старые worker/web продолжали бы работать во время запланированной migration.
4. Initial/ready/pending schema, manifest directory identity, stale ordering и
   precondition/post-pending failures были неоднозначны.
5. CODEOWNERS не покрывал весь executable `ops/` package.

## Owner disposition и remediation

- Разрешены минимальные shared-lock изменения существующих backup/restore
  callers; новых modules нет.
- Manual owner selection/download/transfer exact green run объявлен pilot trust
  boundary. Cryptographic artifact authorship, signer/attestation/API client/
  online lookup/second digest artifact исключены и честно отмечены limitation.
- Migration полностью удалена из activate/rollback. Требуется equality
  target/current/live DB head; initial migration и differing head вынесены в
  owner-controlled CB-57/отдельную data-deploy задачу.
- State schema закрыта: always-present keys, pending|ready, manifest SHA как
  единственный directory identity, exact stale ordering и failure boundary.
- CODEOWNERS планируется на `/ops/` целиком.

## Остаточный gate

После consolidated remediation нужен один independent recheck. ADR не принят;
production filesystem, transfer channel и live state остаются CB-57 preflight.
