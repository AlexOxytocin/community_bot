# CB-57 — финальная независимая перепроверка плана

**Контракт:** `community_bot.plan_review.verdict.v1`

Status: approved

ADR-0019 проверен вместе с планом, но не принят: решение остаётся за владельцем.

## Итог

Обязательных исправлений не осталось. Latest package source-grounded, ограничен
CB-57 и задаёт исполнимый stop-on-failure путь без подмены immutable package,
новой CD/SSH-платформы, dependency, daemon или framework.

## Закрытые критические границы

- **Compose/data cutover:** direct initial activation fail-closed на distinct
  project/head; выбран owner-gated fresh dump → new volume restore →
  `0020→0021` → activation. Пустая DB и host-only
  `COMPOSE_PROJECT_NAME` dependency запрещены.
- **Backup/restore:** one-time native boundary учитывает отсутствие
  `active.json=ready`: restrictive umask, root-only regular `0600`, temp +
  atomic rename, tool compatibility, `--no-owner --no-privileges`, nonzero
  stop, ledger и named count checks. Encryption не заявляется без доказательства.
- **Worker/freeze:** до activation требуется zero-workload window; before/after
  fingerprint допускает только expected heartbeat. После initial ready worker
  останавливается до отдельного шестого owner gate на resume/outbound.
- **Quiescent readiness:** readiness доказывается до worker stop; объявленный
  time-bounded window честно допускает expected `heartbeat_stale`/`503` и
  проверяет web/db/path отдельно. Final success и Jira `Done` возможны только
  после zero-backlog recheck, owner-approved worker resume, Compose green и
  `/readyz=200`.
- **Rollback:** edge закрывается и восстанавливается до data switch; landing и
  unrelated services проверяются. Возврат rehearsal использует exact staged
  Compose force-recreate/wait, а не неработающий same-digest `activate`, затем
  снова quiesces worker и полностью применяет unique-upstream path edge.
- **Mutation boundary:** old `0020` rollback закрывается при dispatch первого
  mutating request или worker/outbound effect. Ambiguous accept разрешается
  только exact same-key replay на new DB; новый key, duplicate effect и rollback
  на stale old snapshot запрещены.
- **Telegram auth:** official bridge стоит в `<head>` до app scripts; raw
  unchanged `initData` отправляется один раз с exact
  `Content-Type: text/plain; charset=utf-8`, same-origin credentials/origin.
  Synthetic offline bridge oracle проверяет `204`→cookie→single retry,
  existing/missing/invalid paths и отсутствие proof в URL/storage/log/evidence.
- **Edge:** landing `/` не заменяется; открываются только `/mini-app`,
  `/mini-assets/`, `/api/v1/`. До reload доказываются unique target Compose
  labels/network/DNS endpoint, internal health, `nginx -t` и exact config
  rollback.
- **Permanent delivery process:** deployable merges сериализуются по monotonic
  release order; superseding artifact обязан содержать earlier merge и пройти
  per-task scope smoke/evidence. Docs/tests/`tasks/**`-only изменения получают
  skip. Blocker не допускает `Done`; нужен green public smoke либо явный
  owner-approved waiver.

## Scope и доказательства

- Release `#71/1` используется только как publication baseline; deploy
  candidate — новый exact green post-CB-57 artifact после handshake fix.
- Public acceptance ограничена фактически реализованным slice: catalog/detail/
  accept, active assignments list/detail и read-only moderation queue. Full
  backend parity не заявляется, будущие capabilities не удаляются.
- Migration `0021` проверена как добавление только `web_sessions`; plan
  сохраняет old data и требует singleton head/count/invariant proof.
- Server IP, credentials, secret paths/content, environment values и raw auth
  proof в planning artifacts отсутствуют.

## Ponytail

Lean already. Ship.

План переиспользует ADR-0018, `ops/release_contract.py`, native PostgreSQL,
Docker Compose и existing nginx. Дополнительная orchestration abstraction не
нужна.

## Валидация и оставшаяся неопределённость

- Прочитаны canonical project/process/release routes, ADR-0016—0019, полный
  latest CB-57 package, Compose, release/backup/restore contracts, migration,
  auth/static frontend, browser/integration tests, worker loop и readiness
  contract.
- Telegram bridge/initData требования сверены с primary source:
  `https://core.telegram.org/bots/webapps#initializing-mini-apps`.
- `git diff --check` — green на момент final re-review.
- Server, Jira, GitHub, Telegram и deployment mutations не выполнялись.
- Host nginx bytes, actual queue/deadline state, PostgreSQL tool compatibility и
  exact new release identities по природе доступны только на owner-authorized
  go-live preflight. План обращается с ними как со stop gates, а не как с уже
  доказанными фактами.
