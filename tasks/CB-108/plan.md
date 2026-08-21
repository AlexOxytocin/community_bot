# CB-108 — план schema cutover 0021→0022

## Результат

Разблокировать production delivery CB-107 одним явным owner-authorized cutover
canonical pilot с `0021` на `0022`, сохранив manual-first contract ADR-0018.
Риск — уровень 3: операция меняет production schema и обязана fail-closed
сохранять восстановимый backup.

## Граница

- изменить только существующий `ops/release_contract.py`, его targeted tests и
  узкое решение ADR-0018;
- переиспользовать native Compose `migrate`, текущие backup/restore primitives,
  operations lock и durable JSON write;
- реализовать ровно `0021→0022`, без generic migration framework, downgrade,
  daemon, SDK, SSH/CD и новых dependencies;
- не менять product runtime, migration `0022`, Compose topology или вручную
  редактировать `active.json`.

## Контракт

1. Новый explicit CLI принимает exact release bundle и работает только от
   ready current/live `0021` к target/image `0022` с monotonic release run.
2. До любой process/DB mutation записывается durable `pending` с target current
   и единственным previous tuple.
3. Останавливаются оба writer-capable process: `web` и `worker`.
4. Из quiescent `0021` создаётся fresh root-only dump в заранее существующем и
   проверенном root-owned `0700` backup directory, без pruning: constant-prefix temp-файл,
   `fsync(dump)`, atomic rename и `fsync(backup_dir)`. Только затем выполняется
   isolated restore drill с exact revision и ledger proof. Durable proof связывает
   current/target manifests и SHA-256 dump; exact rerun проверяет его.
5. Target Compose выполняет один `run --rm migrate`; live DB после команды
   обязана иметь единственный exact head `0022`.
6. При `pending+0021` создаётся новый durable backup/proof; при `pending+0022`
   и `ready-target+0022` существующий proof обязателен и проверяется вместе с
   dump digest. Обычный lifecycle запускает target worker/web и только после readiness
   переводит state в `ready`. Ошибка оставляет `pending`; rerun допускает только
   live `0021` или уже `0022`. Previous обязан быть exact source `0021`; обычный
   rollback из cutover state запрещён, потому что означал бы schema downgrade.
   После успешной migration previous хранится только как provenance/backup
   identity и не является совместимым rollback target.
7. Root-owned activator обновляется только exact reviewed bytes из merged commit;
   bundle не обновляет privileged verifier, ручная правка state/proof запрещена.

## Проверка

- targeted unit success/rerun/failure-order/mismatch/rollback-reject tests;
- реальный disposable production-Compose subprocess cycle: quiescent `0021` →
  durable `pg_dump` → isolated `pg_restore` → proof → native migrate → rerun;
- Ruff, pytest, `git diff --check`, secret scan;
- независимый `sol_reviewer` security/data-loss verdict и Ponytail review;
- PR/CI/merge, новый immutable release, production backup/cutover/activation и
  public acceptance scopes CB-108 + CB-107.
