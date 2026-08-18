# CB-65 — отчёт о реализации manual-first contract

## Результат

Реализован ограниченный ADR-0018 contract: publication-only workflow связывает
существующее доказательство reviewed merge tree, immutable arm64 image digest и
один bounded host bundle; ручные `activate`/`rollback` используют только
root-owned local bytes, два состояния `pending|ready` и одну previous tuple.

Production deployment, SSH, deploy key, forced command, schema-changing
rollout, migration, automatic recovery и release dispatch не выполнялись.

## Exact LOC и объяснение delta

Production additions — `931`:

- `.github/CODEOWNERS`: `2`;
- `.github/workflows/release.yml`: `77`;
- `ops/_runtime.py`: `108`;
- `ops/backup_postgres.py`: `18`;
- `ops/restore_drill.py`: `12`;
- `ops/release_contract.py`: `714`.

Targeted test additions — `830`:

- `tests/unit/test_operations.py`: `86`;
- `tests/unit/test_restore_drill.py`: `23`;
- `tests/unit/test_release_contract.py`: `721`.

От audit candidate `622/176` physical additions delta равна `+222/+434`.
Production delta: formatter раскрыл плотные semicolon/long-line конструкции
`release_contract.py` (`404 -> 632`), удалены четыре строки publication
`concurrency`, `_runtime.py` после narrow Linux-only lock seam стал на две
addition lines меньше. Test delta: formatter и обязательный единый
mocked A→B→rollback scenario (`137 -> 511`), плюс узкий ready/pending selection
oracle `_runtime.py` (`16 -> 76`). Новых semantic surfaces, files,
dependencies, processes, classes или framework этот рост не добавил.

После единственного consolidated security remediation cycle и точечной
Linux CI portability correction delta составила ещё `+87/+220`: exact Git
blob/type/dirty gates, bounded bundle read,
crash-resumable rollback, clean-initial process gate, directory durability,
exact migration-output parser и closed previous-state validation добавлены
в существующие paths вместе с representative oracles. Это не новые surfaces.

## Закрытые findings

- `_release` проверяет root owner, exact type/mode и no-symlink каждого
  installed packaged file до чтения;
- provenance требует lowercase 40-hex SHA, exact PR `workflow_ref`, positive
  run identities и соответствие synthetic merge/parents/tree/HEAD;
- invalid/empty/non-list Docker inspect даёт stable fail-closed
  `ContractError` до indexing;
- один полный mocked A→B→rollback доказывает durable pending/ready, previous
  consumption, compatible schema, worker/web lifecycle и отсутствие
  migration/network pull;
- staging file descriptor закрывается до directory rename;
- `_runtime.py` выбирает тот же `shared/releases/<manifest_sha256>` и использует
  только Linux `flock`; Windows имеет лишь unit-test/import seam и fail-closed.
- exact pending rollback возобновляется из `state.current` после crash, не
  восстанавливая consumed previous;
- package строится из exact commit blobs и отклоняет dirty/non-regular checkout;
- bundle читается не более `MAX_BUNDLE + 1`, initial activation отклоняет
  существующие managed worker/web до mutation;
- nested staging directories fsync-ятся bottom-up до rename, migration output
  принимается без whitespace normalization, malformed previous блокирует ops.

## Проверки

- scoped targeted suite — `126 passed`;
- новый `ops.release_contract` — `83.18%` coverage (`30 passed`);
- changed ready/pending selection branch — отдельный passing unit oracle;
- Ruff format/check по изменённым Python files — pass;
- `uv run ty check src tests ops` — pass;
- workflow YAML/static publication contract — pass;
- один local `docker compose -f compose.production.yaml config --quiet` smoke — pass;
- Python compile, `git diff --check`, R1 inventory и scoped secret/legacy scan — pass.
- первый PR Quality run выявил только Linux non-root test seam; три mocked
  host-flow tests получили explicit `geteuid=0` injection, повторный scoped
  suite — `126 passed`.

Aggregate coverage старых `_runtime` helpers не используется как gate согласно
owner correction; unrelated legacy helper tests ради процента не добавлялись.
Full local product regression не запускался: remote PR CI остаётся полным gate.

## Simplicity ceiling

Fixed surface ceiling соблюдён: два новых production/release файла, четыре
изменённых, `0` dependencies/SDK, production deploy jobs, SSH/shell wrappers,
services/daemons, secret mechanisms и automatic recovery abstractions.
Физический LOC превысил warning после обязательного форматирования и security
test, что явно принято как `justified_exceed`; security не code-golfed.

## Review gates

Independent final security review: `Status: approved`,
`stop_required: false`. Финальный Ponytail-review: `Status: approved`,
`deployment_simplicity: pass`, `net: -0 lines possible`,
`stop_required: false`.

Остаются commit, push, PR, весь remote CI и merge. Release вручную не
запускается; CB-57 сохраняет отдельный manual go-live/preflight gate.
