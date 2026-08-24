# Исходный контекст плана CB-112

- Jira CB-112, прочитана 2026-08-24: обязательны automatic exact-SHA dev deploy, `readyz` не позднее 120 секунд, сохранение безопасного migration path и one-step rollback.
- `origin/main` на момент планирования: `c4eaaacd9fcbd18478c4d37e7cde78ec24cb5a9e`; live baseline от CB-111: release `107/1`, Alembic `0022`, `/readyz` green, previous `105/1`.
- `.github/workflows/ci.yml`: обязательный путь включает полный набор browser, PostgreSQL/Alembic, image contract и `verified-merge-tree`.
- `.github/workflows/release.yml`: только post-merge повторно ищет provenance, собирает ARM image и загружает release bundle.
- `compose.production.yaml` и Dockerfile уже поддерживают runtime exact `RELEASE`; live server имеет предыдущую совместимую версию.
- ADR-0018/0019 предписывают manual-first tuple и запрещают automatic CD; это противоречит явно утверждённому owner scope CB-112 только для canonical dev server.
