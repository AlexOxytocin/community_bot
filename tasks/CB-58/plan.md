# CB-58 — план реализации дизайн-системы Release 2

## Цель

Зафиксировать рабочую дизайн-систему Community Bot до начала CB-53: один
семантический набор токенов должен одинаково обслуживать Telegram Mini App и
будущий browser mode, поддерживать `dark`, `light` и `system`, учитывать
Telegram theme/safe area и давать проверяемые компоненты для ежедневных
сценариев сообщества.

Задача относится к уровню 3 по ADR-0004. Она насыщена визуальными,
продуктовыми, Telegram- и accessibility-источниками, а её результат становится
сквозным контрактом для всех frontend-задач CB-53 — CB-55. Ошибка здесь
размножится на весь интерфейс, поэтому обязательны `plan-source-context.md`,
независимый `plan-review.md` и после реализации — `implementation-report.md` и
`final-review.md`.

Новый ADR не требуется: CB-58 реализует уже принятое решение ADR-0014 о
semantic design tokens, `PlatformBridge`, light/dark themes и browser readiness,
не меняя архитектурную форму приложения или технологический стек.

## Результат задачи

После реализации в репозитории появятся:

1. `docs/release-2/design/DESIGN.md` — каноническое визуальное направление,
   правила тем, типографика, layout, состояния, компоненты, accessibility,
   motion, anti-patterns и контракт передачи в CB-53.
2. `docs/release-2/design/design-tokens.json` — versioned machine-readable
   источник primitives, semantic modes, component contracts, Telegram mapping
   и проверяемых contrast pairs.
3. `docs/release-2/design/design-preview.html` — один автономный интерактивный
   HTML-файл без build step, CDN, API, Telegram SDK и сетевых зависимостей.
4. `tests/documentation/test_release2_design_system.py` — автоматический
   контракт JSON, ссылок токенов, тем, contrast, 44×44 targets,
   self-contained preview и отсутствия drift между JSON и embedded preview.
5. Обновлённый `docs/release-2/README.md` со ссылкой на дизайн-систему и
   закрытым дизайн-вопросом CB-58.
6. Заполненный `tasks/CB-58/test-plan.md` — отдельный ручной/browser протокол
   уровня 3 с actual results, evidence и deviations по стабильным scenario IDs.

Preview встраивает канонический JSON в
`<script type="application/json" id="design-tokens">` и применяет его inline
JavaScript. Автоматический тест сравнивает embedded JSON с отдельным
`design-tokens.json`, поэтому автономность не создаёт второй ручной источник
токенов.

## Визуальное направление

### Название и задача интерфейса

Направление: **«Технологичная взаимопомощь»**.

Интерфейс ежедневно помогает участнику быстро понять четыре вещи:

- что сейчас требует его действия;
- в каком состоянии находится задание или обязательство;
- какой экономический результат уже зафиксирован;
- какое действие безопасно и доступно именно ему.

Тон — спокойный, собранный, доверительный и технически точный. Визуальный язык
может быть узнаваемым, но не должен превращать каталог заданий в marketing hero.

### Аудитория

- active-участники, которые регулярно сканируют каталог, обязательства,
  баланс, прогресс и уведомления;
- авторы и исполнители, которым нужно без двусмысленности различать draft,
  action-required, review, dispute и terminal outcomes;
- модераторы и администраторы, работающие с более плотными списками и
  privacy-sensitive решениями;
- будущие browser users на wide viewport, использующие те же сценарии без
  Telegram-specific визуальной зависимости.

### Запоминающаяся деталь

Тонкая cyan→violet **линия маршрута** связывает этапы задания: создание,
публикацию, принятие, результат и проверку. Она используется как локальный
ориентир в timeline/progress и коротком brand mark, но не заменяет текстовые
статусы и не служит универсальным фоном карточек.

### Что берём из референса

- почти чёрный canvas `#05060A` и слоистые поверхности `#0C0F17` / `#12151F`
  как стартовые dark primitives;
- основной текст `#F0F3FA`, вторичный `#A9B1C4`, приглушённый `#8891A6` после
  проверки каждой смысловой пары;
- cyan `#2EE6D6`, violet `#8B5CF6` и violet text `#A78BFA` как brand primitives;
- Manrope как основной рабочий шрифт;
- тонкие borders, локальный glow, ясный focus и ограниченные акцентные
  переходы `120–240ms`;
- ритм, основанный на 4 px, и небольшое число осмысленных radius.

Исходный `cyan → violet` gradient сохраняется для линии маршрута и малых
brand-акцентов без foreground content. Primary button всегда получает
однотонный semantic color: это убирает двусмысленность contrast по площади
gradient и делает правило одинаковым для browser и Telegram provider themes.

### Что не переносим

- hero-композицию, декоративную сетевую сферу и большие landing-отступы;
- oversized display typography на рабочих экранах;
- полноэкранные декоративные radial gradients и scroll reveal;
- gradient, glow или glass effect на каждой кнопке и карточке;
- marketing navigation вместо прикладного shell;
- card-inside-card как основной способ построения иерархии.

## Контракт токенов

### Формат

`design-tokens.json` получает `schemaVersion: "1.0.0"` и пять верхнеуровневых
разделов:

- `primitives` — raw шкалы, которые нельзя потреблять из component CSS;
- `semantic.shared` — mode-neutral aliases для typography, spacing, radius,
  shadow, size, breakpoint, motion и icons;
- `semantic.dark.color` и `semantic.light.color` — одинаковое дерево цветовых
  ролей для двух разрешённых modes;
- `platform.telegram` — mapping необязательных Telegram `ThemeParams`, safe
  area, synthetic presets и fallback paths;
- `contracts` — alias/palette/state policies, contrast pairs, gradient policy,
  exact component inventory, minimum sizes, font provenance и preview samples.

Каждый token leaf использует поля `$type`, `$value` и `description`, а
`contracts` содержит обычные versioned JSON records. Ссылка записывается как
`{path.to.token}` и всегда разрешается до primitive без циклов. Компонент CB-53
может читать только `semantic.shared.*` и выбранный resolver-ом
`semantic.dark.color.*` либо `semantic.light.color.*`; прямые ссылки на
`primitives.*`, `platform.*` и другой mode из component CSS запрещены.
`system` не имеет собственного semantic subtree: resolver возвращает строку
`dark|light`, после чего все paths становятся однозначными.

### Точное дерево mode-neutral aliases

Raw paths и обязательные aliases фиксируются до реализации:

| Primitive family | Потребляемые semantic paths |
|---|---|
| `primitives.font.family.*`, `weight.*`, `size.*`, `lineHeight.*`, `letterSpacing.*` | composite tokens `semantic.shared.typography.screenTitleCompact`, `.screenTitleWide`, `.sectionHeading`, `.cardHeading`, `.body`, `.label`, `.meta`, `.button`, `.number`, `.wordmark` |
| `primitives.space.{1,2,3,4,5,6,8,10,12,16}` | `semantic.shared.spacing.pageInlineCompact`, `.pageInlineWide`, `.sectionStack`, `.clusterGap`, `.cardPadding`, `.formFieldGap`, `.controlInlineGap`, `.denseRowGap` |
| `primitives.radius.{2,3,4,5,pill}` | `semantic.shared.radius.control`, `.card`, `.sheet`, `.panel`, `.pill` |
| `primitives.shadowGeometry.{none,surface,raised,overlay,focusGlow}` | geometry composites `semantic.shared.shadow.surface`, `.raised`, `.overlay`, `.focusGlow`; цвет берётся отдельно из `semantic.{baseSemanticMode}.color.shadow.*` |
| `primitives.size.*` | `semantic.shared.size.targetMinimum`, `.controlHeight`, `.topBarHeight`, `.bottomNavigationHeight`, `.contentReadableMax`, `.contentCanvasMax` |
| `primitives.breakpoint.{compactEnd,mediumStart,wideStart}` | `semantic.shared.breakpoint.compactEnd`, `.mediumStart`, `.wideStart` |
| `primitives.motion.duration.*`, `.easing.*`, `.distance.*` | `semantic.shared.motion.durationFast`, `.durationStandard`, `.durationDeliberate`, `.easingStandard`, `.easingEmphasized`, `.distanceState`; reduced resolver переопределяет duration/distance в `0ms/0px` |
| `primitives.icon.{grid20,grid24,stroke175}` | `semantic.shared.icon.compactGrid`, `.standardGrid`, `.strokeDefault` |

Typography composites содержат точные `fontFamily`, `fontWeight`, `fontSize`,
`lineHeight` и `letterSpacing` references. Responsive значение не прячется в
компоненте: например, screen title явно выбирает
`typography.screenTitleCompact` ниже `breakpoint.wideStart` и
`typography.screenTitleWide` начиная с него. `contracts.aliasPolicy` хранит
`allowedComponentPrefixes`, `forbiddenComponentPrefixes` и это правило
проверяется по CSS custom properties preview.

### Обязательные semantic color roles

`semantic.dark.color` и `semantic.light.color` обязаны иметь один и тот же
exact leaf set:

- `background.{canvas,surface,raised,overlay,header,navigation}`;
- `text.{primary,secondary,muted,inverse,link,accent}`;
- `border.{subtle,default,strong,separator}` и `focus.ring`;
- `selection.{background,foreground}`, `scrim`,
  `skeleton.{base,highlight}`, `chart.{primary,secondary,tertiary}`;
- `shadow.{surface,raised,overlay,focusGlow}`;
- `brand.{gradientStart,gradientEnd}` и
  `route.{gradientStart,gradientEnd,current,completed,upcoming}`;
- `navigation.item.<state>.{background,foreground,border}` для states
  `default,hover,pressed,focusVisible,selected,disabled`;
- `action.<variant>.<state>.{background,foreground,border,progress}` для
  variants `primary,secondary,tertiary,destructive,iconOnly` и states
  `default,hover,pressed,focusVisible,disabled,loading`;
- `form.field.<state>.{background,foreground,border,placeholder,message}` для
  states `default,hover,focused,invalid,disabled,filled`;
- `form.choice.<state>.{background,foreground,border,indicator}` для states
  `unchecked,checked,focusVisible,disabled`;
- `data.card.<state>.{background,foreground,border,skeleton}` для states
  `default,selected,loading`;
- `overlay.{background,foreground,border}`;
- `status.<variant>.{background,text,icon,border}` для variants
  `info,success,warning,danger,neutral`;
- `system.<variant>.{background,text,icon,border,action}` для variants
  `loading,empty,offline,expired,forbidden,notFound,conflict,featureDisabled,
  genericError`.

Указанные brace-списки — требование к развёрнутым leaves, а не допустимый JSON
с wildcard. `AT-01` сравнивает literal path set dark/light и падает при любом
пропуске или лишнем mode-only leaf.

### Полный state → semantic path contract

`contracts.componentStateTokens` — массив без pattern expansion в runtime.
Каждый record имеет `recordId`, `family`, `variantId`, `stateId` и object
`tokenPaths`, где допустимы только поля `background`, `foreground`, `border`,
`icon`, `indicator`, `placeholder`, `message`, `progress`, `action`,
`focusRing`; каждое
поле содержит exact template `semantic.{baseSemanticMode}.color...` либо
explicit `null`. Обязательное разворачивание:

| Family | Variants | States | Exact token root / дополнительные paths |
|---|---|---|---|
| `navigationItem` | `bottomNavigation`, `sideNavigation`, `tabs`, `segmentedControl` | `default,hover,pressed,focusVisible,selected,disabled` | `background/foreground/border` → `color.navigation.item.<state>.{background,foreground,border}`; только `focusVisible` получает `focusRing` → `color.focus.ring`, остальные поля `null` |
| `button` | `primary,secondary,tertiary,destructive,iconOnly` | `default,hover,pressed,focusVisible,disabled,loading` | `background/foreground/border/progress` → `color.action.<variant>.<state>.{background,foreground,border,progress}`; только `focusVisible` получает `focusRing` → `color.focus.ring`, остальные поля `null` |
| `formField` | `textField,textArea,select,searchField` | `default,hover,focused,invalid,disabled,filled` | `background/foreground/border/placeholder/message` → `color.form.field.<state>.{background,foreground,border,placeholder,message}`; states `focused` и `invalid` получают `focusRing` → `color.focus.ring`, остальные поля `null` |
| `choice` | `toggle,checkbox,radio` | `unchecked,checked,focusVisible,disabled` | `background/foreground/border/indicator` → `color.form.choice.<state>.{background,foreground,border,indicator}`; только `focusVisible` получает `focusRing` → `color.focus.ring`, остальные поля `null` |
| `status` | `info,success,warning,danger,neutral` | `default` | `background/foreground/icon/border` → `color.status.<variant>.{background,text,icon,border}`; остальные поля `null` |
| `routeProgress` | `route` | `completed,current,upcoming` | `indicator` → `color.route.<state>`; `foreground` → `color.text.primary` для `completed` и `current`, `color.text.secondary` для `upcoming`; остальные поля `null` |
| `dataCard` | `taskCard` | `default,selected,loading` | `background/foreground/border/indicator` → `color.data.card.<state>.{background,foreground,border,skeleton}` (`skeleton` записывается в `indicator`); остальные поля `null` |
| `overlay` | `dialog,bottomSheet` | `open,destructive` | `background/foreground/border` → `color.overlay.{background,foreground,border}`; destructive CTA ссылается отдельно на `button.destructive.*`, остальные поля `null` |
| `systemState` | `loading,empty,offline,expired,forbidden,notFound,conflict,featureDisabled,genericError` | `default` | `background/foreground/icon/border/action` → `color.system.<variant>.{background,text,icon,border,action}`; остальные поля `null` |

Например, record `button.secondary.pressed` обязан содержать literal paths
`semantic.{baseSemanticMode}.color.action.secondary.pressed.background`,
`.foreground`, `.border`, `.progress`; `focusRing` равен `null`. Record
`button.secondary.focusVisible` использует одноимённые state leaves и
`semantic.{baseSemanticMode}.color.focus.ring`. Идентификатор состояния в
contrast/sample contract обязан ссылаться на `recordId`; свободные строки
`corresponding roles` запрещены. `AT-03` сравнивает полный literal set
`variant × state`, разрешает paths только после получения `baseSemanticMode` и
не создаёт ни одного token name самостоятельно.

Cyan/violet резервируются для brand, route, focus, selected и primary action.
`success` получает самостоятельный green, `warning` — amber, `danger` —
red/coral, `info` — blue. Ни cyan, ни violet не обозначают одновременно
успех, ошибку или разные конфликтующие доменные состояния.

Dark palette начинается с цветов референса. Light palette проектируется
отдельно, а не инверсией dark: для текста, ссылок, focus и actions используются
более тёмные contrast-safe variants. Raw accent, который не проходит WCAG на
светлой поверхности, остаётся декоративным primitive и не назначается
semantic text/control role.

### Общие шкалы

- spacing: `4, 8, 12, 16, 20, 24, 32, 40, 48, 64` CSS px;
- radii: `8` для compact controls, `12` для inputs/buttons, `16` для cards и
  sheets, `20` только для крупных самостоятельных panels, `999` только для
  chips/pills;
- minimum interactive target: `44×44` CSS px во всех режимах;
- breakpoints: compact `<600`, medium `600–1023`, wide `>=1024` CSS px;
- content widths: readable column до `720`, application canvas до `1200` CSS px;
- motion: fast `120ms`, standard `180ms`, deliberate `240ms`; никакого
  бесконечного или scroll-triggered motion;
- icon grid: `20` и `24` CSS px внутри target `44`, stroke примерно `1.75`,
  inline SVG без emoji как системных иконок.

Все перечисленные числа существуют сначала в `primitives`, а UI получает их
только через точные aliases из таблицы выше. Добавлять новый raw размер прямо в
component CSS нельзя: сначала вводится primitive, затем semantic role и rationale
в `DESIGN.md`.

### Machine-readable contrast contract

`contracts.contrastPairs` — массив explicit records без wildcard и без
неявного выбора threshold. Каждый record обязан иметь:

```json
{
  "id": "text-primary-on-canvas",
  "foregroundPath": "semantic.{baseSemanticMode}.color.text.primary",
  "backgroundPath": "semantic.{baseSemanticMode}.color.background.canvas",
  "adjacentPaths": [],
  "modeIds": ["browserDark", "browserLight", "telegramDark", "telegramLight",
    "telegramFallbackDark", "telegramFallbackLight"],
  "stateTokenRecordIds": [],
  "minRatio": 4.5,
  "purpose": "normalText"
}
```

`modeId` никогда не подставляется в token path. Test сначала находит record в
`contracts.paletteModes`, получает `baseSemanticMode=dark|light`, строит
effective palette и только затем подставляет `{baseSemanticMode}`. Для каждого
`adjacentPaths` ratio считается отдельно. Contract test не округляет ratio до
сравнения и запрещает неизвестные paths/mode IDs/state records, duplicate IDs,
`minRatio <= 0` и пустой `purpose`.

Минимальный исчерпывающий набор records:

- normal text: primary/secondary/muted/link на canvas, surface, raised, header,
  navigation и overlay — `4.5`; large display — `3.0` только для typography
  roles, которые по размеру действительно соответствуют large text;
- navigation item default/hover/pressed/focusVisible/selected/disabled:
  foreground/background `4.5`, meaningful border/selection cue `3.0`, disabled
  `3.0` как project enhancement;
- все пять action variants `primary,secondary,tertiary,destructive,iconOnly`
  во всех states `default,hover,pressed,focusVisible,disabled,loading`:
  foreground против fill `4.5`, meaningful fill/border/progress против каждой
  adjacent surface `3.0`; disabled foreground/fill — проектное усиление `3.0`,
  хотя inactive controls исключены из обязательного WCAG contrast;
- focus ring — `3.0` одновременно против внутреннего control fill и внешних
  canvas/surface/raised через `adjacentPaths`;
- form-field states `default,hover,focused,invalid,disabled,filled` для всех
  четырёх input variants и choice states
  `unchecked,checked,focusVisible,disabled` для toggle/checkbox/radio — text
  `4.5`, meaningful border/indicator/message/state cue `3.0`;
- info/success/warning/danger/neutral: text против status background `4.5`,
  icon и border против background/adjacent surface `3.0`;
- data card default/selected/loading, overlays и все system variants: readable
  foreground `4.5`, meaningful border/icon/selection cue `3.0`; skeleton motion
  не является единственным loading cue;
- Telegram accepted dark/light presets и намеренно неполные low-contrast
  presets: все применимые records повторяются после mapping; low-contrast
  provider обязан дать `telegramFallbackDark|Light`, а не pass по raw value.

### Однозначный palette resolver

`contracts.paletteModes` содержит ровно шесть records. Поля каждого record:
`modeId`, `baseSemanticMode`, `platform`, `providerPresetId`, `providerPolicy`,
`expectedProviderResult`, `expectedEffectivePaletteSource` и
`expectedFallbackResult`.

| `modeId` | Base | Platform | Preset | Policy | Expected provider result | Expected effective source / fallback |
|---|---|---|---|---|---|---|
| `browserDark` | `dark` | browser | `null` | `none` | `notApplicable` | `semantic.dark.color` / `none` |
| `browserLight` | `light` | browser | `null` | `none` | `notApplicable` | `semantic.light.color` / `none` |
| `telegramDark` | `dark` | Telegram | `telegram-dark-valid` | `atomicValidatedOverlay` | `providerAccepted` | `semantic.dark.color+provider:telegram-dark-valid` / `none` |
| `telegramLight` | `light` | Telegram | `telegram-light-valid` | `atomicValidatedOverlay` | `providerAccepted` | `semantic.light.color+provider:telegram-light-valid` / `none` |
| `telegramFallbackDark` | `dark` | Telegram | `telegram-dark-low-contrast` | `atomicValidatedOverlay` | `providerRejected` | `semantic.dark.color` / `fullSemanticFallback` |
| `telegramFallbackLight` | `light` | Telegram | `telegram-light-low-contrast` | `atomicValidatedOverlay` | `providerRejected` | `semantic.light.color` / `fullSemanticFallback` |

`system` — только UI resolver input. В browser он выбирает
`browserDark|browserLight` по `prefers-color-scheme`; в Telegram —
`telegramDark|telegramLight` по нормализованному `colorScheme`. Low-contrast
fallback IDs доступны только preview/test controls и не приходят из runtime.

Provider policy одна — `atomicValidatedOverlay`:

1. mapper проверяет все переданные известные values как `#RRGGBB`; любой
   malformed value даёт `providerRejected`;
2. missing values заполняются base semantic palette;
3. известные provider values накладываются на candidate palette по exact map;
4. все `contrastPairs` для mode выполняются на candidate;
5. если каждая пара проходит, принимается весь candidate; если хотя бы одна не
   проходит, отбрасывается весь overlay и effective palette становится exact
   base palette. Частичного role fallback нет.

`platform.telegram.themeParamMap` фиксирует exact role targets:

| Telegram key | Semantic role suffix |
|---|---|
| `bg_color` | `background.canvas` |
| `secondary_bg_color` | `background.surface` |
| `section_bg_color` | `background.raised` |
| `header_bg_color` | `background.header` |
| `bottom_bar_bg_color` | `background.navigation` |
| `text_color` | `text.primary` |
| `hint_color` | `text.muted` |
| `subtitle_text_color` | `text.secondary` |
| `section_header_text_color`, `accent_text_color` | `text.accent` |
| `link_color` | `text.link` |
| `button_color` | все `action.primary.<state>.background` кроме `disabled` |
| `button_text_color` | все `action.primary.<state>.foreground` кроме `disabled` |
| `destructive_text_color` | все `action.destructive.<state>.foreground` кроме `disabled` |
| `section_separator_color` | `border.separator` |

Map не имеет status/authorization targets. Multiple provider keys, ведущие в
одну role, запрещены кроме явно указанной пары section/accent: при наличии обоих
приоритет имеет `accent_text_color`, что хранится в record `precedence`.

Gradient policy также находится в `contracts.gradientPolicy` и не зависит от
человеческой трактовки: `actionFillPolicy` равен `solidOnly`; под text, icons,
controls и status gradient запрещён. Cyan→violet разрешён только между
`semantic.{baseSemanticMode}.color.route.{gradientStart,gradientEnd}` и
`.brand.{gradientStart,gradientEnd}`, где нет
информативного foreground; route всегда дублируется label/icon/shape. Таким
образом contrast action проверяется по одной фактической solid fill, а не по
условным stops. Любое последующее разрешение gradient под контент потребует
новой версии contract с проверкой каждого пиксельного цвета фактической заливки.

`contracts.fontProvenance` содержит по record на Manrope/Unbounded с полями
`family`, `distributionCommit`, `sourceUrl`, `sourceSha256`, `sourceBytes`,
`upstreamUrl`, `upstreamCommit`, `licenseId`, `licenseUrl`, `copyright`, а в
`subset` — `tool`, `toolVersion`, `compressorVersionObserved`,
`runtimeVersionObserved`, `unicodeRanges`, `command`, `outputSha256`,
`outputBytes`, `format`, `noticeElementId`,
`reproductionClaim: "provenanceAndArtifactIntegrity"` и
`bitReproducible: false`. Input facts фиксированы в source context; output
hash/size связывают проверенный локальный WOFF2 с embedded data URL. Равенство
байтов при повторном subsetting в иной environment не заявляется.

### Typography

- Manrope — body, screen headings, form labels, buttons, tables и numbers;
- Unbounded — только короткий wordmark/brand accent, не body и не длинный title;
- рабочая шкала: screen title `24/30` compact и `30/36` wide, section heading
  `20/26`, card heading `16/22 semibold`, body `16/24`, label `14/20 semibold`,
  meta `13/18`;
- относительные units и корректный wrap обязательны; интерфейс не обрезает
  длинный русский текст ради фиксированной высоты;
- preview включает лицензированные Manrope/Unbounded WOFF2 subsets как data URL
  и фиксирует pinned source, upstream commit, input/output SHA-256, tool/version,
  команду subsetting, glyph ranges, copyright и OFL notice в `DESIGN.md`.
  Полный OFL 1.1 и оба copyright notices также встраиваются в автономный HTML
  как human-readable `font-license-notice`; production packaging остаётся CB-53.

## Темы и платформы

### `dark`, `light`, `system`

`dark` и `light` являются двумя полностью разрешёнными semantic palettes.
`system` — стратегия выбора, а не третий набор случайных значений:

- в browser mode используется `prefers-color-scheme`;
- в Telegram mode `PlatformBridge` передаёт нормализованные `colorScheme` и
  `themeParams`, после чего semantic mapper выбирает базовую light/dark palette;
- изменение темы пересчитывает aliases без перезагрузки страницы;
- отсутствующие, некорректные или недостаточно контрастные provider colors
  получают fallback из выбранной semantic palette.

Preview имеет переключатели `dark|light|system`, `browser|telegram` и четыре
точных Telegram preset IDs из `contracts.paletteModes`. Он не импортирует
Telegram SDK и только демонстрирует provider mapping.

### Telegram mapping

Mapping покрывает актуальные необязательные `ThemeParams`:

- `bg_color`, `secondary_bg_color`, `section_bg_color`, `header_bg_color`,
  `bottom_bar_bg_color`;
- `text_color`, `hint_color`, `subtitle_text_color`,
  `section_header_text_color`, `accent_text_color`, `link_color`;
- `button_color`, `button_text_color`, `destructive_text_color`,
  `section_separator_color`.

Provider values считаются visual hints, а не безусловными токенами. Mapper
строго выполняет описанную выше `atomicValidatedOverlay`: один effective
palette — либо весь contrast-safe candidate, либо exact base semantic palette.
Он никогда не выводит из Telegram accent бизнес-статус или authorization и не
оставляет частично принятый provider набор.

Safe area использует semantic variables для device и content inset с fallback
на `env(safe-area-inset-*)`/`0px`. CB-58 определяет имена и визуальное поведение,
а CB-53 реализует получение `themeChanged`, `safeAreaChanged`,
`contentSafeAreaChanged` и viewport events исключительно внутри
`PlatformBridge`.

### Browser readiness

- те же токены и компоненты работают без Telegram globals;
- compact layout использует bottom navigation, wide layout — side navigation;
- hover-стили активируются только при `(hover: hover)`;
- таблицы и административные списки имеют responsive list representation;
- прямой URL, auth и данные не моделируются дизайн-системой;
- отсутствие browser authentication остаётся ограничением ADR-0014, а не
  визуальным состоянием, которое можно обойти.

## Инвентарь компонентов

Единственный источник состава — `contracts.componentInventory`. Он содержит
`all` и ровно один record на каждый ID с полями `componentId`, `displayName`,
`group`, `coverage`, `sampleIds`, `documentationAnchor` и
`requiredVariantStateCases`. `coverage` принимает только
`previewRequired|documentedOnly`.

### Exact component set

`contracts.componentInventory.all` содержит ровно 53 ID:

- shell/navigation: `app-shell`, `top-bar`, `bottom-navigation`,
  `side-navigation`, `page-header`, `back-action`, `breadcrumbs`, `tabs`,
  `segmented-control`, `route-progress`, `sticky-action-region`;
- actions/feedback: `button`, `link`, `menu-action`, `toggle`, `checkbox`,
  `radio`, `inline-notice`, `toast`, `dialog`, `bottom-sheet`;
- community data: `task-card`, `task-status-chip`, `task-state-timeline`,
  `slot-counter`, `reward-badge`, `time-size-badge`, `member-list-item`,
  `profile-summary`, `avatar`, `role-badge`, `karma-aggregate`,
  `balance-metric`, `level-progress`, `stats-item`, `ledger-row`,
  `leaderboard-row`, `data-table`, `admin-list`;
- forms: `form-field`, `text-field`, `text-area`, `select`, `search-field`,
  `date-time-field`, `material-field`, `character-counter`, `reward-stepper`,
  `performer-stepper`, `task-size-select`, `category-select`,
  `preview-confirmation`;
- system: `system-state`.

`previewRequired` содержит ровно 31 ID:

`app-shell`, `top-bar`, `bottom-navigation`, `side-navigation`, `tabs`,
`segmented-control`, `route-progress`, `sticky-action-region`, `button`,
`toggle`, `checkbox`, `radio`, `inline-notice`, `toast`, `dialog`,
`bottom-sheet`, `task-card`, `task-status-chip`, `profile-summary`,
`balance-metric`, `level-progress`, `ledger-row`, `data-table`, `admin-list`,
`form-field`, `text-field`, `text-area`, `select`, `character-counter`,
`preview-confirmation`, `system-state`.

`documentedOnly` содержит ровно оставшиеся 22 ID:

`page-header`, `back-action`, `breadcrumbs`, `link`, `menu-action`,
`task-state-timeline`, `slot-counter`, `reward-badge`, `time-size-badge`,
`member-list-item`, `avatar`, `role-badge`, `karma-aggregate`, `stats-item`,
`leaderboard-row`, `search-field`, `date-time-field`, `material-field`,
`reward-stepper`, `performer-stepper`, `task-size-select`, `category-select`.

Для `previewRequired` exact `requiredVariantStateCases` равен объединению cases
этого component ID из `contracts.previewSamples` ниже. Для `documentedOnly`
exact cases не оставляются будущему автору `DESIGN.md`, а фиксируются здесь:

| Component ID | Exact `variantId/stateId` cases |
|---|---|
| `page-header` | `compact/default`, `wide/default` |
| `back-action` | `default/default`, `default/hover`, `default/focusVisible`, `default/disabled` |
| `breadcrumbs` | `wide/default`, `wide/current` |
| `link` | `inline/default`, `inline/hover`, `inline/focusVisible` |
| `menu-action` | `default/default`, `default/hover`, `default/focusVisible`, `default/disabled`, `destructive/default` |
| `task-state-timeline` | `compact/completed`, `compact/current`, `compact/upcoming`, `wide/completed`, `wide/current`, `wide/upcoming` |
| `slot-counter` | `available/default`, `full/default`, `closed/default` |
| `reward-badge` | `credit/default`, `experience/default`, `karma/default` |
| `time-size-badge` | `time/default`, `size/default` |
| `member-list-item` | `compact/default`, `wide/default`, `longName/default` |
| `avatar` | `initials/default`, `image/default`, `fallback/default` |
| `role-badge` | `member/default`, `moderator/default`, `admin/default` |
| `karma-aggregate` | `positive/default`, `neutral/default`, `negative/default` |
| `stats-item` | `default/default`, `longValue/default` |
| `leaderboard-row` | `default/default`, `currentMember/default`, `tied/default` |
| `search-field` | `default/empty`, `default/filled`, `default/focused`, `default/disabled` |
| `date-time-field` | `default/default`, `default/filled`, `default/invalid`, `default/disabled` |
| `material-field` | `default/default`, `default/filled`, `default/invalid`, `default/disabled` |
| `reward-stepper` | `credit/default`, `credit/minimum`, `credit/maximum`, `credit/disabled` |
| `performer-stepper` | `default/default`, `default/minimum`, `default/maximum`, `default/disabled` |
| `task-size-select` | `small/selected`, `medium/selected`, `large/selected`, `default/disabled` |
| `category-select` | `default/empty`, `default/filled`, `default/invalid`, `default/disabled` |

`AT-05` сравнивает эти literal pairs, а не только непустоту массива. Это делает
partition исчерпывающим по component ID, variant и state даже для компонентов,
которые пока документируются без интерактивного preview.

`AT-05` содержит literal expected set из этого плана и доказывает:

- records IDs равны `all`, без duplicate/unknown/missing;
- union двух coverage partitions равен `all`, intersection пуст;
- у `previewRequired` есть минимум один sample и все required cases в DOM;
- у `documentedOnly` `sampleIds=[]`, но есть anchor и непустой documented
  variants/states contract в `DESIGN.md`;
- grouped sample допустим только через `componentRequirements[]`; строка label
  не считается доказательством компонента.

UI-группы статусов соответствуют существующим domain states, но не создают
новые transitions. `task-status-chip` всегда содержит label и icon/shape;
forbidden/not-found используют одинаковую privacy-safe композицию.

## Интерактивный preview

Первый viewport показывает не hero и не перечень возможностей, а рабочий
`AppShell` с каталогом заданий. Далее идут foundation и component states.

Preview содержит синтетические обезличенные данные и шесть стабильных сцен:

1. `scene-catalog` — mobile task catalog с filters, task cards и route line;
2. `scene-task-form` — creation form с normal, focused, invalid и disabled;
3. `scene-profile-economy` — level progress, balance и ledger rows;
4. `scene-admin` — wide administrative list и compact representation;
5. `scene-system-states` — loading, empty, offline, expired, forbidden,
   not-found, conflict, feature-disabled и generic error;
6. `scene-foundations-actions` — tokens, action states, feedback и overlays.

Интерактивные controls:

- theme `dark|light|system`;
- platform `browser|telegram` и preset selector
  `telegram-dark-valid|telegram-light-valid|telegram-dark-low-contrast|
  telegram-light-low-contrast`;
- frame `320×568|390×844|1440×900` — все три являются built-in controls;
- motion `normal|reduced`;
- component state selector и открытие/закрытие dialog/sheet.

Read-only diagnostic output `data-diagnostic-id="resolver-trace"` обязателен и
показывает только synthetic contract data: `modeId`, `baseSemanticMode`,
`providerPresetId|null`, `providerResult`, `fallbackResult`,
`effectivePaletteSource` и `failedContrastPairIds[]`. Он не показывает raw
Telegram payload и не является production component. `AT-02` проверяет поля и
ожидаемые значения каждого из шести `paletteModes`; `TP-03` использует именно
этот output, а не скрытую console trace.

Файл работает при открытии через `file://`, не делает `fetch`, не использует
analytics/localStorage, не отправляет данные и не зависит от backend.

### Трассируемая матрица preview samples

Каждый record из `contracts.previewSamples` содержит `id`, `sceneIds`,
`componentRequirements[]` и `evidenceScenarioIds`. Каждый component requirement
имеет exact `componentId` и `requiredCases[]`; case содержит `variantId`,
`stateId` и `stateTokenRecordId|null`. В HTML каждый case доказывается element
с тем же `data-sample-id`, `data-component-id`, `data-variant`, `data-state` и
`data-state-token-record-id`; последнее равно literal record ID либо `none` для
JSON `null`.

| Stable sample ID | Component requirements и обязательные cases | Scene | Evidence |
|---|---|---|---|
| `sample-shell-navigation` | `app-shell`: compact/default, wide/default; `top-bar`: compact/default, wide/default; `bottom-navigation`: compact/default; `side-navigation`: wide/default; `sticky-action-region`: telegram-safe-area/default | `scene-catalog`, `scene-admin` | `AT-05`, `TP-02`, `TP-04`, `TP-15` |
| `sample-tabs-segmented` | `tabs`, `segmented-control`: default/default, default/selected, default/focusVisible | `scene-catalog` | `AT-05`, `TP-02`, `TP-06` |
| `sample-button-primary` | `button` variant primary: default, hover, pressed, focusVisible, disabled, loading | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-06`, `TP-08`, `TP-10` |
| `sample-button-secondary-tertiary` | `button` variants secondary и tertiary: default, hover, pressed, focusVisible, disabled, loading для каждой | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-06`, `TP-08`, `TP-10` |
| `sample-button-destructive` | `button` variant destructive: default, hover, pressed, focusVisible, disabled, loading | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-06`, `TP-10` |
| `sample-button-icon` | `button` variant iconOnly: default, hover, pressed, focusVisible, disabled, loading | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-06`, `TP-08`, `TP-14` |
| `sample-task-card` | `task-card`: compact-member/default, compact-community/default, compact-test/default, compact-member/selected, compact-member/loading, full-member/default | `scene-catalog` | `AT-05`, `TP-02`, `TP-03`, `TP-13` |
| `sample-route-progress` | `route-progress`: default/completed, default/current, default/upcoming | `scene-catalog` | `AT-05`, `TP-02`, `TP-10`, `TP-13` |
| `sample-status-set` | `task-status-chip`, `inline-notice`: variants info/success/warning/danger/neutral, state default для каждой | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-10`, `TP-14` |
| `sample-form-field` | `form-field`: field/default, field/invalid; `text-field`, `text-area`, `select`: default, hover, focused, invalid, disabled, filled; `character-counter`: default/default; `preview-confirmation`: default/default | `scene-task-form` | `AT-03`, `AT-05`, `TP-03`, `TP-07`, `TP-14` |
| `sample-choice-controls` | `toggle`, `checkbox`, `radio`: default/unchecked, default/checked, default/focusVisible, default/disabled | `scene-task-form` | `AT-03`, `AT-05`, `TP-06`, `TP-07` |
| `sample-feedback` | `inline-notice`: все пять status variants/default; `toast`: info/default, success/default, warning/default, danger/default, polite/live | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-07`, `TP-10`, `TP-14` |
| `sample-dialog` | `dialog`: standard/closed, standard/open, destructive/open, standard/focusContained, standard/focusReturned | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-03`, `TP-06`, `TP-14` |
| `sample-bottom-sheet` | `bottom-sheet`: standard/closed, standard/open, standard/focusContained, standard/focusReturned | `scene-foundations-actions` | `AT-03`, `AT-05`, `TP-03`, `TP-06` |
| `sample-profile-economy` | `profile-summary`, `balance-metric`, `level-progress`: default/default и longValue/default; `ledger-row`: default/default, empty/default | `scene-profile-economy` | `AT-05`, `TP-08`, `TP-13` |
| `sample-admin-list` | `data-table`: wide/default, wide/empty; `admin-list`: compact/default, compact/empty | `scene-admin` | `AT-05`, `TP-04`, `TP-05`, `TP-08` |
| `sample-system-states` | `system-state`: variants loading/empty/offline/expired/forbidden/notFound/conflict/featureDisabled/genericError, state default | `scene-system-states` | `AT-03`, `AT-05`, `TP-11`, `TP-14` |

Binding `stateTokenRecordId` также фиксирован, а не выводится автором теста:

- canonical record ID равен `<family>.<variantId>.<stateId>` ровно для records
  из таблицы `componentStateTokens`;
- `bottom-navigation`, `side-navigation`, `tabs`, `segmented-control` ссылаются
  соответственно на `navigationItem.bottomNavigation.*`,
  `.sideNavigation.*`, `.tabs.*`, `.segmentedControl.*`; button cases —
  `button.*`; route —
  `routeProgress.route.*`; task-card states — `dataCard.taskCard.*` независимо
  от compact/full и origin variant;
- task status, notice и toast visual variants ссылаются на
  `status.<variant>.default`;
  form inputs — `formField.<inputVariant>.<state>`; choice controls —
  `choice.<componentId>.<state>`; overlay mapping exact:
  `dialog standard/open` → `overlay.dialog.open`,
  `dialog destructive/open` → `overlay.dialog.destructive`,
  `bottom-sheet standard/open` → `overlay.bottomSheet.open`;
  system variants — `systemState.<variant>.default`;
- explicit `null` разрешён только для layout/content cases `app-shell`,
  `top-bar`, `sticky-action-region`, `form-field`, `character-counter`,
  `preview-confirmation`, profile/economy/table/list cases и невидимых/
  behavioral overlay cases `closed`, `focusContained`, `focusReturned`, а также
  невизуального live-region case `toast polite/live`.

Таблица является человекочитаемой проекцией expanded JSON records, а не
заменяет их. `AT-05` проверяет каждый required case и его
`stateTokenRecordId`; layout/content-only cases используют explicit `null`, а
не пропуск поля. Если component/variant/state отсутствует, test падает; если
интерактивное поведение не доказано, соответствующий `TP-*` остаётся
незакрытым.

## Accessibility contract

- WCAG 2.2 AA: normal text `>=4.5:1`, large text `>=3:1`, meaningful control,
  focus и graphical state cues `>=3:1`; значения проверяются без округления;
- проектный minimum target `44×44` CSS px строже базового WCAG AA и обязателен
  для button, icon button, tabs, chips с действием и navigation;
- focus-visible — отдельная контрастная линия минимум 2 px с offset, а не только
  glow или изменение цвета;
- semantic native HTML используется раньше ARIA; у каждого интерактивного
  sample проверяются accessible name, role и value, `div`/`span`-buttons
  запрещены;
- status, validation и selection не кодируются одним цветом;
- все inputs имеют видимый label; help/error связаны семантически;
- icon-only controls имеют текстовое accessible name, meaningful SVG скрывает
  декоративные paths, а динамические outcomes объявляются через подходящий
  `aria-live` без повторного чтения всей страницы;
- preview полностью проходим клавиатурой, dialog удерживает focus и возвращает
  его инициатору; menu/sheet также возвращают focus trigger, `Escape` закрывает
  неопасный overlay;
- действие не может зависеть только от drag/swipe, если нет равнозначного
  single-pointer/keyboard control;
- errors не только называют проблему, но и дают конкретный способ исправления;
- при 400% zoom, эквивалентном reflow до ширины 320 CSS px, смысловой контент не требует
  горизонтального скролла;
- baseline заявляется как WCAG 2.2 Level AA; `prefers-reduced-motion: reduce` и
  preview override обязательны как проектное усиление, соответствующее
  Animation from Interactions Level AAA, и отключают transform, parallax,
  scroll reveal и несущественные transitions;
- dark/light/system и Telegram fallback проверяются одинаковыми contrast pairs;
- длинные русские labels переносятся без overlap и изменения hit area.

## Anti-AI-slop gate

Реализация не проходит визуальное ревью, если присутствует хотя бы одно из
следующего без явного функционального обоснования:

- centered marketing hero вместо рабочего приложения в первом viewport;
- decorative blobs, сетевые сферы, parallax или reveal-on-scroll;
- cyan→violet gradient на большинстве buttons/cards;
- glow на неактивных поверхностях или несколько glow-слоёв ради украшения;
- glassmorphism как универсальная поверхность;
- cards внутри cards вместо spacing, headings и dividers;
- pill radius у inputs, dialogs и обычных cards;
- Unbounded в body, длинных screen headings, forms или tables;
- emoji вместо системного icon set;
- animation без информационной функции;
- описание возможностей внутри UI вместо ясных controls и states.

Отдельно проверяется визуальный бюджет: один высокохромный акцент на локальный
action cluster, gradient только в разрешённых `contracts` roles, glow только для
focus/current route/краткого подтверждения состояния.

## Шаги реализации

1. После `problem-escalation.md` получить третье и последнее независимое review
   полного пакета. Реализация разрешена только при `Status: approved`; очередной
   `changes_requested` останавливает задачу для решения владельца.
2. Утвердить `test-plan.md` вместе с планом; до реализации все поля actual
   остаются честно помечены `не выполнено`.
3. Создать `design-tokens.json` и сразу добавить contract tests для schema,
   aliases, themes, mappings, font provenance, contrast records, sample matrix
   и target size.
4. Создать `DESIGN.md`, зафиксировав purpose, audience, tone, semantic rules,
   component anatomy, responsive behavior, accessibility и anti-patterns.
5. Собрать автономный `design-preview.html` из embedded canonical tokens,
   inline CSS/JS/SVG и лицензированных inline font subsets.
6. Реализовать preview-required scenes/states по stable IDs без
   React, API, Telegram SDK и доменной логики.
7. Обновить `docs/release-2/README.md`, связав результат с ADR-0014 и handoff в
   CB-53.
8. Выполнить `AT-01`—`AT-06`, затем каждый `TP-01`—`TP-15`; заполнить actual,
   evidence и deviation, включая font size/open-time и anti-AI-slop review.
9. Создать `implementation-report.md` с доказательством каждого критерия Jira и
   независимый `final-review.md` уровня 3.
10. После `Status: approved` передать ветку по штатному маршруту commit → push →
   PR → CI/review → merge. Финальный Jira `Done` не выполняется автоматически.

## Автоматические проверки

### Целевой contract test

`uv run pytest tests/documentation/test_release2_design_system.py`

Он должен доказать шесть именованных групп assertions:

- `AT-01 schema-and-references`: JSON валиден, `schemaVersion` ожидаемая, все
  token references существуют, разрешаются без циклов и имеют type-compatible
  values;
- `AT-02 alias-and-platform-contract`: `semantic.shared` содержит точные
  typography/spacing/radius/shadow/size/breakpoint/motion/icon paths, dark/light
  color trees одинаковы, `system` только resolver; все шесть `paletteModes`
  имеют допустимый `baseSemanticMode`, preset/result/effective/fallback values,
  Telegram mapping полный, resolver diagnostics совпадает с records, component
  CSS не читает запрещённые prefixes;
- `AT-03 contrast-contract`: каждый explicit `contrastPair` имеет все поля,
  `modeIds`/state record/purpose/threshold; `componentStateTokens` содержит весь
  literal variant×state set и только существующие paths после подстановки
  `baseSemanticMode`; effective palettes и каждый adjacent ratio проходят без
  округления; atomic provider results совпадают, gradient policy равна
  `solidOnly`, cyan/violet не являются success/danger;
- `AT-04 assets-and-autonomy`: source/input SHA-256 и font provenance совпадают,
  acquisition использует pinned raw URLs и pre-subset hash gate; embedded WOFF2
  равен записанному output hash, содержит copyright/name metadata, HTML содержит
  OFL notice, а claim честно равен provenance/integrity с
  `bitReproducible=false`; embedded tokens равны внешнему JSON; отсутствуют
  external resources, `fetch`, XHR, service worker, storage и telemetry;
- `AT-05 component-partition-and-samples`: exact literal set из 53 IDs равен
  inventory records; partitions полны и не пересекаются; каждый из 31
  preview-required component и каждый required variant/state case существует
  в HTML с пятью data attributes и корректным literal
  `data-state-token-record-id`; documented-only records имеют DESIGN anchors и
  exact required cases; evidence IDs существуют;
- `AT-06 static-scope`: preview содержит built-in frames `320×568`, `390×844`,
  `1440×900`, resolver diagnostics, reduced-motion, mobile/wide и safe-area
  contracts; raw visual values не обходят semantic CSS variables, кроме
  документированных `transparent`, data URL и layout-only values; diff не
  вводит runtime/toolchain/Telegram SDK.

### Репозиторные gates

- `uv run ruff format --check .`;
- `uv run ruff check .`;
- `git diff --check`;
- проверка внутренних Markdown links добавленных/изменённых файлов;
- secret-like scan по diff без вывода потенциального секрета;
- проверка, что diff ограничен CB-58 и не добавляет `package.json`, runtime code,
  migrations или Telegram SDK.

## Browser и ручная матрица

Авторитетный исполняемый протокол находится в `tasks/CB-58/test-plan.md`.
Ниже — сводка обязательных frame/mode gates; steps, synthetic data, expected,
actual, evidence и deviations не дублируются и заполняются в test plan:

| Размер | Theme/platform | Test-plan evidence |
|---|---|---|
| `390×844` | Telegram dark | `TP-02`, `TP-06`, `TP-08`, `TP-15` |
| `390×844` | Telegram light и low-contrast preset | `TP-03`, `TP-07`, `TP-10` |
| `1440×900` | browser dark | `TP-04`, `TP-06`, `TP-13` |
| `1440×900` | browser light | `TP-05`, `TP-10`, `TP-13` |
| `320×568` built-in frame, zoom 100% | browser system | `TP-01`, `TP-08`, `TP-15` |
| browser viewport `1280×720`, zoom 400% | browser system | `TP-08` |

Дополнительные ручные сценарии:

1. пройти controls только `Tab`/`Shift+Tab`/`Enter`/`Space`/`Escape`;
2. переключить `dark → light → system` и убедиться, что все states меняются без
   перезагрузки и без flash нечитаемых цветов;
3. включить Telegram custom-theme preset с неполным и заведомо
   low-contrast набором — mapper обязан использовать semantic fallback;
4. включить reduced motion — layout не прыгает, transform и decorative motion
   отсутствуют;
5. увеличить zoom до 400% и проверить reflow до ширины 320 CSS px без
   горизонтального скролла смыслового контента;
6. измерить computed bounding boxes всех интерактивных samples: минимум 44×44;
7. проверить loading, empty, offline, expired, forbidden и stale conflict;
8. выполнить checklist `design-system` по color, typography, spacing,
   component consistency, responsive, themes, motion, accessibility,
   information density и polish;
9. выполнить anti-AI-slop gate из этого плана отдельным проходом.

Факты сначала записываются в `test-plan.md`, затем сводятся без завышения в
`implementation-report.md`. Скриншоты и computed measurements сохраняются по
правилам test plan в gitignored `tmp/CB-58-evidence/` и не становятся новым
каноническим источником.

## Критерии приёмки и доказательства

| Критерий CB-58 | JSON path / HTML sample | Automated | Browser/manual evidence |
|---|---|---|---|
| Палитра имеет роли | exact `semantic.{dark,light}.color.*`, `componentStateTokens`, `sample-status-set` | `AT-01`—`AT-03`, `AT-05` | `TP-02`—`TP-05`, `TP-10` |
| Cyan/violet не смешаны со status | `color.brand/route` отдельно от `color.status.*` | `AT-03` | `TP-10`, `TP-13` |
| WCAG 2.2 AA | `contracts.contrastPairs[*]`, focus/form/status samples | `AT-03`, `AT-05` | `TP-03`, `TP-06`, `TP-07`, `TP-10`, `TP-14` |
| Targets не меньше 44×44 | `semantic.shared.size.targetMinimum`, interactive samples | `AT-02`, `AT-05` | `TP-08` computed boxes |
| Один набор в Telegram/browser | `paletteModes`, `themeParamMap`, resolver diagnostics, `sample-shell-navigation` | `AT-02`, `AT-03`, `AT-05` | `TP-02`—`TP-05`, `TP-15` |
| Telegram SDK изолирован | mapping records; SDK отсутствует в HTML | `AT-04`, `AT-06` | `TP-01`, `TP-15` |
| Manrope рабочий, display ограничен | `semantic.shared.typography.*`, font provenance | `AT-01`, `AT-04` | `TP-12`, `TP-13` |
| Glow/motion функциональны | `semantic.shared.motion.*`, `gradientPolicy` | `AT-02`, `AT-03`, `AT-06` | `TP-09` (AAA enhancement), `TP-13` |
| Mobile и desktop preview | exact 53-component inventory, 31 preview-required IDs, scenes и три frame controls | `AT-05`, `AT-06` | `TP-02`—`TP-05`, `TP-08`, `TP-15` |
| Результат доступен CB-53 | canonical files, component/state IDs и Release 2 link | repo/link gate + `AT-05` | handoff section в `DESIGN.md` + `TP-15` |

## Риски и меры снижения

- **Custom Telegram theme ломает contrast.** `atomicValidatedOverlay` принимает
  только целиком прошедший candidate; любая format/contrast ошибка возвращает
  exact base palette, поэтому partial mixed state невозможен.
- **Light mode получается механической инверсией.** Light roles проектируются
  отдельно и проходят тот же автоматический набор pairs.
- **JSON и preview расходятся.** Preview содержит embedded canonical JSON, а
  test требует структурное равенство.
- **Design preview превращается в скрытый frontend prototype.** Только
  representative scenes и component anatomy; API, routing, auth, state manager
  и business actions запрещены.
- **Дизайн лендинга вытесняет рабочую плотность.** Первый viewport — task
  catalog; hero, sphere, scroll effects и landing spacing блокируются
  anti-slop gate.
- **44 px делает desktop чрезмерно рыхлым.** Визуальный glyph может быть 20–24
  px, но hit area сохраняется 44 px; плотность достигается grid/spacing, а не
  уменьшением цели.
- **Status palette конфликтует с brand.** Status colors имеют отдельные hue и
  обязательные text/icon labels.
- **Inline fonts раздувают preview.** Используются только необходимые
  Cyrillic/Latin WOFF2 subsets с зафиксированным источником; production bundle
  их не импортирует автоматически. Гарантия ограничена provenance/integrity:
  compressor/runtime фиксируются как observed facts, bit equality повторной
  сборки не заявляется.
- **CB-53 начинает раньше контракта.** Jira dependency сохраняется: CB-58
  блокирует полноценную CB-53 до merge результатов.
- **Browser readiness разрастается в отдельный продукт.** CB-58 ограничивается
  responsive layout, system theme и platform-neutral tokens; browser auth,
  public registration и новые navigation flows вне области.

## Рассмотренные альтернативы

- **Копировать landing UI.** Отклонено: он решает задачу привлечения внимания,
  а не повторяемой работы со статусами и транзакционными действиями.
- **Dark-only.** Отклонено Jira-критериями и будущим browser mode.
- **Безусловно использовать Telegram CSS variables.** Отклонено: custom theme
  может быть неполной/неконтрастной, а browser не имеет этих variables.
- **Только CSS custom properties без JSON.** Отклонено: нет versioned
  machine-readable контракта и проверки semantic completeness.
- **Storybook/React component library прямо в CB-58.** Отклонено: frontend
  toolchain ещё принадлежит CB-53; автономный HTML быстрее даёт независимый
  проверяемый визуальный контракт.
- **Ждать CB-53 и выбирать стиль по ходу экранов.** Отклонено: это создаст
  случайные hex, дубли компонентов и дорогую обратную унификацию.

## Вне области

- React/Vite setup и production component implementation;
- код `PlatformBridge` и обращение к Telegram WebApp SDK;
- API, auth/session, routing, feature flags и deployment;
- изменение domain states, ролей, экономики, privacy или moderation rules;
- полноценный browser UI, browser authentication и public registration;
- Figma/Canva library, marketing landing и иллюстрации;
- реализация всех экранов CB-53 — CB-55;
- live Telegram/deployment acceptance.

## Критерии готовности

- независимый `plan-review.md` содержит `Status: approved`;
- `problem-escalation.md` закрывает критерии последнего R-008 remediation; при
  третьем `changes_requested` процесс останавливается для решения владельца;
- шесть запланированных deliverables существуют; product outputs связаны из
  Release 2 docs, а task evidence остаётся в `tasks/CB-58/`;
- machine-readable tokens, DESIGN и preview не противоречат друг другу;
- `semantic.shared`, шесть `paletteModes`, полный state path set, exact
  component partition и preview cases проходят `AT-01`—`AT-06`;
- dark/light/system, Telegram mapping, WCAG AA, project enhancements, mobile/
  wide components и anti-AI-slop contract закрыты `TP-01`—`TP-15`;
- `test-plan.md` не содержит `не выполнено`: для каждого case заполнены actual,
  evidence и deviation;
- `implementation-report.md` сопоставляет каждый критерий Jira с доказательством;
- независимый `final-review.md` содержит `Status: approved`;
- ветка `task/CB-58` проходит штатный PR/CI/merge route либо в Jira фиксируется
  конкретный блокирующий gate.
