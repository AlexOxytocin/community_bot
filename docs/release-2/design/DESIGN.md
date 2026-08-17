# Дизайн-система Community Bot — Release 2

**Версия контракта:** `1.0.0`

**Статус:** реализация CB-58

**Архитектурная основа:** [ADR-0014](../../adr/0014-multi-interface-release-2.md)

**Интерактивное доказательство:** [автономный preview](design-preview.html)
**Machine-readable источник:** [design-tokens.json](design-tokens.json)

## Назначение

Интерфейс помогает участнику закрытого сообщества быстро понять: что сейчас
нужно сделать, кому это помогает, в каком состоянии находится задача и какое
действие безопасно доступно. Это рабочая среда для ежедневной взаимопомощи, а
не landing page. Первый экран поэтому открывает каталог задач, а визуальная
выразительность живёт в маршруте, фокусе и одном локальном акценте.

## Направление

- **Purpose:** быстрое чтение задач, статусов, баланса и административных
  списков без изменения доменных правил Release 1.
- **Audience:** участники закрытого сообщества, авторы и исполнители задач,
  модераторы и администраторы; интерфейс должен выдерживать повторное ежедневное
  использование и длинный русский текст.
- **Tone:** технологичный, спокойный, собранный, человечный.
- **Memorable detail:** тонкая cyan→violet линия маршрута — ориентир прогресса,
  но не универсальная заливка кнопок или карточек.
- **Constraints:** WCAG 2.2 AA, проектная цель `44×44`, автономный preview,
  dark/light/system, Telegram theme как недоверенная подсказка, готовность к
  browser layout и отсутствие frontend runtime в CB-58.

## Источники и границы заимствования

Референс владельца дал исходные dark-neon primitives, Manrope/Unbounded и
характер cyan/violet. Композиция landing page, hero, сфера, большие отступы и
scroll reveal не переносятся. От Linear берётся task-first плотность, от Discord
— progressive disclosure и сохранение контекста, от Todoist — list-first mobile
representation. Названия, продуктовые modes и бизнес-правила этих продуктов не
заимствуются.

## Семантическая модель токенов

Компоненты читают только `semantic.shared.*` и выбранное resolver-ом дерево
`semantic.dark.color.*` либо `semantic.light.color.*`. `primitives` не являются
публичным component API. `system` — стратегия выбора, отдельного цветового
дерева у него нет. Все leaves имеют `$type`, `$value`, `description`; ссылки
разрешаются до primitive без циклов.

Mode-neutral слой покрывает typography, spacing, radius, shadow geometry,
sizes, breakpoints, motion и icons. Цветовые деревья dark/light имеют одинаковые
paths. Brand/route cyan-violet отделены от info/success/warning/danger/neutral.
Action fill всегда solid; gradient разрешён только brand/route без
информативного foreground.

## Темы и Telegram mapping

Resolver различает `modeId` и `baseSemanticMode`. Browser выбирает dark/light
через `prefers-color-scheme`. Telegram preset сначала заполняет отсутствующие
роли base palette, затем атомарно накладывает известные `ThemeParams` и запускает
все contrast pairs. При любой malformed или failed pair весь provider overlay
отбрасывается. Частичного смешанного fallback нет. Business status, role,
authorization и ownership никогда не выводятся из provider color.

Preview показывает безопасный `resolver-trace`: только preset ID, mode,
effective source и IDs непройденных pairs. Raw provider payload и пользовательские
данные туда не попадают. Получение theme/safe-area events остаётся единственной
границей будущего `PlatformBridge` в CB-53.

`contracts.controlProjection` разрешает controls только canonical tuples.
Browser отключает Telegram preset; explicit Telegram theme показывает presets
только той же color scheme; `system` допускает оба scheme, но каждый результат
всё равно совпадает ровно с одним из шести `paletteModes`. Несогласованный
theme/preset tuple нельзя выбрать через UI.

## Типографика

Manrope используется для рабочего текста, controls, таблиц и чисел. Unbounded
разрешён только в коротком wordmark. Screen title: `24/30` compact и `30/36`
wide; section heading `20/26`; card heading `16/22 semibold`; body `16/24`;
label `14/20 semibold`; meta `13/18`. Длинный русский текст переносится и не
уменьшает hit area.

## Layout и responsive

- compact `<600`: bottom navigation, одноколоночный catalog, admin list;
- medium `600–1023`: больше inline space, но та же информационная модель;
- wide `>=1024`: side navigation, application canvas до `1200px`, table view;
- readable column ограничена `720px`;
- встроенные доказательные frames: `320×568`, `390×844`, `1440×900`;
- safe-area применяется к shell/sticky actions через semantic variables;
- table и compact list представляют один набор synthetic объектов.

## Accessibility

Baseline — WCAG 2.2 Level AA: normal text `>=4.5:1`, large text и meaningful
UI cues `>=3:1`, без округления. Проектная минимальная цель `44×44` строже AA.
Native HTML предшествует ARIA; inputs имеют видимые labels и связанные
suggestions; icon-only button имеет доступное имя; status не кодируется одним
цветом. Dialog удерживает focus, закрывается Escape и возвращает focus trigger.
При 400% zoom смысловой контент не требует горизонтального scroll.
`prefers-reduced-motion` и override отключают transform/decorative transitions —
это обязательное проектное усиление, соответствующее AAA Animation from
Interactions, а не новая декларация общего уровня AAA.

## Motion и polish

Допустимы только короткие `120/180/240ms` переходы, поясняющие state. Infinite,
scroll-triggered, parallax и reveal motion запрещены. Glow применяется к focus,
current route или краткому подтверждению, но не ко всем surfaces.

## Anti-AI-slop gate

Запрещены centered marketing hero, blobs/сфера, gradient на большинстве
buttons/cards, универсальный glassmorphism, cards внутри cards, pill radius у
обычных inputs/dialogs, Unbounded в body, emoji вместо icon system и анимация
без информационной функции. На локальный action cluster — не больше одного
высокохромного акцента.

## Компонентный контракт

`componentInventory` — единственный список. `previewRequired` обязан иметь
DOM-case для каждого variant/state; `documentedOnly` остаётся точной
спецификацией, а не обещанием «когда-нибудь дорисовать». Ни один компонент не
вычисляет баланс, разрешённый переход или право — он только показывает готовое
server state и доступное действие.

Для всех state-record-backed preview cases preview содержит 114 живых specimens.
Каждый помечен точным `componentStateTokens.recordId`, а resolver проецирует его
token paths в computed background/foreground/border и дополнительные
focus/icon/indicator/message/progress/action roles. Metadata matrix без
визуального потребителя не считается доказательством state contract.

Синтетические task examples следуют D-018/D-032: member S показывает `3`
кредита и `15–40` минут, community M — автора «Сообщество», `4` кредита и
`40–75` минут; description limit равен `1200`, категория взята из утверждённого
DB-справочника. Preview не вводит собственную экономику или справочники.


<a id="component-app-shell"></a>
### `app-shell`

Coverage: `previewRequired`. Variants/states: `compact/default`, `wide/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-top-bar"></a>
### `top-bar`

Coverage: `previewRequired`. Variants/states: `compact/default`, `wide/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-bottom-navigation"></a>
### `bottom-navigation`

Coverage: `previewRequired`. Variants/states: `compact/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-side-navigation"></a>
### `side-navigation`

Coverage: `previewRequired`. Variants/states: `wide/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-page-header"></a>
### `page-header`

Coverage: `documentedOnly`. Variants/states: `compact/default`, `wide/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-back-action"></a>
### `back-action`

Coverage: `documentedOnly`. Variants/states: `default/default`, `default/hover`, `default/focusVisible`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-breadcrumbs"></a>
### `breadcrumbs`

Coverage: `documentedOnly`. Variants/states: `wide/default`, `wide/current`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-tabs"></a>
### `tabs`

Coverage: `previewRequired`. Variants/states: `default/default`, `default/selected`, `default/focusVisible`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-segmented-control"></a>
### `segmented-control`

Coverage: `previewRequired`. Variants/states: `default/default`, `default/selected`, `default/focusVisible`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-route-progress"></a>
### `route-progress`

Coverage: `previewRequired`. Variants/states: `default/completed`, `default/current`, `default/upcoming`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-sticky-action-region"></a>
### `sticky-action-region`

Coverage: `previewRequired`. Variants/states: `telegram-safe-area/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-button"></a>
### `button`

Coverage: `previewRequired`. Variants/states: `primary/default`, `primary/hover`, `primary/pressed`, `primary/focusVisible`, `primary/disabled`, `primary/loading`, `destructive/default`, `destructive/hover`, `destructive/pressed`, `destructive/focusVisible`, `destructive/disabled`, `destructive/loading`, `iconOnly/default`, `iconOnly/hover`, `iconOnly/pressed`, `iconOnly/focusVisible`, `iconOnly/disabled`, `iconOnly/loading`, `secondary/default`, `secondary/hover`, `secondary/pressed`, `secondary/focusVisible`, `secondary/disabled`, `secondary/loading`, `tertiary/default`, `tertiary/hover`, `tertiary/pressed`, `tertiary/focusVisible`, `tertiary/disabled`, `tertiary/loading`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-link"></a>
### `link`

Coverage: `documentedOnly`. Variants/states: `inline/default`, `inline/hover`, `inline/focusVisible`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-menu-action"></a>
### `menu-action`

Coverage: `documentedOnly`. Variants/states: `default/default`, `default/hover`, `default/focusVisible`, `default/disabled`, `destructive/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-toggle"></a>
### `toggle`

Coverage: `previewRequired`. Variants/states: `default/unchecked`, `default/checked`, `default/focusVisible`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-checkbox"></a>
### `checkbox`

Coverage: `previewRequired`. Variants/states: `default/unchecked`, `default/checked`, `default/focusVisible`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-radio"></a>
### `radio`

Coverage: `previewRequired`. Variants/states: `default/unchecked`, `default/checked`, `default/focusVisible`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-inline-notice"></a>
### `inline-notice`

Coverage: `previewRequired`. Variants/states: `info/default`, `success/default`, `warning/default`, `danger/default`, `neutral/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-toast"></a>
### `toast`

Coverage: `previewRequired`. Variants/states: `info/default`, `success/default`, `warning/default`, `danger/default`, `polite/live`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-dialog"></a>
### `dialog`

Coverage: `previewRequired`. Variants/states: `standard/closed`, `standard/open`, `destructive/open`, `standard/focusContained`, `standard/focusReturned`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-bottom-sheet"></a>
### `bottom-sheet`

Coverage: `previewRequired`. Variants/states: `standard/closed`, `standard/open`, `standard/focusContained`, `standard/focusReturned`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-task-card"></a>
### `task-card`

Coverage: `previewRequired`. Variants/states: `compact-member/default`, `compact-community/default`, `compact-test/default`, `compact-member/selected`, `compact-member/loading`, `full-member/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-task-status-chip"></a>
### `task-status-chip`

Coverage: `previewRequired`. Variants/states: `info/default`, `success/default`, `warning/default`, `danger/default`, `neutral/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-task-state-timeline"></a>
### `task-state-timeline`

Coverage: `documentedOnly`. Variants/states: `compact/completed`, `compact/current`, `compact/upcoming`, `wide/completed`, `wide/current`, `wide/upcoming`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-slot-counter"></a>
### `slot-counter`

Coverage: `documentedOnly`. Variants/states: `available/default`, `full/default`, `closed/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-reward-badge"></a>
### `reward-badge`

Coverage: `documentedOnly`. Variants/states: `credit/default`, `experience/default`, `karma/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-time-size-badge"></a>
### `time-size-badge`

Coverage: `documentedOnly`. Variants/states: `time/default`, `size/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-member-list-item"></a>
### `member-list-item`

Coverage: `documentedOnly`. Variants/states: `compact/default`, `wide/default`, `longName/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-profile-summary"></a>
### `profile-summary`

Coverage: `previewRequired`. Variants/states: `default/default`, `longValue/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-avatar"></a>
### `avatar`

Coverage: `documentedOnly`. Variants/states: `initials/default`, `image/default`, `fallback/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-role-badge"></a>
### `role-badge`

Coverage: `documentedOnly`. Variants/states: `member/default`, `moderator/default`, `admin/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-karma-aggregate"></a>
### `karma-aggregate`

Coverage: `documentedOnly`. Variants/states: `positive/default`, `neutral/default`, `negative/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-balance-metric"></a>
### `balance-metric`

Coverage: `previewRequired`. Variants/states: `default/default`, `longValue/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-level-progress"></a>
### `level-progress`

Coverage: `previewRequired`. Variants/states: `default/default`, `longValue/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-stats-item"></a>
### `stats-item`

Coverage: `documentedOnly`. Variants/states: `default/default`, `longValue/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-ledger-row"></a>
### `ledger-row`

Coverage: `previewRequired`. Variants/states: `default/default`, `empty/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-leaderboard-row"></a>
### `leaderboard-row`

Coverage: `documentedOnly`. Variants/states: `default/default`, `currentMember/default`, `tied/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-data-table"></a>
### `data-table`

Coverage: `previewRequired`. Variants/states: `wide/default`, `wide/empty`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-admin-list"></a>
### `admin-list`

Coverage: `previewRequired`. Variants/states: `compact/default`, `compact/empty`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-form-field"></a>
### `form-field`

Coverage: `previewRequired`. Variants/states: `field/default`, `field/invalid`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-text-field"></a>
### `text-field`

Coverage: `previewRequired`. Variants/states: `default/default`, `default/hover`, `default/focused`, `default/invalid`, `default/disabled`, `default/filled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-text-area"></a>
### `text-area`

Coverage: `previewRequired`. Variants/states: `default/default`, `default/hover`, `default/focused`, `default/invalid`, `default/disabled`, `default/filled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-select"></a>
### `select`

Coverage: `previewRequired`. Variants/states: `default/default`, `default/hover`, `default/focused`, `default/invalid`, `default/disabled`, `default/filled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-search-field"></a>
### `search-field`

Coverage: `documentedOnly`. Variants/states: `default/empty`, `default/filled`, `default/focused`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-date-time-field"></a>
### `date-time-field`

Coverage: `documentedOnly`. Variants/states: `default/default`, `default/filled`, `default/invalid`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-material-field"></a>
### `material-field`

Coverage: `documentedOnly`. Variants/states: `default/default`, `default/filled`, `default/invalid`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-character-counter"></a>
### `character-counter`

Coverage: `previewRequired`. Variants/states: `default/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-reward-stepper"></a>
### `reward-stepper`

Coverage: `documentedOnly`. Variants/states: `credit/default`, `credit/minimum`, `credit/maximum`, `credit/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-performer-stepper"></a>
### `performer-stepper`

Coverage: `documentedOnly`. Variants/states: `default/default`, `default/minimum`, `default/maximum`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-task-size-select"></a>
### `task-size-select`

Coverage: `documentedOnly`. Variants/states: `small/selected`, `medium/selected`, `large/selected`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-category-select"></a>
### `category-select`

Coverage: `documentedOnly`. Variants/states: `default/empty`, `default/filled`, `default/invalid`, `default/disabled`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-preview-confirmation"></a>
### `preview-confirmation`

Coverage: `previewRequired`. Variants/states: `default/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

<a id="component-system-state"></a>
### `system-state`

Coverage: `previewRequired`. Variants/states: `loading/default`, `empty/default`, `offline/default`, `expired/default`, `forbidden/default`, `notFound/default`, `conflict/default`, `featureDisabled/default`, `genericError/default`.

Anatomy: semantic container, readable label/content slot и только заявленные actions. Responsive: сохраняет identity и порядок чтения; compact representation не меняет domain meaning. Accessibility: native role, accessible name/state, visible focus и `44×44` для интерактивных targets.

## Системные состояния и privacy

Loading имеет текстовый cue, а не один skeleton. Empty предлагает безопасное
следующее действие. Offline/expired/conflict не имитируют success. Forbidden и
not-found имеют одинаковую внешнюю композицию и не подтверждают существование
ресурса. Generic error показывает только синтетический reference без payload.

## Font provenance и лицензия

Оба исходника получены из pinned snapshot `google/fonts`
`352f6b7d9d6cc4fa9e242b931291d31b21a6dc84` по direct raw URL и проверены до
subsetting: Manrope `165420` bytes / SHA-256
`d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`,
Unbounded `778272` bytes / SHA-256
`323b511be380c8d474ef030686b71aedde501f8d9cd46da558b7c40454372c3f`.
Subset выполнен `fonttools[woff]==4.63.0`; observed environment: CPython
`3.13.15`, Brotli `1.2.0`. Точные команды, output sizes/hashes и upstream
commits находятся в `contracts.fontProvenance`.

Гарантия — `provenanceAndArtifactIntegrity`, `bitReproducible=false`.
Output hash доказывает конкретные embedded bytes, но не обещает идентичный
stream в другой environment. Полный OFL 1.1 и оба copyright notices встроены в
preview в `font-license-notice`.

## Handoff в CB-53

CB-53 импортирует versioned JSON и переносит semantic/component contract в один
React SPA, не копируя demo JavaScript preview. Любой Telegram-specific доступ
идёт через `PlatformBridge`; browser mode работает без provider globals.
Production auth, API, routing, feature flags и реальные данные не определяются
этой дизайн-системой. Release freeze сохраняется: даже прошедшая CB-58 не
сливается в `main` до закрытия CB-50 и фиксации `v1.0.0`.
