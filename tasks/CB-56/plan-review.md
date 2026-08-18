# CB-56 — независимое ревью Pareto-плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники

- `tasks/CB-56/plan-source-context.md` и `tasks/CB-56/plan.md` после единого
  remediation cycle;
- Jira CB-56, CB-60, комментарий 10189, CB-64, CB-57, актуальные links и
  transitions — только для чтения;
- exact `HEAD`/`origin/main`
  `7f2d14ef12c569e6e84daab49be2155a43be5657`;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, release/architecture документы,
  ADR-0016 и ADR-0017;
- actual CI, Dockerfile, Compose, web/worker/health/migration runtime,
  backup/restore contract и tests;
- удалённые исторические release workflow, Python deploy scripts и два shell
  wrappers из parent commit до CB-62.

## Область задачи

Обязательных замечаний нет.

- A1 является одним минимальным наблюдаемым результатом: существующий FastAPI
  Mini App становится запускаемым internal web process и проходит честный
  readiness текущего backend.
- B, C и D причинно отделены и не попадают в implementation diff A1.
- Текущий Jira contract CB-56 шире A1. Это корректно зафиксировано как hard
  blocker с двумя точными owner options; одного transition недостаточно.
- Jira links объяснены через REST orientation; причинная последовательность
  соответствует descriptions: `CB-52 -> CB-56 -> CB-57`.
- Новый ADR для A1 не нужен. Направление B требует отдельного ADR и security
  review до forced-command/host boundary changes.

## Логика решения

Обязательных замечаний нет.

- `community-web` фиксирует `started_at`, а `/readyz` передаёт его как
  `heartbeat_not_before`; старый same-release heartbeat после restart не может
  закрыть gate.
- Heartbeat более чем на пять секунд в будущем fail-closed с отдельным
  стабильным code.
- Web остаётся только в `internal` network; недоказанный egress исключён.
- Worker использует единственный packaged migration head вместо literal
  `0020`, а readiness сравнивает heartbeat revision.
- Production-like release identity требует полный lowercase 40-hex SHA без
  fallback `manual`.

## Альтернативы и риски

- Восстановление R1 release workflow/wrappers отклонено: они осознанно удалены,
  содержат legacy owner/process contract и не соответствуют Mini App-only
  topology.
- Compact DB import/cutover отклонён из A1: текущий Mini App уже работает поверх
  сохранённого backend/schema, а import добавил бы data-loss и rollback surface
  без causal necessity.
- Public HTTPS/deployment отклонён из A1: DNS, TLS edge, production host,
  published digest и host-package contract владельцем не определены.

Ponytail-вердикт: минимальный diff использует существующие FastAPI, PostgreSQL,
worker, outbox, health и Compose contracts; новые platform/framework/storage
слои не нужны.

## Стратегия проверки

Обязательных замечаний нет.

- Dirty-worktree functional smoke, PR synthetic-merge image evidence и future
  actual-merge production evidence разделены и не подменяют друг друга.
- `.github/workflows/ci.yml` включён в exact file scope; PR image связывается с
  synthetic merge SHA и OCI revision.
- Restart smoke обязан получить `503` до нового worker tick и `200` только
  после нового heartbeat.
- Readiness cases расширяют существующую matrix в
  `tests/integration/test_notifications.py`, а не создают второй набор.
- `community-web --check`, safe response assertions, disposable Compose smoke,
  full non-browser/browser gates и cleanup определены.
- Дефект packaged head `0021` против worker literal `0020` имеет прямую правку
  и exact test.

## Обязательные исправления

Нет.

## Остаточные риски

- Implementation заблокирована до выбора владельцем Jira handling.
  Рекомендуется сузить CB-56 до A1; при выборе отдельной задачи пакет должен
  выполняться под её ключом и веткой.
- DNS, HTTPS edge, production host, published image digest и host-package
  provenance не проверялись и остаются B/D gates.
- Backup/restore evidence обязательно до заявления о готовом production
  deployment, но изменение или запуск backup/restore не входит в A1.
- Runtime, Docker smoke и tests не запускались из-за planning-only режима; их
  фактические результаты проверяются после разрешённой реализации.
