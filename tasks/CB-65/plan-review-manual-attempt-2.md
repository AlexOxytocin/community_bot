# CB-65 — fresh manual-first review, попытка 2

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

deployment_simplicity: pass

## Закрыто

- Explicit shared lock проходит через backup/restore subprocess и cleanup.
- Manual exact-green-run trust boundary принята без signer/attestation layer.
- Migration orchestration удалена; differing head вынесен в отдельную задачу.
- State schema, initial state, manifest identity, stale ordering и failure
  boundary закрыты.
- `/ops/` целиком включён в planned CODEOWNERS.
- Automatic recovery/framework/SSH/production job отсутствуют.

## Единственное обязательное замечание

`os.replace` без `fsync` parent directory не доказывает, что pending transition
durable до первого Docker subprocess. Activation и rollback должны использовать
`fsync(temp) -> replace -> fsync(parent) -> process mutation`; failure до
завершения parent fsync не запускает lifecycle.

## Обязательное действие

Добавить одну shared durable-write primitive и один representative ordering
test без generic crash/fault framework, затем выполнить terminal
post-escalation recheck. ADR остаётся `Предложено`.
