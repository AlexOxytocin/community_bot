# CB-96 — consolidated independent recheck frontend-only плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Проверенные источники (`reviewed_sources`)

- Live Jira CB-96 перечитана через Atlassian Rovo. Проверены актуальное
  frontend-only описание и comment `10352`, который заменил механические 541
  edge на explicit product transitions и global navigation/state invariants.
  Jira не изменялась.
- Полностью перечитаны актуальные `tasks/CB-96/plan.md`,
  `plan-source-context.md`, `test-plan.md`, `build_ui_contract.py`,
  `ui-contract.json`, `ui-inventory.md`, `README.md`,
  `pre-gate-runtime-snapshot.md` и design key flows
  `design/cb93-ui-plan-v5.md:82-93`.
- Повторно сверены ADR-0016, ADR-0017, ADR-0019 и project workflow, прочитанные
  в первом проходе. Нового архитектурного решения пакет не вводит.
- Generator воспроизведён в отдельной временной папке из актуального
  `build_ui_contract.py` и task-local board. Generated и committed planning
  contracts byte-identical:
  SHA-256 `B9E6ADAB4FB405159E548C96D5BCB70A14A7E2EEBFC80DEC097FBD529F53E7A8`.
  Python AST parsing и `git diff --check -- tasks/CB-96` прошли.

## Замечания по области (`scope_findings`)

Обязательных замечаний нет.

План теперь последовательно ограничен native presentation layer:

- не добавляет backend endpoints, projections, application seams,
  domain/storage/schema/migration/dependency changes;
- сохраняет только существующие connected HTTP paths;
- неподключённые production actions остаются
  `disabled_unavailable`/`disabled_reason`, а conceptual outcomes доступны
  только `dev_test_fixture_only`;
- engine/API gaps находятся только в handoff следующей отдельной задачи;
- runtime использует native HTML/CSS/ES modules без React/Vite/Node, generic
  screen/form framework и новой зависимости.

Точный scope scan по plan/source/test/generator не нашёл инструкций добавить
backend/API/application/domain/storage/schema/dependency реализацию. Stale
`84/9/75` и `#/ui/` встречаются только в явных запретах.

`pre-gate-runtime-snapshot.md` корректно отделяет начатый по Jira comment
`10351` parallel static UI/test diff от planning evidence. Этот review не
читал его как доказательство, не оценивал и не менял runtime/tests. Approval
относится только к planning package.

## Замечания по дизайну (`design_findings`)

Обязательных замечаний нет.

Machine contract соответствует решению `10352`:

- `103` уникальных UI ID, `17` уникальных no-UI ID, `26` уникальных
  capability ID и `11` allowlisted route patterns;
- `128` уникальных explicit product/user edges; count является длиной
  `PRODUCT_EDGES`, а не заранее добитым количеством системных рёбер;
- `transitions[]` не содержит `back`, `reload`, `deep_link_hint`,
  `primary_nav` или `system_state`: повторяющиеся правила вынесены в
  structured `global_contracts` и per-screen attributes;
- нет `#/ui/<id>`, `#/screen/<id>`, route-per-ID или renderer-per-ID;
  все 103 screens используют только 11 route patterns + allowlisted
  `view_state`.

Все 16 обязательных key-edge pairs присутствуют, включая
`T04B→T05`, `T08→M10`, `M07→M03`, `M13→M10/M03/M14`,
`M17→M18`, `M19→M10/M03`, `P04→P02`, `S04→S01`,
`G17→G18`, `G20→G21`, `G22B→M12` и `G06/S02→S08`.

Запрещённые success→mutation Back отсутствуют:
`T08→T07`, `M07→M06`, `M13→M12`, `P04→P03`,
`S04→S03`. Пять success screens имеют post-success logical parent:
`T08→M10`, `M07→M03`, `M13→M10`, `P04→P02`,
`S04→S01`. `global_contracts.success_history` задаёт `replace` и
запрещает target preceding mutation editor/confirm; generator отдельно
assert-ит required и forbidden sets.

Каждый из 103 screens имеет непустой `semantic_layout` из закрытого набора
`list/detail/editor/preview/confirm/outcome/history/hub`. Фактическое
распределение: 26/23/28/4/5/10/6/1. Generic unavailable card не является
layout contract.

Каждая no-UI строка имеет `connection_class: no_ui`. Action и data availability
разделены: actions — `10 existing_http_connected / 61 ui_local_only /
32 disabled_unavailable`; data modes — `32 existing_http_connected /
9 local_view_state / 62 unavailable_without_fixture`.

## Замечания по проверке (`verification_findings`)

Обязательных замечаний нет.

Детерминированные проверки подтвердили:

- 128 уникальных IDs и 128 уникальных
  `source/target/trigger/runtime_scope` signatures; все refs разрешаются в
  текущие 103 screen IDs;
- каждый transition oracle содержит
  `screen_marker/state/history/focus/safe_fallback/request_count`;
  marker/state/history совпадают с edge, fallback является известным screen,
  а `1_authoritative` используется только для
  `production_existing_api`;
- все 32 disabled actions содержат `disabled_reason` в system states;
  fixture scopes не выданы за production success;
- все 103 screens имеют `navigation_class`, `reload_class` и
  `deep_link_class`;
- structured globals задают root replace/role visibility, context Back/focus,
  dirty/dialog behavior, success replace, reload/deep-link safe fallback и
  system-state coverage по различающимся route/navigation/layout/guard
  classes;
- test plan прямо запускает table-driven 103-screen/128-edge browser oracles,
  global invariants, fixture isolation, existing API non-regression,
  accessibility/mobile/visual checks и архитектурный scope guard.

## Обязательные исправления (`required_actions`)

Нет.

## Остаточные риски (`residual_risks`)

- Approval не подтверждает качество уже появившегося runtime diff: он должен
  отдельно сойтись с утверждённым manifest, пройти planned browser/a11y/visual
  gates, Ponytail review и independent final review.
- Второй обязательный verdict `plan-review-orchestrator.md` остаётся
  самостоятельным Gate 1. Этот файл его не подменяет.
- `dependency-remap.json` фиксирует planning base
  `949c837dccaea9c3549737d6f14e782947a291ff`; fresh `origin/main` remap
  остаётся динамическим gate перед принимаемой реализацией и final review.
- Production data, live role profiles и неподключённые engine adapters этим
  frontend-only review намеренно не проверялись; они не разрешены внутри
  CB-96 и относятся к non-regression/следующей задаче.
