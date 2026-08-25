# ADR-0018 — Manual-first пара image и host package

**Статус:** Принято

**Дата:** 2026-08-18

**Решение владельца:** 2026-08-18 владелец явно подтвердил: «да принимаем».
Принят ровно manual-first contract этого ADR без расширения deployment scope.

## Контекст

CB-56 добавила current Mini App `web` process и readiness, но current tree не
публикует production image и не связывает его с host files. Image-only rollout
может оставить stale Compose/ops package. R1 release automation удалена
ADR-0016/CB-62 и не является baseline: current `origin/main` не содержит
historical wrappers/verifier, а старая topology включает legacy owner и bot.

Первый automated draft CB-65 скрывал deployment platform внутри одного файла:
GitHub production job, direct SSH forced command и четырёхсостояний automatic
recovery. Для single-host pilot это лишняя поверхность. Владелец выбрал
manual-first publication и отдельный go-live CB-57.

## Решение

1. Перед implementation inventory через `git cat-file -e` и `git ls-tree`
   доказывает actual target paths. Удалённый R1 code не восстанавливается.
2. `.github/workflows/release.yml` работает только на actual two-parent merge
   `main`: потребляет existing successful `verified-merge-tree`, сверяет exact
   PR/base/head/tree/run, затем публикует immutable image digest и один bounded
   release bundle artifact. Второго provenance pipeline нет.
3. Workflow не содержит GitHub production Environment job, SSH, deploy key,
   forced command, host secret, transfer, activation или server mutation.
4. Один canonical manifest `community-mini-app-release/v1` связывает current
   repository `AlexOxytocin/community_bot`, full merge commit/tree/PR/CI run,
   release run identity, immutable GHCR digest, exact single Alembic head,
   deterministic host-package digest и ordered file digests/modes.
5. Host package содержит только `compose.production.yaml` и current Python ops
   files `_runtime`, backup и restore с `ops/__init__.py`. `.env`, runtime data,
   symlinks, special files и arbitrary repository paths запрещены.
6. Один standalone stdlib-only `ops/release_contract.py` без classes или
   orchestration framework реализует pure build/verify и local root-only
   activate/rollback. Host actions не скачивают network artifacts/images и не
   принимают caller tuple для rollback.
7. CB-57 после отдельного owner go-live вручную открывает exact green release
   run, скачивает его единственный artifact, отдельно ставит exact reviewed
   tool из выбранного commit root:root `0700`, обеспечивает local immutable
   image и запускает activator как root. Bundle не auto-updates verifier;
   transfer channel не абстрагируется.
8. Manual owner selection exact green run/commit является pilot trust boundary.
   Host verifier доказывает internal tuple consistency и root-owned staged
   bytes, но не cryptographic external authorship. Signer, attestation verifier,
   GitHub API client, online lookup, second digest artifact и credential не
   добавляются; новое authorship requirement требует отдельной задачи.
9. Verifier bounded-read проверяет closed JSON schema, duplicate/unknown fields,
   repository/commit/image/package/file digests, member count/size, canonical
   paths, regular-file types и expected modes. Extraction выполняется без
   `extractall` в root-owned staging с reread, fsync и content-addressed rename.
10. До state/runtime mutation activator проверяет local image RepoDigest, OCI
    source/revision, root-owned `.env` `0600`, Compose config и equality target
    manifest head == current manifest head (если есть) == live DB head. Network
    pull и migration внутри tool запрещены. Initial install/migration остаётся
    manual CB-57 gate; differing head требует отдельной owner-authorized задачи.
11. Единственный root-owned `active.json` имеет всегда exact keys status,
    operation, current, previous. Status только `pending|ready`; ready требует
    `operation=null`, pending — kind/target manifest SHA. Manifest SHA является
    единственным release-directory identity. State может отсутствовать только
    при доказанно чистой initial activation. Ordering — exact positive
    `(release_run_number, release_run_attempt)`; same-run different manifest,
    lower/conflicting operation fail-closed. Каждый pending/ready transition
    использует temp в том же directory, `fsync(temp)`, `os.replace` и
    `fsync(parent directory)`; process mutation разрешена только после durable
    pending parent fsync. Та же primitive применяется к rollback.
12. Activator держит exclusive shared operations lock. После записи pending он
    останавливает old web, force-recreate/readiness worker, затем web против
    уже совместимой schema. `postgres`, `migrate`, bootstrap admin/product
    config, bot, proxy и новый process не запускаются.
13. При ошибке state остаётся `pending`; automatic recovery отсутствует.
    Backup/restore fail-closed while pending. Operator выбирает exact rerun либо
    explicit rollback.
13a. Отдельный owner-authorized schema cutover может быть добавлен только как
    явный bounded path существующего activator для одной exact forward пары.
    До process/DB mutation он пишет durable `pending`, останавливает все writers,
    в заранее существующем root-owned `0700` directory создаёт fresh backup без
    pruning через constant-prefix temp, `fsync(dump)`, atomic
    rename и `fsync(backup directory)`, затем доказывает isolated restore. Durable proof
    связывает current/target manifests и SHA-256 backup; затем native Compose
    one-shot `migrate` обязан привести live DB ровно к target head. Exact rerun
    принимает только source или target head и при target head требует exact
    backup proof; mismatch остаётся `pending`. Previous с несовместимым schema
    head не является rollback target. Downgrade, automatic recovery и generic
    migration framework запрещены.
14. Rollback использует только единственный saved previous manifest+package+
    image с тем же Alembic head, пишет `pending`, запускает тот же lifecycle и
    завершает `ready` с `previous=null`. Previous потребляется; второй rollback,
    arbitrary digest, migration и Alembic downgrade запрещены.
15. `_runtime.py` предоставляет explicit immutable selection context со shared
    lock; backup и restore callers удерживают его через все subprocess и
    cleanup. Project path/image/release берутся из одного ready manifest;
    pending/race завершаются до external call. Module-global coordination
    запрещена.
16. Privacy-safe evidence содержит только contract/commit/tree/run/image/
    package identities и stable result; environment/secret content запрещён.

## Hard ceiling

- максимум два новых production/release files: `release.yml` и
  `release_contract.py`;
- максимум четыре modified production files: `CODEOWNERS`, `_runtime.py`,
  `backup_postgres.py`, `restore_drill.py`;
- `0` новых dependencies/SDK, production jobs, SSH/forced-command surfaces,
  repository shell scripts, services/daemons, secret mechanisms, registries,
  inventories, plugins/providers и automatic recovery abstractions;
- один manifest version, два state values и ровно одна previous tuple;
- `/ops/` целиком защищён CODEOWNERS как executable root package;
- test strategy: один success scenario и table-driven representative rejects,
  без theoretical permutation/fault/SSH framework.

Non-binding warning estimate: `400–500` production LOC и `450–600` targeted
test LOC. При превышении примерно `500/600` implementation останавливается до
упрощения или нового owner-approved split. Это warning surface, не LOC target;
security нельзя удалить ради числа строк.

Любое превышение hard ceiling получает `deployment_simplicity: fail`,
`Status: changes_requested` и требует owner re-approval ADR.

## Рассмотренные альтернативы

### Automated GitHub deployment через SSH

Отклонено для pilot: добавляет production job, deploy key, forced-command
boundary, host secrets и remote failure semantics до доказанной необходимости.

### Automatic recovery state machine

Отклонено: `pending` честно блокирует operations; exact rerun или explicit
one-step rollback восстанавливает состояние без recovery taxonomy/history.

### Восстановить R1 wrappers/verifier

Отклонено: files отсутствуют в current tree и несут снятую owner/bot topology.
Переиспользуются только проверенные invariants reviewed-tree и immutable digest.

### Registry/provider/deployment framework

Отклонено: один GitHub artifact и ручной CB-57 transfer закрывают single-host
pilot без generic layer.

## Последствия

- CI publication не имеет production authority.
- Owner видит exact artifact/image tuple до любого server action.
- Pending failure требует явного operational решения и не маскируется сложной
  автоматикой.
- Rollback ограничен одной compatible tuple; schema downgrade отсутствует.
- Initial install, host transfer и live acceptance остаются CB-57 gates.

## Связанные материалы

- Jira CB-65.
- [ADR-0011](0011-protected-single-ci-release.md).
- [ADR-0012](0012-python-ops-and-git-deploy.md).
- [ADR-0016](0016-mini-app-only-runtime.md).
