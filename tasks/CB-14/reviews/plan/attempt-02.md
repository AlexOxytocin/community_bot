# CB-14 — plan review, попытка 2

Status: changes_requested

## Проверенный снимок

Staged tree: `03bcaa3170a43c47e570e34edd58abae335a602d`.

## Результат

P-001 закрыто полностью. P-002 закрыто частично: GHCR digest и порядок были
описаны, но Render one-off job старого base service не мог запустить новый
digest до переключения сервисов. Не был определён безопасный rollback после
успешной миграции и частичного deploy без backward-compatible schema contract.

Backup cron ошибочно считался непригодным из-за read-only credential; в
эскалационном исправлении права dedicated backup-role задаются явно, чтобы
исключить неоднозначность.

Архив сохраняет проверенный tree, точный verdict, закрытый P-001 и полный смысл
остаточного P-002 до контрольного review. Jira, index и remote reviewer не
менял.
