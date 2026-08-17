# CB-58 — эскалация после двух непройденных plan review

## Основание

CB-58 относится к уровню 3. Два последовательных независимых review полного
планового пакета завершились `Status: changes_requested`. По R-008 роли
`plan-reviewer`, `docs/AGENT_WORKFLOW.md` и правилам проекта до реализации
обязательны этот артефакт и один последний консолидированный remediation-цикл.

Review-файлы остаются read-only. Runtime, дизайн-артефакты, Jira, Git remote и
другие worktree в рамках remediation не изменяются. Если третье независимое
review не даст `Status: approved`, работа останавливается для решения владельца,
а не уходит в четвёртый обычный цикл.

## История review

### Попытка 1 — `changes_requested`

Первый review подтвердил scope и визуальное направление, но потребовал:

- завершить non-color semantic aliases для передачи в CB-53;
- формализовать `contrastPairs`, states, Telegram fallback и gradient policy;
- связать component inventory со стабильными preview samples и evidence;
- вынести ручную/browser проверку уровня 3 в отдельный `test-plan.md`;
- закрепить font provenance/license/subsetting sources;
- выполнить сравнение трёх daily-use интерфейсов;
- отделить WCAG AA baseline от reduced-motion project enhancement/AAA.

Первый remediation добавил `semantic.shared`, contrast record schema,
sample IDs, 15 test scenarios, pinned font sources, три сравнения и правильную
accessibility классификацию.

### Попытка 2 — `changes_requested`

Второй review признал большую часть первой правки, но обнаружил четыре
оставшиеся системные неоднозначности:

1. `modeId` был смешан с `baseSemanticMode`: Telegram mode IDs подставлялись в
   paths, где существуют только `dark|light`; state → token paths перечислены
   не полностью.
2. Grouped samples не доказывали наличие каждого компонента, а inventory не был
   исчерпывающе разделён на `preview-required` и `documented-only`.
3. `320×568`, resolver trace и `table→detail` в test plan не совпадали с
   фактически обещанными preview controls/samples.
4. Pinned input и FontTools не делали WOFF2 output bit-reproducible, потому что
   raw acquisition и compressor/runtime environment не были полностью
   закреплены; claim оказался сильнее доказательства.

## Корневые причины

- План последовательно уточнялся prose-добавлениями, а не от одного
  нормализованного machine contract. Из-за этого одинаковое слово `mode`
  использовалось для user choice, base palette и provider test environment.
- Component inventory и sample matrix проектировались с разных сторон:
  inventory как человеческий каталог, samples как визуальные сцены. Между ними
  не было единственного проверяемого множества component IDs.
- Test plan расширил проверку полезными действиями, но часть действий не была
  сначала добавлена в preview contract. Получился drift «проверяем то, чего не
  обещали построить».
- Font section смешал три разных свойства: provenance input, integrity готового
  artifact и bit-for-bit reproducibility. Pinned FontTools без pinned Brotli и
  runtime доказывает первые два свойства, но не третье.
- Первый remediation проверял наличие ключевых терминов и связей, но не выполнил
  отрицательную симуляцию: «может ли тест разрешить каждый path/component/action
  без домысла». Именно этот тест теперь становится центральным.

## Единый способ закрытия

Последний цикл использует одну формальную модель и синхронно проецирует её во
все три плановых документа:

1. Ввести `contracts.paletteModes`: `modeId` только идентифицирует test/runtime
   environment; `baseSemanticMode` принимает только `dark|light`; provider
   overlay атомарно принимается либо полностью заменяется base palette. Все
   contrast paths подставляют только `baseSemanticMode`.
2. Ввести `contracts.componentInventory` с точным `all`, непересекающимися
   `previewRequired`/`documentedOnly`, one-component records и
   `requiredVariantStateCases`. HTML доказывает каждый case через
   `data-component-id`, `data-variant`, `data-state`.
3. Сделать preview contract единственным источником test capabilities:
   добавить frame `320×568`, обязательный read-only resolver diagnostics output
   и удалить незаявленный `table→detail` переход.
4. Зафиксировать pinned raw URLs и input hash gate, но честно назвать font
   гарантию `provenanceAndArtifactIntegrity`: output SHA-256 связывает embedded
   bytes с проверенным artifact, а `bitReproducible=false` прямо признаёт
   незакреплённые compressor/runtime bytes.
5. Обновить automated/evidence mapping по тем же IDs и выполнить отрицательный
   self-check множеств, paths и test capabilities до третьего review.

## Критерии выхода из эскалации

- для каждого `modeId` однозначно известны `baseSemanticMode`, provider preset,
  provider result, effective palette и fallback result; ни один Telegram ID не
  образует semantic JSON path;
- каждый обязательный action/form/status/navigation state имеет точный
  machine-readable semantic path record и contrast threshold;
- exact component set совпадает с inventory, partition полон и не пересекается;
  каждый preview-required component/variant/state case доказуем `AT-05`;
- built-in frames, resolver diagnostics и все TP steps совпадают без скрытых
  возможностей; незаявленного detail sample нет;
- font source открывается по pinned raw URL, input hash проверяется до subset,
  embedded output проверяется по записанному hash; bit reproducibility не
  заявляется;
- `plan.md`, `plan-source-context.md`, `test-plan.md` проходят полный local
  self-check без placeholders, broken internal references, trailing whitespace
  и изменений вне CB-58;
- третье и последнее независимое review возвращает `Status: approved`. Иначе
  CB-58 остаётся без реализации до решения владельца.
