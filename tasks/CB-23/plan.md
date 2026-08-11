# CB-23 — план representative migration oracle

## Цель

Усилить существующий test `0009→0010`: до upgrade создать минимальную связанную доменную цепочку и после upgrade доказать сохранение значений, business identities и внешних ключей вместе с уже проверяемым outbox backfill.

## Representative chain на revision 0009

1. Два active member: author/rater и performer/karma target.
2. Member task с reserve transaction, published task и accepted assignment.
3. Result submission и paid reward transaction, связанная с task/assignment.
4. Независимая reputation chain: current `karma_votes` row и две immutable
   `karma_vote_history` revisions с FK на vote и actor member.
5. Независимая moderation chain для assignment: `moderation_cases` с
   `case_type=fraud_review`, затем immutable `dispute_resolutions` version 1.
   Из-за циклической ссылки fixture сначала вставляет case с
   `current_resolution_id=NULL`, затем resolution и после этого обновляет case:
   `current_resolution_id=<resolution>`, `status=resolved`, `revision=1`,
   `resolved_at=<fixed timestamp>`.
6. Две outbox rows: unpublished и published — существующий oracle сохраняется.

Все UUID, business keys, revisions, deltas, outcomes, payload и timestamps фиксированы helper-ом. Inserts используют точные таблицы/колонки схемы `0009` и соблюдают FK/unique/check constraints.

## Oracle после upgrade 0010

- counts по каждой representative table равны ожидаемым;
- join chain `account_transactions → members/task/assignment`,
  `assignments → tasks/members`, `karma_vote_history → karma_votes/members`,
  `moderation_cases → assignments/members/current dispute_resolutions` и
  `dispute_resolutions → moderation_cases/members` не имеет orphan rows;
- фиксированные identities, revisions, values, deltas, business/idempotency keys и timestamps совпадают с fixture manifest;
- published/unpublished outbox становятся `materialized`/`pending` без потери прежних полей;
- operational constraints/indexes остаются на месте, invalid states отклоняются;
- повтор `alembic upgrade head` идемпотентен и oracle проходит повторно.

## Готовность

Один изолированный PostgreSQL migration test, Ruff, ty и diff-check зелёные; implementation report перечисляет только фактические assertions; independent final review approved. Ветка отдельным PR вливается в `task/CB-16`.
