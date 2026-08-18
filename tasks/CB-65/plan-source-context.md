# CB-65 — исходный контекст manual-first плана

## Статус снимка

- Дата: 2026-08-18, `America/Buenos_Aires`.
- Process level 3, planning-only: без runtime-кода, Jira writes, commit/push/PR,
  Docker runtime, SSH, deployment, server и Telegram действий.
- Jira CB-65 прочитана через Atlassian Rovo MCP: `К выполнению`, комментариев
  нет, задача блокирует CB-57.
- После свежего `git fetch origin main` exact commit:
  `81b090b348798d6f44e19f09ccedd856ea70cda8`; parents
  `7f2d14ef12c569e6e84daab49be2155a43be5657` и
  `2ea453d087f69046952b2f8e61ab46fec0623d3e`; tree
  `27f57a06ec07d3a2bf6fe5a921ed7e22b4cee0d4`.
- Worktree detached; ветка CB-65 не создавалась.

## Актуальное owner acceptance

Deployment simplicity важнее automation полноты:

- CB-65 release workflow только доказывает reviewed merge и публикует image +
  один release bundle artifact;
- production Environment job, SSH/deploy key/forced command и server mutation
  исключены;
- CB-57 после отдельного owner go-live вручную получает artifact/image,
  проводит host preflight и запускает local root activator;
- active state имеет только `pending|ready`, current и один previous;
- failure остаётся pending; разрешены exact rerun или explicit one-step
  rollback, automatic recovery отсутствует;
- tests закрывают реальные parser/state branches representative tables, а не
  каждую теоретическую permutation.
- manual owner download/transfer exact green run является declared pilot trust
  boundary; host не доказывает cryptographic external artifact authorship;
- activate/rollback не выполняют migration: target/current/live DB heads
  должны совпасть, иначе требуется отдельная owner-authorized data/deploy task.

Предыдущий automated draft и его approved review superseded этим acceptance:
его GitHub production job, direct SSH boundary и recovery taxonomy больше не
являются планом реализации.

## Jira boundary

CB-65 требует один machine-readable tuple reviewed commit + immutable image +
root-owned host package; fail-closed stale/partial/path/owner/mode/symlink;
atomic activation; coordinated previous rollback; current owner; no R1/bot;
privacy-safe evidence. Production deploy/live acceptance разрешены только
отдельным owner решением.

Не входят: compact DB cutover, DNS/TLS/proxy, production transfer/deployment,
SSH/server changes, live acceptance, new secret mechanism, hosted service,
Kubernetes, Redis, broker или generic deployment framework.

## Current Mini App topology

### Есть

- `.github/workflows/ci.yml`: PR quality/PostgreSQL/browser/image gates и
  existing `verified-merge-tree` artifact с repository, PR, base/head,
  synthetic merge/tree и CI run identity.
- `Dockerfile`: non-root image и OCI source/revision labels.
- `compose.production.yaml`: required immutable image/release и current chain
  `postgres -> migrate -> worker -> web`; host port и bot service отсутствуют.
- `ops/_runtime.py`, backup и restore: root-owned `.env` `0600`, immutable image
  validation, PostgreSQL dump и isolated restore.
- `.github/CODEOWNERS`: current owner `@AlexOxytocin`, но stale R1 paths.

### Нет

- post-merge release publication;
- deterministic host package/manifest/bundle;
- current verifier/activator/rollback;
- production deployment authority.

## Exact legacy inventory

Команды против свежего `origin/main`:

```text
git cat-file -e origin/main:ops/github_deploy_entrypoint.sh
git cat-file -e origin/main:ops/deploy_self_hosted.sh
git cat-file -e origin/main:ops/verify_release_provenance.py
```

Все вернули non-zero. Historical files прочитаны только из `7c4bda8^` как
negative evidence. Полезны invariants exact merge/tree/run, immutable digest,
root ownership и stale rejection. Code/topology не переиспользуются: старые
wrappers содержат legacy `alexgoodman53`, bot process и shell boundary,
удалённые ADR-0016/CB-62.

## Verified current ops mismatch

`_runtime.py::read_current_image()` читает отдельный mutable
`shared/releases/current-image`, а `operations_environment()` не выставляет
обязательный `COMMUNITY_BOT_RELEASE`. Поэтому package activation с неизменённым
helper допускает mixed tuple или Compose failure в backup/restore.

Минимальная явная coordination затрагивает `_runtime.py` и оба existing
backup/restore callers: один immutable selection context держит shared lock
через все subprocess/cleanup; activator держит exclusive lock. Pending/race
отклоняется до external call; новый module или module-global state не нужен.

## Ponytail manual-first итог

- один versioned manifest;
- один GitHub artifact;
- один stdlib-only Python file;
- pure CI build/verify;
- local manual root activate/rollback;
- один `active.json`, два status values, один consumed previous;
- один crash-durable state-write primitive: fsync temp, replace, fsync parent
  до process mutation;
- ноль production jobs, SSH surfaces, wrappers, daemons, frameworks и
  automatic recovery.
- ноль signer/attestation/API-client/online-authorship layers;
- ноль migration orchestration: только compatible-schema worker/web recreate.

Warning estimate: `400–500` production LOC и `450–600` targeted test LOC; выше
примерно `500/600` — stop и simplification/split до code.

## Неизвестное внешнее состояние

Не читались production filesystem, Python/Docker/Compose versions, current
state, authorized keys, `.env`, credentials, GitHub Environment/branch
protection или actual transfer channel. Они не блокируют planning package, но
CB-57 обязан fail-closed проверить их после отдельного owner go-live.

## Источники

- Jira CB-65/CB-57 snapshot 2026-08-18.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`.
- Jira/process, architecture, Release 2 и multi-agent routed documents.
- ADR-0011, ADR-0012, ADR-0016, ADR-0017.
- `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `Dockerfile`,
  `compose.production.yaml`, current `ops/`.
- `tasks/CB-56/plan*`, implementation report и review.
- Git history до CB-62 только как negative legacy evidence.
