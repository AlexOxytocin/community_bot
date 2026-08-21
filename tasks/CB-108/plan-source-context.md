# CB-108 — контекст решения

- `origin/main=c128275` содержит CB-107 и migration `0022`, чей единственный
  parent — `0021`; upgrade добавляет bounded JSONB column без data rewrite.
- ADR-0018 запрещает migration в routine activation и требует отдельный owner
  gate; ADR-0019 требует backup, stop writers, exact forward migration и public
  smoke для schema-changing release.
- `ops/release_contract.py` уже даёт root check, exclusive flock, immutable
  bundle/image verification, monotonic run ordering, durable pending/ready и
  lifecycle.
- `compose.production.yaml` уже содержит native one-shot `migrate`.
- `ops/backup_postgres.py` и `ops/restore_drill.py` содержат проверенные lower
  primitives; публичные entrypoint блокируются при pending, поэтому cutover
  вызывает их внутри уже удерживаемого exclusive lock без второго lock.
- Canonical pilot по переданным фактам ready на `0021`; release #104 содержит
  CB-107/`0022`, но compatible activator корректно его отклоняет.

Вывод Ponytail: новый framework не нужен; минимальная точка изменения — один
существующий activator и один намеренно негeneric CLI path.

