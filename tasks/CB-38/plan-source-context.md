# CB-38 - источники плана

- Jira `CB-38`: цель, область и критерии приемки ускоренного release path.
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: уровни риска, Git/Jira/Telegram gates.
- `docs/AGENT_WORKFLOW.md`: lifecycle задач и правила review.
- `docs/adr/0004-risk-tiered-development-workflow.md`: пропорциональный процесс.
- `docs/adr/0010-small-bugfix-fast-lane.md`: маршрут малых багфиксов.
- `.github/workflows/ci.yml`: два параллельных полных PR/main CI jobs.
- `.github/workflows/release.yml`: текущая публикация после повторного CI на main.
- `ops/deploy_self_hosted.sh`: immutable image, migration, worker/bot readiness.
- `docs/operations/PILOT_RUNBOOK.md`: release, rollback и production gates.
- Безопасный probe `default` и `tg-test`: оба профиля авторизованы 2026-08-14;
  приватные идентификаторы и содержимое чатов в артефакт не переносились.
