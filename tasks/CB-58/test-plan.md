# CB-58 — план проверки дизайн-системы Release 2

`community_bot.developer.test_plan.v1`

Этот артефакт был утверждён вместе с планом и исполнен после реализации.
Ни один case не считается успешным без наблюдаемого `Actual`, локального
privacy-safe `Evidence` и явно записанного `Deviation`.

## Предусловия

- независимый `plan-review.md` имеет `Status: approved`;
- существуют `DESIGN.md`, `design-tokens.json`, `design-preview.html` и
  `test_release2_design_system.py` по путям из `plan.md`;
- `AT-01`—`AT-06` и репозиторные gates завершились exit `0` до ручной проверки;
- preview открыт напрямую через `file://` в Chromium; номер сборки Chromium,
  ОС, device scale factor и фактический viewport записаны в evidence;
- DevTools Network включён до открытия: после reload нет сетевых запросов;
- browser cache отключён; системные dark/light и reduced-motion preferences
  доступны либо эквивалентно управляются DevTools emulation;
- используются только synthetic data ниже; Telegram SDK, Bot API, реальные
  профили, чаты, credentials, cookies и production backend не подключаются;
- проверяющий не редактирует DOM/CSS для получения желаемого результата;
  допустимы только controls самого preview и read-only DevTools inspection.

## Синтетические данные

- участники: `Участник А`, `Участница Б`, `Модератор В`; аватары — initials,
  без фотографий и Telegram identifiers;
- задания: member task «Помочь разобрать длинный список материалов для встречи»
  категории `Практическая помощь`, размера `S`, оценки `15–40 минут` и награды
  `3 кредита`; community task «Подготовить памятку для новичков» от автора
  `Сообщество`, категории `Практическая помощь`, размера `M`, оценки
  `40–75 минут` и награды `4 кредита`; явно маркированное test task
  «Проверить тестовый сценарий»;
- описание формы ограничено `1200` символами; preview использует только короткий
  synthetic текст и не содержит реальных данных сообщества;
- status set: info, success, warning, danger и neutral с label и icon/shape;
- economy: balance `25` credits, experience `50`, level `4`, три synthetic
  ledger rows и вариант empty ledger; UI отображает готовые server values и
  ничего не пересчитывает;
- длинная строка stress case: «Очень длинное русское название действия, которое
  должно переноситься без обрезания, наложения и уменьшения зоны нажатия»;
- `telegram-dark-valid`: canvas `#05060A`, text `#F0F3FA`, button `#2EE6D6`,
  button text `#05060A`, safe area `top=12/right=0/bottom=24/left=0`;
- `telegram-light-valid`: canvas `#F6F8FC`, text `#111827`, button `#0B7A75`,
  button text `#FFFFFF`, safe area `top=12/right=0/bottom=20/left=0`;
- `telegram-dark-low-contrast`: каждый переданный provider color `#101217`,
  `colorScheme=dark`; candidate обязан быть атомарно отклонён;
- `telegram-light-low-contrast`: каждый переданный provider color `#F7F7F7`,
  `colorScheme=light`; candidate обязан быть атомарно отклонён;
- отсутствующие provider fields в valid presets заполняются base palette;
  malformed либо failed contrast даёт полный, а не частичный fallback;
- privacy states forbidden/not-found имеют одинаковую внешнюю композицию;
  generic error показывает только synthetic request reference `REQ-0001`.

## Правила записи результата

Для каждого `TP-*` после выполнения заменить четыре поля:

- `Actual` — наблюдаемый результат с viewport/theme/platform и без оценочного
  «вроде работает»;
- `Evidence` — локальный filename screenshot/measurement либо точная запись
  DevTools/accessibility tree; одна ссылка может подтверждать несколько шагов,
  если это явно указано;
- `Deviation` — `нет` либо конкретное расхождение expected/actual с влиянием;
- `Result` — только `passed` или `failed`; `blocked` допускается лишь с точной
  внешней причиной и не считается закрытым gate.

Ниже записаны итоговые `Actual`, `Evidence`, `Deviation` и `Result` для каждого
выполненного case.

## Сценарии

### TP-01 — автономность, resolver и первый viewport

- **Samples:** `sample-shell-navigation`, все `scene-*`.
- **Шаги:** отключить сеть; открыть HTML через `file://`; reload; проверить
  Network/Console; переключить `dark → light → system`, затем изменить системную
  тему; пройти все scene controls и built-in frames
  `320×568 → 390×844 → 1440×900`.
- **Expected:** первый viewport — рабочий catalog, не hero; ноль network
  requests и runtime errors; все сцены доступны; `system` следует системной
  теме без собственного неполного palette; состояние меняется без reload и
  flash нечитаемых цветов.
- **Actual:** preview открылся через `file://` без console/page errors и внешних
  запросов; доступны 6 сцен и три точных frame. В browser/system смена
  эмулируемой системной схемы перевела resolver из `browserDark` в
  `browserLight` без reload.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-targeted.json`,
  `TP-01--320x568--browser-system--catalog.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-02 — Telegram dark compact

- **Samples:** `sample-shell-navigation`, `sample-tabs-segmented`,
  `sample-task-card`, `sample-route-progress`.
- **Шаги:** выбрать frame `390×844`, platform Telegram, preset
  `telegram-dark-valid`; открыть catalog; проверить top/bottom safe areas,
  sticky action, cards и navigation; прокрутить сцену целиком.
- **Expected:** bottom navigation и content не пересекают safe area; нет
  horizontal overflow; task hierarchy сканируется; route state имеет label и
  shape; targets не визуально обрезаны.
- **Actual:** `telegramDark` принял provider preset без fallback; compact
  catalog прошёл ручной просмотр и measurement: horizontal overflow отсутствует,
  safe-area padding и sticky navigation сохраняются, все targets не меньше
  `44×44`.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `TP-02--390x844--telegram-dark--catalog.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-03 — Telegram light и provider fallback

- **Samples:** `sample-task-card`, `sample-form-field`, `sample-dialog`,
  `sample-bottom-sheet`.
- **Шаги:** на built-in `390×844` применить `telegram-light-valid`, затем
  `telegram-light-low-contrast`; открыть form, dialog и sheet; прочитать
  `data-diagnostic-id="resolver-trace"`.
- **Expected:** для valid preset trace показывает `modeId=telegramLight`,
  `baseSemanticMode=light`, `providerResult=providerAccepted`,
  `fallbackResult=none`; для low-contrast —
  `modeId=telegramFallbackLight`, `providerResult=providerRejected`,
  `fallbackResult=fullSemanticFallback`, effective source
  `semantic.light.color` и непустой `failedContrastPairIds`. Candidate
  отбрасывается целиком; errors/destructive/overlays читаемы, status не
  выводится из provider accent.
- **Actual:** valid preset дал `telegramLight/providerAccepted/none`; low-contrast
  preset дал `telegramFallbackLight/providerRejected/fullSemanticFallback`,
  source `semantic.light.color` и непустой список failed pairs. Form, dialog и
  sheet читаемы в обоих вариантах. Control projection оставила для Telegram
  light только `telegram-light-valid` и `telegram-light-low-contrast`; попытка
  выбрать dark preset через automation отклонена браузером.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-03--390x844--telegram-light--form.png`,
  `TP-03--390x844--telegram-fallback-light--form.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-04 — browser dark wide

- **Samples:** `sample-shell-navigation`, `sample-admin-list`.
- **Шаги:** выбрать browser dark и built-in `1440×900`; проверить side
  navigation, application canvas, wide table, row/action hover и keyboard focus.
- **Expected:** content canvas ограничен token max width; table не растягивает
  строки бесконтрольно; hover существует только для hover-capable environment;
  focus не теряется; primary и destructive actions различимы.
- **Actual:** wide admin использует side navigation и table; compact list
  скрыт. Dark primary hover изменил background с `rgb(45, 212, 191)` на
  `rgb(94, 234, 212)`, focus видим, destructive action отделён собственной
  ролью.
- **Evidence:** `tmp/CB-58-evidence/browser-targeted.json`,
  `TP-04--1440x900--browser-dark--admin.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-05 — browser light wide

- **Samples:** `sample-admin-list`, `sample-status-set`.
- **Шаги:** выбрать browser light и `1440×900`; пройти административную сцену,
  status set и empty admin state; проверить computed foreground/background.
- **Expected:** light palette не является механической инверсией; все status
  roles различимы label/icon/shape; dense rows сохраняют rhythm и 44×44 actions;
  empty state предлагает безопасное следующее действие.
- **Actual:** light wide admin и status roles просмотрены вручную; table
  сохраняет ритм, actions имеют минимум `44×44`, статусы имеют текстовые labels
  и marker shape, empty-case присутствует в контракте и preview matrix.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `TP-05--1440x900--browser-light--admin.png`; `AT-05`.
- **Deviation:** нет.
- **Result:** passed.

### TP-06 — keyboard и focus management

- **Samples:** `sample-tabs-segmented`, `sample-button-primary`,
  `sample-button-secondary-tertiary`, `sample-button-destructive`,
  `sample-button-icon`, `sample-choice-controls`, `sample-dialog`,
  `sample-bottom-sheet`.
- **Шаги:** не использовать pointer; пройти `Tab`/`Shift+Tab`; активировать
  `Enter`/`Space`; открыть dialog/sheet; проверить focus containment, `Escape`
  и возврат focus trigger; повторить destructive confirmation без применения
  реального действия.
- **Expected:** логичный порядок; ни один control не недоступен; focus indicator
  видим и контрастен с обеих сторон; overlay не выпускает focus в фон,
  закрывается безопасно и возвращает focus инициатору.
- **Actual:** `Enter` и `Space` активируют native controls; `Tab` и `Shift+Tab`
  остаются внутри modal dialog. Focus ring равен
  `rgb(124, 58, 237) 0 0 0 3px`; `Escape` закрывает dialog/sheet и возвращает
  focus на `open-dialog`/`open-sheet`. Live specimens для action/form/choice,
  overlay и system focus states сверены с token paths во всех шести палитрах.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-targeted.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-06--390x844--dialog--visible-focus.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-07 — forms, errors и live feedback

- **Samples:** `sample-form-field`, `sample-choice-controls`, `sample-feedback`.
- **Шаги:** проверить labels/descriptions в accessibility tree; вызвать invalid
  state, исправить значение, отправить synthetic form; проверить error
  suggestion, counter и live announcement.
- **Expected:** label видим; help/error программно связаны; ошибка называет
  проблему и исправление; state не кодируется одним цветом; live region
  объявляет ровно изменившийся outcome без повторного чтения страницы.
- **Actual:** пустой критерий оставляет `aria-invalid=true`, публикует точную
  подсказку и получает focus; исправление меняет `aria-invalid=false` и live
  outcome на «Критерий принят.». Counter обновился до `8 из 1200 символов`, а
  preview открыл sheet с outcome «Предпросмотр готов.». Labels и descriptions
  программно связаны. Foreground/background/border/focus/message/indicator
  для всех form/choice state records совпали с token paths во всех шести
  палитрах.
- **Evidence:** `tmp/CB-58-evidence/browser-targeted.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-03--390x844--telegram-light--form.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-08 — targets, wrap и 400% reflow

- **Samples:** все interactive samples, включая
  `sample-button-secondary-tertiary`, `sample-profile-economy` и
  `sample-admin-list`.
- **Шаги:** программно снять computed bounding boxes; проверить минимум
  `44×44`; отдельно пройти built-in `320×568` при zoom 100%; затем установить
  browser viewport `1280×720` и zoom `400%` (эквивалент 320 CSS px); включить
  stress label и long numeric value; пройти все сцены.
- **Expected:** каждый target минимум 44×44 CSS px; смысловой content не требует
  horizontal scroll; labels/values переносятся без overlap, clipping или
  уменьшения hit area; допустимый scroll внутри явно обозначенной data region
  не скрывает основное действие.
- **Actual:** в 18 сочетаниях scene/frame минимальная измеренная зона равна
  `44×44`, undersized targets и horizontal overflow отсутствуют. Long label не
  clipped. При эквиваленте 400% получены CSS viewport `320×568`, DPR `4` и ноль
  page/preview overflow.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `TP-08--1280x720--400pct-equivalent--reflow.png`.
- **Deviation:** вместо UI-команды Chrome zoom использован эквивалент CDP device
  metrics (`1280×720` physical → `320×568` CSS, DPR `4`); функционального
  расхождения не обнаружено.
- **Result:** passed.

### TP-09 — reduced motion, проектное усиление AAA

- **Samples:** `sample-route-progress`, `sample-button-primary`,
  `sample-button-destructive`, `sample-dialog`, `sample-bottom-sheet`.
- **Шаги:** сравнить normal и preview reduced override; затем включить системный
  `prefers-reduced-motion: reduce`; инициировать state, route и overlay changes.
- **Expected:** transform, parallax, scroll reveal и decorative transitions
  отсутствуют; layout не прыгает; change остаётся понятен без animation. Это
  обязательный project gate/Level AAA enhancement поверх baseline AA.
- **Actual:** preview override дал `transitionDuration=0s, 0s` и
  `transform=none`; отдельная системная эмуляция
  `prefers-reduced-motion: reduce` дала `transitionDuration=0s` и
  `transform=none`. Layout и смысл состояния сохранились.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-targeted.json`,
  `TP-09--390x844--browser-dark--reduced-motion.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-10 — contrast, states и gradient policy

- **Samples:** `sample-button-primary`, `sample-button-destructive`,
  `sample-button-secondary-tertiary`, `sample-button-icon`,
  `sample-status-set`, `sample-form-field`, `sample-route-progress`.
- **Шаги:** для всех шести `modeId` пройти default/hover/pressed/disabled/
  destructive/focus/status states; сверить diagnostics, state record IDs и
  computed values с `contrastPairs`; проверить action backgrounds.
- **Expected:** все ratios равны/выше своего exact `minRatio` без округления;
  focus проходит против обеих adjacent colors; action fills только solid;
  cyan→violet есть лишь в route/brand без content; status не зависит только от
  hue.
- **Actual:** `AT-03` пересчитал все declared pairs во всех шести effective
  palettes без нарушения `minRatio`. Browser contract прошёл все 114 live-state
  records в каждой из 6 палитр и выполнил 2868 computed assertions для
  foreground/background/border/focus/indicator/message/progress/action paths.
  Критические значения: browser dark primary pressed `rgb(20, 184, 166)`,
  destructive hover `rgb(159, 18, 57)`, pressed `rgb(136, 19, 55)`; Telegram
  valid primary pressed использует provider values — `rgb(46, 230, 214)` dark и
  `rgb(11, 122, 117)` light. Action fills solid, route gradient не несёт
  content; status labels и markers не зависят только от hue.
- **Evidence:** `AT-03`; `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-10--390x844--telegram-fallback-dark--actions.png`,
  `TP-10--1440x900--browser-dark--live-state-contract.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-11 — системные и privacy-safe состояния

- **Samples:** `sample-system-states`.
- **Шаги:** последовательно показать loading, empty, offline, expired,
  forbidden, not-found, conflict, feature-disabled и generic-error; активировать
  retry/refresh там, где он предусмотрен.
- **Expected:** у каждого state есть ясный текст и доступное следующее действие;
  retry не показывает ложный success; forbidden/not-found визуально одинаковы;
  error не содержит payload/identity, только `REQ-0001`; loading не блокирует
  доступный cancel/back без причины.
- **Actual:** показаны ровно 9 системных состояний; forbidden/not-found имеют
  дословно одинаковую композицию, generic error содержит только `REQ-0001`.
  Нажатие synthetic retry не заявило ложный success. Все 9 systemState token
  records получили live specimens; их foreground/background/border/icon/action
  bindings программно совпали с semantic paths во всех 6 палитрах.
- **Evidence:** `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-targeted.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-11--390x844--browser-dark--system-states.png`.
- **Deviation:** нет.
- **Result:** passed.

### TP-12 — fonts, notice и вес автономного preview

- **Samples:** все typography samples.
- **Шаги:** при отключённой сети проверить loaded fonts; сравнить computed
  families/weights; найти embedded input/output SHA-256 provenance, оба
  copyright notices и полный OFL 1.1; записать размер HTML и время открытия на
  доступном low-end/mobile emulation profile.
- **Expected:** Manrope используется в рабочем UI, Unbounded только в wordmark;
  fallback не срабатывает; notice соответствует pinned raw source; embedded
  bytes равны записанному output SHA-256. Provenance record содержит observed
  runtime/Brotli и `bitReproducible=false`; повторение output bytes не
  заявляется. Размер/время записаны как факт; заметная задержка или crash —
  deviation и повод сократить subset.
- **Actual:** offline Chrome загрузил embedded Manrope и Unbounded; computed
  families совпали с назначением. HTML имеет размер `670479` bytes и открылся
  за `366 ms` в доступном headless profile. `AT-04` подтвердил оба input/output
  SHA-256, полный OFL, notices и `bitReproducible=false`.
- **Evidence:** `AT-04`; `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-targeted.json`.
- **Deviation:** отдельного low-end hardware/emulation profile в среде нет;
  записаны наблюдаемые размер, browser build и время без заявления low-end
  benchmark.
- **Result:** passed.

### TP-13 — visual direction и anti-AI-slop

- **Samples:** все scenes.
- **Шаги:** пройти десять измерений `design-system`; отдельно проверить первый
  viewport, hierarchy/density, nested cards, gradient/glow budget, radii,
  typography, motion и long labels на mobile/wide.
- **Expected:** направление «Технологичная взаимопомощь» узнаваемо через palette
  и route line; нет hero/blob/sphere/glass/reveal; один high-chroma accent на
  action cluster; Unbounded и glow ограничены; рабочая hierarchy важнее
  декоративности.
- **Actual:** вручную просмотрены dark/light compact/wide, form, dialog,
  reduced-motion и system states. Первый viewport рабочий; hierarchy плотная и
  утилитарная; gradient ограничен route line, Unbounded — wordmark; hero,
  blob/sphere, glass и reveal отсутствуют; long label не clipped.
- **Evidence:** набор screenshots `TP-01`—`TP-11` в
  `tmp/CB-58-evidence/`; `tmp/CB-58-evidence/browser-qa.json`.
- **Deviation:** pre-CB-58 visual baseline отсутствует, поэтому pixel-regression
  comparison неприменим; выполнена ручная anti-AI-slop проверка, но не заявлено
  сравнение с несуществующим baseline.
- **Result:** passed.

### TP-14 — accessibility tree: name, role, value

- **Samples:** `sample-button-icon`, `sample-status-set`, `sample-form-field`,
  `sample-feedback`, `sample-dialog`, `sample-system-states`.
- **Шаги:** read-only проверить accessibility tree; сверить name/role/value,
  heading/order, selected/disabled/expanded/invalid, descriptions и live region;
  убедиться, что декоративные SVG скрыты.
- **Expected:** native semantics используются первыми; нет click-only div/span;
  icon button имеет понятное имя; values/states доступны; decorative paths не
  дублируются; одинаковые privacy states не раскрывают скрытые различия.
- **Actual:** CDP accessibility tree содержит один `main`, navigation, status и
  именованную icon-button «Добавить участника»; DOM scan не нашёл unlabeled
  buttons/fields или decorative SVG leaks, нашёл 3 live regions. Native form
  roles, labels, descriptions и invalid-state проверены программно. Отдельный
  computed contract подтвердил token-bound foreground/background/border/focus
  для preview-required action/form/choice/status/system cases во всех шести
  палитрах; accessibility metadata не использовалась вместо проверки стилей.
- **Evidence:** `tmp/CB-58-evidence/browser-targeted.json`,
  `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  `TP-06--390x844--dialog--visible-focus.png`.
- **Deviation:** axe-core и полноценный screen-reader pass недоступны в bundled
  runtime; выполнены CDP accessibility-tree, native semantics и DOM checks,
  поэтому совместимость с конкретным screen reader не заявляется.
- **Result:** passed.

### TP-15 — responsive/platform boundary

- **Samples:** `sample-shell-navigation`, все scenes.
- **Шаги:** встроенным frame control переключать
  `320×568 ↔ 390×844 ↔ 1440×900`, browser↔Telegram и system themes; проверить
  navigation swap, data table/list, safe area и source HTML на Telegram
  globals/SDK.
- **Expected:** одна semantic/component модель работает во всех frames;
  bottom/side navigation меняются на breakpoint без потери current location;
  table имеет compact list; provider-specific logic ограничена mapper demo;
  Telegram SDK/globals отсутствуют, browser mode полноценен визуально без них.
- **Actual:** frame control дал точные `320×568`, `390×844`, `1440×900`; compact
  показывает list и bottom navigation, wide — table и side navigation. Все 6
  сцен работают в browser/Telegram modes. Control projection проверена на 11
  допустимых tuples: browser preset отключён как неприменимый; explicit
  Telegram dark/light показывают только два preset своей base mode; Telegram
  system — ровно четыре canonical preset. Обе попытки программно выбрать
  несовместимый light↔dark preset отклонены. `AT-02/AT-06` не нашли Telegram
  SDK, globals или component-зависимости от platform primitives.
- **Evidence:** `AT-02`, `AT-06`; `tmp/CB-58-evidence/browser-qa.json`,
  `tmp/CB-58-evidence/browser-state-contract.json`,
  screenshots `TP-01`—`TP-05`.
- **Deviation:** нет.
- **Result:** passed.

## Правила screenshot и measurement evidence

- локальный каталог: `tmp/CB-58-evidence/`; он уже покрыт `.gitignore` и не
  добавляется в commit, Jira или MemPalace;
- filename: `TP-<NN>--<viewport>--<mode>--<slug>.png`; measurements — тот же
  prefix с `.json` или `.txt`; никаких UUID, Telegram IDs или имён людей;
- minimum screenshots: по одному для каждого из шести frame/mode gates из
  `plan.md`, плюс open dialog с visible focus, 400% reflow, reduced motion state
  и system-state gallery; лишние дубли не сохраняются;
- каждый screenshot снимает только synthetic preview и включает видимые frame,
  theme/platform и scene labels; cropping не должен скрывать overflow;
- computed evidence хранит sample ID, state, width/height, foreground,
  background/adjacent paths, ratio, browser build и timestamp; raw DOM dump не
  сохраняется;
- `implementation-report.md` приводит итог и локальные filenames/hash при
  необходимости, но каноническими остаются tokens, `DESIGN.md` и HTML. Evidence
  подтверждает контракт, а не определяет его задним числом;
- при расхождении screenshot не «обновляется» до зелёного: case отмечается
  failed, фиксируется deviation, исправление проходит тот же scenario повторно
  с новым evidence filename и пометкой supersedes.

## Acceptance trace

| Jira criterion | Automated | Test scenarios |
|---|---|---|
| Semantic dark/light roles | `AT-01`—`AT-03` | `TP-01`—`TP-05`, `TP-10` |
| Brand отдельно от status | `AT-03` | `TP-10`, `TP-13` |
| WCAG 2.2 AA | `AT-03`, `AT-05` | `TP-03`, `TP-06`—`TP-08`, `TP-10`, `TP-14` |
| 44×44 project target | `AT-02`, `AT-05` | `TP-02`, `TP-05`, `TP-08` |
| Telegram и browser | `AT-02`—`AT-06` | `TP-01`—`TP-05`, `TP-15` |
| Manrope/limited display | `AT-01`, `AT-04` | `TP-12`, `TP-13` |
| Purposeful glow/motion | `AT-02`, `AT-03`, `AT-06` | `TP-09`, `TP-13` |
| Mobile/desktop previews | `AT-05`, `AT-06` | `TP-02`—`TP-05`, `TP-08`, `TP-15` |

## Ограничения проверки

- CB-58 доказывает design contract в автономном Chromium preview, но не
  production React/WebView parity; Telegram theme/safe-area events и native
  controls проверяются в CB-53/release acceptance;
- live Telegram, deployment, auth, API и реальные data flows не запускаются;
- visual/anti-slop judgment остаётся ручным и не подменяется static assertions;
- отсутствие принятого performance threshold не разрешает назвать тяжёлый
  preview быстрым: размер и open time фиксируются как измеренные факты.
