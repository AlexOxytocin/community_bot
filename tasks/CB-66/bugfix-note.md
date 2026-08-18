# CB-66 — compact bugfix note

Уровень: `1B`.

## Симптом

Автоматическая публикация фактического merge commit `04465077ea1657662ba42712e0724b51e625bf16`
отклонила bounded release bundle, потому что SHA synthetic merge object из
успешного PR-run отличается от SHA заново созданного GitHub merge commit.

## Причина и исправление

Проверка provenance лишне требовала равенство двух разных Git objects. Исправление
удаляет только `synthetic_merge_sha == final_merge_commit`. Обязательная lowercase
40-hex форма synthetic SHA, exact `base_sha`/`head_sha` в порядке parents и exact
`tree_sha` остаются fail closed.

## Regression oracle

- другой валидный synthetic SHA при тех же exact parents/tree принимается;
- валидный, но несовпадающий base/head parent или tree отклоняется;
- malformed synthetic SHA отклоняется.

## Не входит

Новые provenance- или deployment-механизмы, зависимости, runtime surfaces,
ручной dispatch релиза, production/SSH/server mutation.

## Проверка

- targeted release/workflow tests: `35 passed`;
- Ruff format/lint и `ty`: pass;
- `git diff --check`: pass;
- secret и legacy-surface scans: pass;
- независимый provenance review: `Status: approved`, `stop_required: false`;
- Ponytail: `Lean already. Ship.`, `net: -0 lines possible`.

Остаются внешние gates: PR CI и успешная автоматическая publication после merge.
