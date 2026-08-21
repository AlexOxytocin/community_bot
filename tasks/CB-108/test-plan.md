# CB-108 — план проверки

1. Unit: exact `0021→0022` success доказывает pending до stop/backup/restore/
   migrate, stop обоих writers, no-prune temp/write/fsync/rename/directory-fsync,
   durable proof, exact head и ready после health.
2. Unit: crash/rerun для `pending+0021`, `pending+0022`, `ready-target+0022`,
   missing/tampered proof, чужой pending, stale release,
   malformed proof/dump, unexpected head и failed restore/migrate остаются
   fail-closed; обычный rollback из cutover pending/ready source provenance
   отклоняется, downgrade command отсутствует.
3. PostgreSQL: один disposable production-Compose scenario проходит фактическую
   subprocess boundary cutover: quiescent `0021` → `pg_dump` → `pg_restore` →
   proof → native `migrate` → rerun на `0022`; fixture member сохраняется и
   получает `profile_links_json=[]` с обоими constraints.
4. Static: Ruff, targeted pytest, `git diff --check`, no-secret scan и
   Ponytail review.
5. Independent: `sol_reviewer` сначала одобряет этот обновлённый Level-3 plan,
   затем проверяет security/data-loss semantics всего diff, incompatible
   previous/rollback и exact root-owned tool update до commit.
6. Delivery: required CI → merge → superseding immutable release → production
   cutover → `/mini-app` exact JS, `/readyz`, unauth `401`, два разрешённых
   Telegram profile auth probe.
