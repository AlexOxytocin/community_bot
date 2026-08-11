# CB-15 — независимое повторное ревью self-hosted плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Предыдущий verdict `tasks/CB-15/plan-review.md` и четыре обязательных
  исправления P-001–P-003/V-001–V-004.
- Актуальные `tasks/CB-15/plan.md`, `architecture-solution.md`, `test-plan.md`.
- Принятый `docs/adr/0009-self-hosted-pilot-runtime.md` и актуальный
  `docs/operations/PILOT_RUNBOOK.md`.
- Фактические contracts: `compose.production.yaml`,
  `ops/deploy_self_hosted.sh`, `ops/backup_postgres.sh`,
  `ops/restore_drill.sh`, `ops/systemd/*`,
  `.github/workflows/release.yml`, `tests/unit/test_operations.py`, актуальная
  SQLAlchemy/Alembic schema.
- Точечная автоматизированная проверка:
  `uv run pytest tests/unit/test_operations.py --no-cov -q` — `3 passed`.

## scope_findings

- Область не расширена: self-hosted MVP остаётся отдельным Compose project без
  публичных ports, Redis/Celery/Kubernetes, reverse proxy, external backup, R2,
  application object storage или webhook.
- Compose isolation/egress не регрессировала: PostgreSQL доступен только во
  внутренней сети, `bot`/`worker` имеют outbound egress для Telegram/Sentry.
- Same-host backup по-прежнему честно покрывает логическую порчу, но не потерю
  сервера/диска; принятый владельцем риск ADR-0009 явно сохранён.

## design_findings

- **P-001 закрыт.** Production deploy принимает только
  `ghcr.io/...@sha256:<64 lowercase hex>`. Проверка выполняется до pull,
  migration, запуска services и изменения release state; mutable/local tag
  отклоняется fail closed. Текущая и предыдущая immutable identity сохраняются
  для forward-compatible rollback без schema downgrade.
- **P-002 закрыт.** Unattended backup и restore сами читают
  `shared/releases/current-image`, валидируют digest и экспортируют как
  `COMMUNITY_BOT_IMAGE`; внешний root-owned env path экспортируется как
  `COMMUNITY_BOT_ENV_FILE`. Compose больше не зависит от shell окружения
  предыдущего deploy.
- **P-003 закрыт.** Все три operational script до `source`/Compose отклоняют
  symlink, не-root owner и mode, отличный от `0600`. Сообщения об отказе не
  раскрывают содержимое secret file.
- Restore остаётся изолированным: фиксированная drill DB создаётся и удаляется
  отдельно, production DB не переключается.

## verification_findings

- **V-001 закрыт:** plan/test/runbook требуют только GHCR digest; фактический
  guard расположен до любых release mutations и runtime operations.
- **V-002 закрыт:** backup/restore contracts явно восстанавливают обе Compose
  variables из устойчивого server state; actual server
  `backup → isolated restore` остаётся обязательным доказательством AC7.
- **V-003 закрыт:** restore oracle проверяет существующие
  `alembic_version`, `members` и ledger source-of-truth
  `account_transactions`; ошибочное `ledger_entries` удалено.
- **V-004 закрыт:** scripts fail closed по owner/mode/symlink, backup создаётся
  с `umask 077`, test-plan требует root `0600`, retention и несекретные UTC/RPO/
  RTO evidence.
- Точечный ops-contract suite проходит. Новых противоречий с ADR-0009,
  self-hosted runbook и восемью Jira AC в проверенной области не обнаружено.

## required_actions

- Обязательных исправлений планового пакета нет.

## residual_risks

- Фактический server backup/restore drill и healthy bot с настоящим `BOT_TOKEN`
  остаются execution/final-review gates; одобрение плана не подменяет их
  результат.
- Same-host dump не переживает потерю хоста — это явно принятая MVP-граница.
- Внешний Telegram crash-window между API success и `sent_at` остаётся
  ограничением ADR-0006 и не является end-to-end exactly-once.
