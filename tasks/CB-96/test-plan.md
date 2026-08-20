# CB-96 — frontend-only test plan

## Консолидированная структура

Все проверки UI manifest, переходов и browser-поведения находятся в одном
существующем файле `tests/browser/test_mini_app.py`. Отдельные файлы на каждый
экран, маршрут или вид проверки не создаются.

Table-driven проверка читает `ui-contract.json` и подтверждает:

1. точные количества: `103` UI ID, `17` no-UI контрактов, `26` capabilities,
   `11` route patterns и `128` явных продуктовых переходов;
2. уникальность UI/no-UI/capability/transition ID и отсутствие потерянных
   source/target refs;
3. наличие у каждого UI ID route key/pattern, `view_state`, semantic layout,
   role/entry/parent, применимых visual/system states, закрытого action
   `connection_class`, независимого `data_mode` и fixture policy;
4. только `11` разрешённых patterns, `8` предметных semantic layouts и отсутствие
   `#/ui/`, route/component/test per screen;
5. полный transition contract: source ID/view state, target ID/route/view state,
   trigger, target state, history, runtime scope, guard и structured browser
   oracle;
6. обязательные key edges, отсутствие запрещённых success→mutation Back и общие
   invariants для Back/reload/deep-link/system state по различающимся классам;
7. точное распределение `128` edges: `93 production_ui_local`,
   `25 dev_test_fixture_only`, `10 production_existing_api`;
8. границу fixture: production modules не импортируют fixture harness, не
   принимают fixture URL/storage flags и не показывают fixture success;
9. `disabled_unavailable` остаётся на исходном экране, показывает честный
   `disabled_reason` и выполняет `request_count=0`; неизвестное production
   состояние закрывается безопасно;
10. `17` no-UI boundaries и `26` capabilities связаны с актуальным inventory;
    устаревший manifest `84/9/75` не используется;
11. Git diff не добавляет backend routes, application/domain/infrastructure
    seams, models, migrations или dependencies.

## Browser oracle

Консолидированный table-driven сценарий открывает все `103` ID через `11`
patterns и `view_state`, затем сверяет:

- точный screen marker, заголовок, semantic layout и role variant;
- предметное содержимое каждого ID без одинакового generic fallback;
- loading/content/empty/error/permission-closed/disabled/confirm/success только
  там, где состояние разрешено контрактом;
- переход через реальный source control, а не прямой вызов target renderer;
- для всех `128` edges — marker, state, history, focus, safe fallback и
  request count;
- root replace, logical Back/focus return, dirty confirm, dialog Back/Escape,
  success history, reload и deep-link safe fallback;
- `production_ui_local` меняет только `view_state` и не делает запрос;
- `dev_test_fixture_only` достижим только через явную test/dev boundary и
  недостижим в production mode;
- каждый из `10 production_existing_api` edges отправляет точный существующий
  HTTP method/path/body, ждёт авторитетный ответ и только после него показывает
  success; retry не размножает изменяющий запрос.

## API non-regression

Существующие `tests/unit/test_web_auth.py` и
`tests/integration/test_web_api.py` остаются зелёными. Browser cases сохраняют
подключённые catalog/freeform/assignment/result/review/dispute/profile/karma
пути и их текущую request/response semantics. Новые backend/API integration
tests в CB-96 не добавляются.

## Accessibility, mobile и visual evidence

- все `103` ID и применимые system states проверяются при `375×812` и
  `430×932`; `scrollWidth <= clientWidth`, safe-area не перекрывает sticky
  controls;
- action hit area не меньше `44×44` CSS px;
- проверяются labels/fieldset/legend/`aria-describedby`, live error/status,
  focus-visible, keyboard order, dialog focus trap/Escape/focus return;
- semantic token pairs соответствуют AA, status передаётся не только цветом;
- reduced-motion отключает декоративные transitions;
- dark inputs/selects читаемы во всех состояниях;
- девять отдельных runtime frames сопоставляются с полным board/map/coverage и
  split-макетами creation 1/2 и task 1/2; длинные экраны не оцениваются по одному
  обрезанному viewport.

## Воспроизводимые команды

```powershell
uv run python tasks/CB-96/build_ui_contract.py
uv run ruff format --check .
uv run ruff check --output-format=github .
uv run ty check src tests ops
uv run pytest --no-cov -q tests/browser/test_mini_app.py
uv run pytest --no-cov -q tests/unit/test_web_auth.py tests/integration/test_web_api.py
uv run pytest --no-cov -q tests/architecture tests/documentation
git diff --check origin/main
```

До runtime требуются `plan-review.md` и `plan-review-orchestrator.md` со
`Status: approved`. После implementation обязательны Ponytail review,
`implementation-report.md`, independent `final-review.md`, PR CI, immutable
release, production activation и public Mini App smoke.
