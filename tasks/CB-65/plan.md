# CB-65 — manual-first план provenance/security contract

## Результат и граница

После отдельного owner approval ADR-0018 реализовать минимальный pilot
contract: exact reviewed merge commit, immutable application image digest и
root-owned host package образуют одну versioned tuple. CI только публикует
проверенный image и один bounded release bundle. Transfer, installation,
activation и rollback выполняются вручную в CB-57 после отдельного go-live
решения владельца.

Этот пакет — только план уровня 3. В CB-65 сейчас запрещены runtime-код, Jira
writes, commit/push/PR, production job, SSH и server mutation.

## Deployment simplicity hard ceiling

| Surface | Hard ceiling |
| --- | ---: |
| Новые production/release files | 2: `.github/workflows/release.yml`, `ops/release_contract.py` |
| Изменённые production files | 4: `.github/CODEOWNERS`, `ops/_runtime.py`, backup и restore callers |
| Новые dependencies/SDK | 0; `release_contract.py` — stdlib-only |
| GitHub production/deploy jobs | 0 |
| SSH/deploy-key/forced-command surfaces | 0 |
| Repository shell scripts/wrappers | 0 |
| Новые services/daemons/runtime processes | 0 |
| Manifest versions | 1: `community-mini-app-release/v1` |
| Activation states | 2: `pending`, `ready` |
| Previous tuples/history depth | 1; rollback потребляет previous |
| Automatic recovery/history/orchestration abstractions | 0 |

Запрещены deployment framework, orchestrator/DSL, generic artifact registry,
inventory engine, plugin/provider abstraction, новый secret mechanism,
Kubernetes, Ansible, Terraform, automatic recovery и универсальная rollback
history. Любое превышение ceiling или пятая modified production file требует
`changes_requested` и нового owner re-approval ADR.

### Неблокирующая LOC-сигнализация

Ожидаемый implementation diff: примерно `400–500` production LOC и `450–600`
targeted test LOC. Это не цель и не разрешение минифицировать код. Если
уточнённая оценка до code либо фактический diff превышает примерно `500`
production LOC или `600` targeted test LOC, остановиться и сначала удалить,
объединить или вынести отдельный доказанно самостоятельный slice на новое
owner approval. Security checks нельзя сокращать ради числа строк.

## Единственный release manifest

Canonical UTF-8 JSON с duplicate-key rejection и exact keys:

```json
{
  "contract_version": "community-mini-app-release/v1",
  "repository": "AlexOxytocin/community_bot",
  "commit_sha": "<40 lowercase hex>",
  "tree_sha": "<40 lowercase hex>",
  "pr_number": 1,
  "ci_run_id": 1,
  "ci_run_attempt": 1,
  "release_run_number": 1,
  "release_run_attempt": 1,
  "image": "ghcr.io/alexoxytocin/community_bot@sha256:<64 lowercase hex>",
  "migration_head": "<single packaged Alembic head>",
  "host_package": {
    "sha256": "<64 lowercase hex>",
    "size": 1,
    "files": [
      {"path": "compose.production.yaml", "sha256": "<64 hex>", "mode": "0600"}
    ]
  }
}
```

`host_package.files` — sorted exact allowlist:

- `compose.production.yaml`;
- `ops/__init__.py`;
- `ops/_runtime.py`;
- `ops/backup_postgres.py`;
- `ops/restore_drill.py`.

Manifest не содержит tag, mutable ref, timestamp, environment value, secret,
host path или deployment history.

`release-bundle.tar` содержит ровно root regular files `manifest.json` и
`host-package.tar`. Внутренний deterministic POSIX tar имеет sorted allowlist,
normalized metadata и только regular files. Size/member limits фиксируются
константами; symlink, hardlink, special file, absolute/non-canonical path,
backslash, `.`, `..`, duplicate, missing и extra member запрещены.

## Минимальный implementation file map

### 0. Inventory gate

Перед implementation повторить против exact target commit:

```text
git cat-file -e origin/main:ops/github_deploy_entrypoint.sh
git cat-file -e origin/main:ops/deploy_self_hosted.sh
git cat-file -e origin/main:ops/verify_release_provenance.py
git ls-tree -r --name-only origin/main -- .github/workflows ops
```

На planning snapshot все три historical paths отсутствуют. R1 files/code,
legacy owner и bot lifecycle не восстанавливаются.

### 1. Native release publication без deployment

Добавить `.github/workflows/release.yml` на `push` в `main`:

1. checkout exact two-parent merge commit;
2. найти existing successful `verified-merge-tree` artifact PR CI и вызвать
   pure verifier; второй provenance workflow/artifact не создавать;
3. только после exact parents/tree/PR/run proof построить и опубликовать image
   с immutable GHCR digest и current OCI source/revision;
4. получить exact single migration head из image;
5. pure builder создаёт deterministic host package, manifest и один bundle;
6. pure verifier повторно проверяет final bundle;
7. загрузить один bounded artifact, содержащий только exact bundle, с retention
   и обычной GitHub run identity.

Workflow заканчивается publication. В нём нет `environment: production`, SSH,
deploy key, host secret, transfer, activation или server mutation.

### 2. Один stdlib-only contract tool

Добавить `ops/release_contract.py` без classes/framework и без импортов project
или third-party packages. Четыре маленьких explicit commands считаются одной
cohesive contract responsibility:

- `build` — pure deterministic package/manifest/bundle creation;
- `verify` — pure reviewed-merge evidence либо local bundle verification;
- `activate BUNDLE` — root-only local verification, staging и activation;
- `rollback` — root-only consumption единственного previous.

Если реализация может безопасно объединить pure `build/verify` interface без
ambiguous flags, это допустимое сокращение. Host commands не скачивают image
или artifact, не открывают network и не принимают caller-supplied image/path
для rollback. Внешние команды вызываются exact argv без shell/eval.

CB-57 preflight отдельно:

- инвентаризирует actual host/Python/Docker/Compose/filesystem;
- в authenticated GitHub UI вручную открывает exact green release run для
  manifest commit и скачивает его единственный artifact;
- отдельно вручную ставит exact reviewed `release_contract.py` root:root
  `0700` из того же owner-selected commit;
- обеспечивает наличие exact manifest image локально;
- запускает `/usr/bin/python3 -I -B .../release_contract.py activate BUNDLE`
  как root.

Это заявленная trust boundary pilot: owner selection exact green run и manual
transfer. Host verifier доказывает internal tuple consistency и root-owned
staged bytes, но не cryptographic external authorship artifact. Signer,
attestation verifier, GitHub API client, online lookup, второй digest artifact
и credential не добавляются. Если external authorship станет requirement,
нужна отдельная owner-authorized задача. Bundle не обновляет installed tool.

### 3. Один atomically selected state record

`shared/releases/active.json` — root-owned regular non-symlink file mode `0600`
с exact keys:

```json
{
  "status": "ready",
  "operation": null,
  "current": {"manifest_sha256": "<64 hex>"},
  "previous": null
}
```

Все четыре keys присутствуют всегда. При `ready` operation строго `null`. При
`pending` operation строго
`{"kind":"activate|rollback","target_manifest_sha256":"<64 hex>"}`.
`current`/`previous` содержат только manifest SHA; release directory — ровно
`releases/<manifest_sha256>`, второго content id нет. `previous` равен object
или `null`; run history в state не хранится.

Отсутствующий `active.json` допустим только для initial activation, если
`releases/` не содержит managed release и preflight не обнаружил managed
`worker/web`. Любой malformed/partial state fail-closed.

Stale ordering — lexicographic positive integer pair
`(release_run_number, release_run_attempt)`: новый activate обязан быть больше
ready current. Exact same manifest — idempotent; same pair с другим manifest,
lower pair и любой другой activate при pending запрещены. Pending exact
`activate` resumes. Rollback является единственным исключением ordering и может
выбрать только state.previous.

Activation:

1. взять exclusive lock, общий с backup/restore shared lock, и удерживать его
   через state transition и все Docker/DB subprocess;
2. bounded-read и полностью проверить bundle/manifest/package/path/digest;
3. проверить root directory/active state ownership/mode/no-symlink;
4. безопасно записать files без `extractall`, reread digest, normalize
   root:root/modes, fsync и rename в content-addressed release directory, затем
   fsync parent `releases/` до ссылки из state;
5. убедиться, что exact image уже локально доступен; сверить RepoDigest и OCI
   source/revision; network pull tool не выполняет;
6. проверить `.env` root:root `0600`, Compose config и строгую совместимость:
   target manifest migration head == current manifest head (если current есть)
   == live DB head. Любое различие блокирует до state/process mutation и требует
   отдельную owner-authorized data/deploy задачу; initial install/migration —
   ручной gate CB-57;
7. выполнить все schema/stale/idempotency/precondition rejects до записи
   operation; ready exact tuple — no-op после readiness check, pending exact
   operation — resume;
8. crash-durable primitive записывает `pending` с target current и старым
   current как единственный previous: создать exclusive temp в том же state
   directory, записать/flush, `fsync(temp)`, `os.replace(temp, active.json)`,
   открыть parent directory и `fsync(parent)`; только после успешного parent
   fsync разрешён первый process mutation;
9. прямой compatible-schema lifecycle без abstraction: остановить old `web`,
   force-recreate target `worker` и дождаться health, затем force-recreate
   target `web` и дождаться readiness. `postgres`/`migrate`, admin/product
   bootstrap не запускать;
10. той же primitive записать `ready` и `operation=null`.

При ошибке state остаётся `pending`; automatic recovery нет. Разрешены только:

- exact повтор `activate` того же manifest, который идемпотентно продолжает;
- явный `rollback`, если previous существует и имеет тот же migration head.

Rollback той же crash-durable primitive пишет `pending` с previous как current
и `previous=null`; только после parent fsync запускает тот же прямой lifecycle
и затем durable `ready`.
Previous считается потреблённым; второй rollback без нового successful
activation запрещён. Migration, Alembic downgrade и cross-head rollback
запрещены.

Failure до `pending` не меняет active state. Failure после `pending` сохраняет
ровно этот parseable operation; lock освобождается, backup/restore отклоняют
pending, а operator выбирает exact resume либо rollback.

### 4. Existing ops выбирают ту же tuple

Изменить `_runtime.py`, `backup_postgres.py` и `restore_drill.py`:

- удалить mutable `shared/releases/current-image` как source of truth;
- принимать только `active.status == ready`; при `pending` backup/restore
  fail-closed до Docker/DB external call;
- разрешить canonical current release directory из `active.json`, проверить
  manifest digest и взять из одного manifest project directory,
  `COMMUNITY_BOT_IMAGE` и `COMMUNITY_BOT_RELEASE`;
- selection race между helper calls завершать до external call.
- добавить один явный stdlib context manager `selected_release()` с immutable
  selection и shared `flock` на том же lock file;
- оба callers используют один `with selected_release()` и удерживают shared
  lock через все Docker/DB subprocess, включая restore cleanup. Activator/
  rollback держат exclusive lock; module-global state запрещён.

Других изменений поведения backup/restore нет; оба входят в package.

### 5. Ownership и документация

- `.github/CODEOWNERS`: удалить stale R1 paths; защитить `/ops/` целиком,
  workflow directory, Dockerfile и Compose владельцем `@AlexOxytocin`.
- После явного owner acceptance изменить ADR-0018 на `Принято`.
- При implementation обновить `docs/release-2/README.md` manual publication,
  CB-57 transfer/preflight/activation/rollback gate; R1 runbook не возвращать.

## Пропорциональная test strategy

Один success test выполняет: reviewed proof → deterministic build → verify →
activate A → activate B → one-step rollback A. External Docker/Compose runner
mocked; Linux root/filesystem semantics проверяются одним отдельным scenario.

Table-driven cases соответствуют реальным parser/state branches, а не каждой
теоретической tar комбинации:

| Branch | Representative rejects |
| --- | --- |
| Manifest/provenance | duplicate/unknown/missing field, wrong repository/commit/tree/run, mutable/wrong image digest, internally inconsistent bundle |
| Package parser | digest/size mismatch, missing/extra member, one non-regular member, one traversal/non-canonical path, unsafe mode |
| Host trust | symlink or non-root/group-writable active/release/env path |
| Tuple/image | package A + image B, OCI revision mismatch, different migration head |
| State/idempotency | absent initial state, exact ready/pending schema, lower/conflicting activation, exact ready no-op, exact pending resume, different pending reject |
| Failure/rollback | readiness failure leaves pending, backup/restore reject pending, explicit rollback consumes only previous, duplicate rollback rejects |

Дополнительно:

- build twice даёт byte-identical package/bundle;
- AST import gate доказывает stdlib-only tool;
- compatibility assertion доказывает target/current/live DB head equality до
  mutation; lifecycle — stop old web, sequential worker/web recreate/readiness
  без postgres/migrate/bootstrap/bot;
- A→B/B→A backup/restore test доказывает одну selected manifest tuple и race
  rejection до external call; shared lock удерживается до завершения всех
  subprocess/cleanup, exclusive activation ждёт;
- один mock sequence test доказывает exact
  `write/flush -> fsync(temp) -> replace -> fsync(parent) -> first subprocess`;
  ошибка любого durable-write шага не вызывает lifecycle. Generic crash/fault
  framework не создаётся;
- scoped inventory assertion доказывает отсутствие R1 runtime paths и
  `alexgoodman53` только в production surfaces.

Не создавать test per tar member type, generic fault-injection framework,
automatic crash simulator или SSH/hostile-environment suite.

## Точные команды будущей проверки

```text
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest tests/unit/test_release_contract.py --no-cov
uv run pytest -m "not integration and not browser"
uv run pytest -m "not browser"
uv run pytest tests/browser --no-cov
git diff --check
```

PR CI выполняет existing PostgreSQL/browser/image gates и новый local-only
release-contract test. Production host, SSH и live URL не используются.

## Сопоставление acceptance

| Jira criterion | Machine-checkable evidence |
| --- | --- |
| Один manifest связывает commit/image/package | canonical schema, existing reviewed-tree proof, deterministic build/verify |
| Fail-closed package/path/owner/mode/symlink | representative table-driven rejects до state/runtime mutation |
| Atomic current и previous | closed initial/ready/pending schema, manifest-SHA directory, fsync/replace, exact resume |
| Coordinated rollback | previous manifest+package+image only, equal migration head, consumed after one rollback |
| Stale/idempotent | release run tuple + pending operation digest tests |
| Manual artifact trust boundary | owner-selected exact green run; host доказывает internal tuple/root-owned bytes, external authorship честно вне scope |
| Нет legacy bot/R1 | inventory/allowlist/scoped absence assertion |
| Deployment simplicity | hard ceiling + LOC warning + independent verdict |
| Нет production mutation | release workflow publication-only; manual go-live остаётся CB-57 |

## Stop conditions и non-goals

Stop при непринятом ADR, превышении surface/LOC warning, ambiguous host state,
непроверенном internal artifact/image, unsafe ownership/mode/path, pending
conflicting operation, differing target/current/live DB head или необходимости
automatic recovery/external artifact attestation.

Не входят: production transfer/activation, SSH/deploy key/forced command,
GitHub production environment, DB import/cutover/downgrade, DNS/TLS/proxy,
live acceptance, signing platform, SBOM framework, multi-host/canary/fleet,
Kubernetes/Ansible/Terraform, bot UI/runtime и generic deployment tooling.

## Gate после планирования

Fresh independent reviewer обязан вернуть `Status: approved` и отдельный
`deployment_simplicity: pass`. Любая server automation, automatic recovery,
лишний parser/test framework или превышение ceiling даёт `changes_requested`.
Verdict не принимает ADR за владельца. После review работа останавливается до
явного owner acceptance ADR-0018.
