# CB-96 — пакет полного UI-слоя концепции 05

Каноническая область: native presentation layer без новых backend/API/
application/domain/storage/schema/dependency изменений.

## Реализационный контракт

- `plan.md` — frontend-only slices и delivery gates;
- `plan-source-context.md` — Jira/ADR/repository evidence;
- `test-plan.md` — manifest/browser/accessibility/visual oracle;
- `ui-contract.json` — 103 UI, 17 no-UI, 26 capabilities, 11 route patterns,
  128 explicit product/user transitions и global navigation/state invariants;
- `ui-inventory.md` — человекочитаемые таблицы всех 103 экранов, 128
  перехода и 17 no-UI границ;
- `build_ui_contract.py` — детерминированная пересборка manifest;
- `next-task-engine-handoff.md` — ненормативный handoff API gaps следующей
  отдельной задаче;
- `dependency-remap.json` — base/static-path refresh gate;
- `pre-gate-runtime-snapshot.md` — read-only фиксация параллельного UI executor,
  не evidence до approved reviews;
- `plan-review.md`, `plan-review-orchestrator.md` — два обязательных verdict.

## Дизайн и скриншоты

`design/README.md` перечисляет полный CB-93 concept-05 source package и все 18
PNG. В него входят full screen board, grouped transition overview, contract
coverage, key screen groups и две части каждого длинного create/task screen.

Production fixtures запрещены. Неподключённое действие всегда показывает
`disabled_reason`; conceptual success разрешён только dev/test/screenshot
harness.
