# CB-108 — отчёт реализации

## Статус

Локальная реализация и disposable PostgreSQL proof завершены. Git/CI/release и
production gates ещё не выполнялись.

## Что изменено

- `ops/release_contract.py` получил один explicit CLI
  `cutover-0021-to-0022`; других migration pairs и generic framework нет.
- Target/current/image/live heads проверяются fail-closed; release run обязан
  быть monotonic, durable `pending` записывается до остановки `web`/`worker`.
- Cutover требует заранее существующий root-owned `0700` backup directory; dump
  создаётся без pruning и без DB-derived filename: constant-prefix temp `0600`
  → `fsync` → atomic rename → directory `fsync`; isolated restore использует
  exact current release package.
- Durable proof связывает source/target manifests, heads, backup path и SHA-256.
  При live `0022` proof обязателен, включая ready rerun.
- Native Compose выполняет только `run --rm --no-deps migrate`; exact `0022`
  проверяется до lifecycle/`ready`.
- Обычный rollback между разными migration heads явно запрещён.
- ADR-0018 уточнён только для bounded owner-authorized cutover.

## Критерии и доказательства

- Unit state matrix: ready source `0021`, pending `0021`, pending `0022`, ready
  target `0022`, tampered dump, durable write ordering и downgrade reject.
- Adjacent release/restore/runtime suites после fail-closed correction:
  `149 passed`.
- Реальный data migration test с fixture: `1 passed, 16 deselected`.
- Disposable production-Compose subprocess proof:
  `source_head=0021`, `restored_head=0021`,
  `backup_sha256=6d80e6a673f4b5de6d16912545e1f8ef7a045854bafbb93350e87a52b483d6e1`,
  `target_head=0022`, `schema_proof=1,2`, `rerun_head=0022`; disposable project
  и volume удалены.
- Ruff format/check, ty и `git diff --check` прошли.
- Representative rejects исполняются для wrong source/target/live head, stale
  release, foreign pending, current-package mismatch, restore/migrate failure,
  path escape, tampered proof и schema downgrade.

## Ponytail review

Один existing activator, standard library, current Compose и current
backup/restore code. Новых dependencies, service, daemon, SDK, provider,
generic state machine или reusable migration abstraction нет.

`Lean already. Ship.`

`net: -0 lines possible.`

## Остаточный риск и следующие gates

Нужен независимый final security/data-loss review всего diff. После approval:
commit/push/PR/CI/merge, exact immutable release, root-owned exact activator
update, production cutover и public smoke CB-108/CB-107. До green production
smoke ни CB-108, ни CB-107 не переводятся в `Done`.
