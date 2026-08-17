# CB-58 — отчёт о реализации дизайн-системы Release 2

## Итог

CB-58 реализована локально в ветке `task/CB-58` в утверждённой области:
созданы каноническое руководство, versioned machine-readable tokens и
автономный интерактивный preview для Telegram Mini App и будущего browser UI.
Один semantic/component contract обслуживает dark, light и system themes;
Telegram ThemeParams проходят атомарную проверку контраста и при любой ошибке
целиком возвращаются к base semantic palette.

Runtime бота, React/Vite, API, auth, routing, Telegram WebApp SDK и production
deployment не добавлялись. Это foundation/handoff для CB-53, а не скрытая
реализация frontend-приложения.

## Поставленные артефакты

- `docs/release-2/design/DESIGN.md` — направление «Технологичная взаимопомощь»,
  правила foundations/components, responsive/platform boundaries, WCAG и
  handoff в CB-53;
- `docs/release-2/design/design-tokens.json` — schema `1.0.0`, primitives,
  mode-neutral semantic aliases, шесть effective palette modes, Telegram map,
  resolver policy, contrast/state/component/preview contracts и font
  provenance;
- `docs/release-2/design/design-preview.html` — один self-contained HTML без
  сети и внешних runtime dependencies, с embedded canonical JSON и WOFF2;
- `docs/release-2/README.md` — capability links на все три product outputs;
- `tests/documentation/test_release2_design_system.py` — `AT-01`—`AT-06`;
- `tasks/CB-58/test-plan.md` — фактические `Actual/Evidence/Deviation/Result`
  для `TP-01`—`TP-15`.

Контрольные SHA-256 product outputs на момент отчёта:

| Файл | SHA-256 |
|---|---|
| `DESIGN.md` | `03918E5AFE9946CCB5DE4C668965DAED19168B89D6343AB21FB3816B03A60433` |
| `design-tokens.json` | `1D7348DCC715053B6EB9F75DF3520328B95DE0045B82DA36F065681778E5B211` |
| `design-preview.html` | `7A86CF1F37ADB1B0B2A67E4B22406847D9B6F51170079065D1DB7D311A4B76DB` |

## Contract-first реализация

Первый red run был выполнен до создания product artifacts:

```text
uv run pytest -q --no-cov tests/documentation/test_release2_design_system.py
6 failed — отсутствовали DESIGN.md, design-tokens.json и design-preview.html
```

После реализации тот же suite зелёный:

```text
6 passed in 0.93s
```

Контракт фиксирует:

- 53 component IDs: 31 `previewRequired` и 22 `documentedOnly`;
- 114 точных component state token records;
- 158 contrast pairs со всеми foreground/background/adjacent paths;
- 17 stable preview sample IDs и 136 variant/state DOM cases;
- 6 effective palette modes;
- canonical control projection, не допускающая theme/platform/preset tuple вне
  этих шести modes;
- точные built-in frames `320×568`, `390×844`, `1440×900`;
- запрет прямых primitive/platform references в component CSS;
- отсутствие Telegram SDK/globals, React/Vite и внешних URL в preview.

## Remediation после первого final review

Первый независимый final review обнаружил реальный пробел: metadata для state
records существовала, но preview не доказывал computed привязку каждого
preview-required состояния к `componentStateTokens`. Поэтому прежний `passed`
для соответствующих частей `TP-06/07/10/11/14` не переносился автоматически.
В одном консолидированном цикле:

- добавлены 114 live specimens для всех action/form/choice/status/system и
  остальных state records; каждый визуальный field получает значение по
  точному semantic path из JSON;
- browser contract прошёл 114 records × 6 canonical palettes и 2868 computed
  assertions для foreground/background/border/focus/indicator/icon/placeholder/
  message/progress/action;
- исправлены фактические primary pressed и destructive hover/pressed styles;
- control UI ограничен `contracts.controlProjection`: browser preset отключён,
  explicit Telegram mode показывает только preset своей base mode, system —
  четыре допустимых preset; обе negative light↔dark попытки отклонены;
- synthetic product content приведён к D-018/D-032 и domain rules: member
  `S · 15–40 минут · 3 кредита`, community автор `Сообщество`,
  `M · 40–75 минут · 4 кредита`, категория `Практическая помощь`, limit
  описания `1200`;
- `tests/documentation/__init__.py` сохранён как package marker: без него
  репозиторный Ruff gate `INP001` отклоняет contract test как implicit namespace
  package; файл содержит только module docstring и не добавляет runtime logic.

## Соответствие критериям CB-58

| Критерий | Реализация | Проверка |
|---|---|---|
| Ролевая palette и независимые status roles | `semantic.{dark,light}.color`, `componentStateTokens`; brand/route отделены от status | `AT-01`—`AT-03`, `TP-02`—`TP-05`, `TP-10`, `TP-13` |
| WCAG 2.2 AA | machine-readable `contrastPairs`, двусторонний focus contrast, form/status paths | `AT-03`, `TP-03`, `TP-06`, `TP-07`, `TP-10`, `TP-14` |
| Targets минимум 44×44 | shared size token и computed measurement всех сцен/frames | `AT-02`, `AT-05`, `TP-08` |
| Telegram и browser используют один набор | шесть mode records, ThemeParams map, resolver trace и atomic fallback | `AT-02`, `AT-03`, `TP-01`—`TP-05`, `TP-15` |
| Telegram SDK изолирован | provider mapping остаётся data contract; SDK/globals отсутствуют | `AT-04`, `AT-06`, `TP-01`, `TP-15` |
| Manrope и ограниченный display font | Manrope в рабочем UI, Unbounded только wordmark; embedded provenance/license | `AT-01`, `AT-04`, `TP-12`, `TP-13` |
| Функциональные glow/motion | gradient только route/brand без content; normal/reduced contract | `AT-02`, `AT-03`, `AT-06`, `TP-09`, `TP-13` |
| Mobile и desktop preview | 6 сцен, compact/wide navigation, table→list, safe area и exact frames | `AT-05`, `AT-06`, `TP-02`—`TP-05`, `TP-08`, `TP-15` |
| Handoff доступен CB-53 | стабильные IDs/paths, capability link и отдельный handoff раздел | `DESIGN.md`, `docs/release-2/README.md`, `TP-15` |

## Font provenance и лицензия

Зафиксирован ограниченный claim `provenanceAndArtifactIntegrity`, а не
бит-в-бит воспроизводимость повторной компрессии:

- Manrope pinned raw input: `165420` bytes,
  SHA-256 `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`;
- Unbounded pinned raw input: `778272` bytes,
  SHA-256 `323b511be380c8d474ef030686b71aedde501f8d9cd46da558b7c40454372c3f`;
- embedded Manrope WOFF2: `38780` bytes,
  SHA-256 `c0a3d977e4938b656bb4a6de284228e74969a8eaf2543e71fdf4667e88b61429`;
- embedded Unbounded WOFF2: `155204` bytes,
  SHA-256 `c096d8236d81f98fe38e32f2d5ba42fb7dadb35c0b59f4bb779ec898a285d587`;
- observed environment: CPython `3.13.15`, FontTools `4.63.0`, Brotli `1.2.0`;
- полный OFL 1.1 и оба copyright notices встроены в preview;
- `bitReproducible=false` записан явно.

## Browser и ручная проверка

Финальный прогон выполнен в установленном Chrome `151.0.7922.138` через
Playwright с `file://` и отключёнными внешними зависимостями. Privacy-safe
evidence находится только в gitignored `tmp/CB-58-evidence/`.

Фактический результат повторного прогона после remediation:

- HTML `670479` bytes, load observation `366 ms`;
- `0` console errors, `0` page errors, `0` external requests;
- все 6 palette modes дали ожидаемый resolver trace;
- 114 live-state records проверены во всех 6 palettes; выполнено 2868 computed
  assertions, включая реальные primary pressed и destructive hover/pressed;
- проверены 11 разрешённых control projection tuples; обе несовместимые
  dark↔light попытки выбора preset отклонены;
- все 18 scene/frame measurements без horizontal overflow;
- undersized targets: `0`, измеренный минимум `44×44`;
- compact admin: list visible/table hidden; wide admin: table visible/list hidden;
- dialog удерживает focus на `Tab` и `Shift+Tab`; `Escape` возвращает focus
  trigger для dialog и sheet;
- form проходит `invalid → corrected → preview`, descriptions и counter
  `8 из 1200 символов` программно связаны, outcome публикуется через live
  region;
- preview override и системный `prefers-reduced-motion: reduce` дают
  `transform=none` и нулевую transition duration;
- forbidden/not-found имеют дословно одинаковую композицию; всего 9 system
  states, synthetic retry не заявляет ложный success;
- CDP accessibility tree содержит `main`, navigation, status и именованную
  icon-button; DOM scan: `0` unlabeled buttons, `0` unlabeled fields,
  `0` decorative SVG leaks, `3` live regions;
- 400% reflow проверен эквивалентом CDP: `1280×720` physical,
  `320×568` CSS, DPR `4`; page и preview overflow отсутствуют;
- ручной просмотр dark/light, compact/wide, form, dialog, reduced motion и
  system states не выявил hero/blob/sphere/glass/reveal или другого
  anti-AI-slop нарушения.

## Ограничения доказательств

- axe-core отсутствует в bundled runtime. Выполнены CDP accessibility-tree,
  native semantics и DOM checks, но совместимость с конкретным screen reader
  не заявляется;
- 400% проверен эквивалентом CDP device metrics, а не UI-командой zoom видимого
  Chrome; функционального расхождения не обнаружено;
- pre-CB-58 visual baseline отсутствует, поэтому pixel-regression comparison
  неприменим; выполнена ручная визуальная проверка без выдуманного baseline;
- отдельного low-end hardware/emulation profile не было; размер, browser build
  и наблюдаемое время записаны как факты, не как low-end benchmark;
- live Telegram, server deploy и production acceptance к CB-58 не относятся и
  не выполнялись.

## Автоматические gates

```text
uv run pytest -q --no-cov tests/documentation/test_release2_design_system.py
6 passed in 0.58s

uv run ruff format --check .
484 files already formatted

uv run ruff check --no-cache .
All checks passed!

git diff --check + untracked no-index diff-check
passed

uv run pytest -q
501 passed, 1 skipped in 397.59s; coverage 80.27%
```

Дополнительные bounded gates: внутренние Markdown links — `PASS` по 11 файлам;
secret-like scan — `PASS` по 15 изменённым/новым файлам без вывода содержимого;
tracked и untracked whitespace checks — `PASS`.

Browser evidence после последней регенерации:

```text
browser-state-contract.json
Chrome 151.0.7922.138; 114 live records; 6 palettes;
2868 computed assertions; 11 projection tuples;
negative dark/light preset selection rejected; 0 console/page/external errors

browser-qa.json
670479 bytes; 366 ms; 18 scene/frame measurements;
0 undersized targets; 0 horizontal overflow; focus trap/return green

browser-targeted.json
form invalid/corrected/preview green; counter 8 из 1200;
Space/Shift+Tab/system theme/reduced motion/fonts/AX tree green
```

## Release freeze и handoff

Результат локально готов к независимому final review, но этот отчёт не создаёт
`final-review.md` и не заменяет отдельный review stage. Commit, push и PR в этом
этапе не выполнялись.

Даже после успешного review ветка CB-58 не должна merge в `main` до завершения
CB-50 и фиксации Release 1 (`v1.0.0`). После снятия freeze CB-53 получает
`DESIGN.md`, JSON contract и preview как входные данные; production React
components и `PlatformBridge` реализуются там отдельно, без копирования demo
JavaScript из preview.
