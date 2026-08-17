# CB-58 — контекст и источники плана

## Jira

- **Задача:** CB-58 — «Зафиксировать дизайн-направление и токены интерфейсов
  Release 2».
- **Родительский эпик:** CB-48 — единая платформа Community Bot с Telegram Mini
  App.
- **Потребитель результата:** CB-53 — frontend shell и read-only сценарии.
- **Зависимость:** связь Jira фиксирует, что CB-58 блокирует CB-53.
- **Состояние на момент планирования:** CB-58 и CB-48 — `В работе`, CB-53 —
  `К выполнению`.
- **Комментарии:** планирование уровня 3 уже зафиксировано на ветке
  `task/CB-58`; реализация не начинается до независимого approved plan review.
- **Основной референс владельца:**
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>.
- **Критерии Jira:** semantic dark/light tokens, Telegram theme и safe areas,
  WCAG AA, 44×44 targets, Manrope, ограниченный display font, функциональные
  glow/motion, mobile/desktop preview и готовность до CB-53.

Вложения у CB-58, CB-48 и CB-53 отсутствуют. Открытых Jira-блокеров для
планирования дизайн-системы нет.

## Канонические проектные источники

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira-first, русский язык,
  уровни риска, независимые reviews и task branch route.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md` — полный цикл уровня 3,
  артефакты, внешние изменения и критерии доказательности.
- `agents/developer/*` — bounded scope, inspect-before-edit, evidence и
  независимый final review.
- два последовательных `Status: changes_requested` в плановой фазе и
  `tasks/CB-58/problem-escalation.md` — основание последнего консолидированного
  remediation по R-008; третье review является последним до решения владельца.
- `docs/adr/0004-risk-tiered-development-workflow.md` — источник классификации
  уровня 3 для насыщенной источниками и сквозной задачи.
- `docs/adr/0014-multi-interface-release-2.md` — принятые React/Vite,
  `PlatformBridge`, semantic tokens, light/dark, responsive и browser readiness.
- `docs/release-2/README.md` — capability, actors/surfaces, ограничения и
  handoff CB-58 → CB-53.
- `docs/release-2/PARITY_MATRIX.md` — набор R2 surfaces и системных состояний,
  которые design system должна уметь выразить без новой доменной логики.
- `docs/mvp/README.md`, `01_PRODUCT_REQUIREMENTS.md`, `02_DOMAIN_RULES.md`,
  `TECH_STACK.md`, `11_DECISIONS_AND_OPEN_QUESTIONS.md` — границы Release 1,
  роли, экономика, status semantics и D-033.
- `docs/mvp/03_USER_FLOWS.md` — каталоги, создание задания, выполнение,
  подтверждение, профили, карма, споры и административные потоки.
- `docs/mvp/05_BOT_INTERFACE.md` — текущие navigation/card/list/form patterns,
  системные сообщения и ограничения длинных русских labels.
- `docs/mvp/07_SECURITY_AND_PRIVACY.md` — одинаковая privacy-safe композиция
  forbidden/not-found и запрет раскрывать приватные поля.
- `docs/mvp/08_MODERATION_AND_ABUSE.md` — moderation states, human decision и
  separation risk signal от sanction.

Из этих документов следует: дизайн не вводит новые domain states, не вычисляет
баланс/права и не превращает скрытую кнопку в authorization. Цвета и компоненты
только отображают server-provided state и разрешённые actions.

## Применённые design skills

### `design-system`

Skill задаёт обязательные выходы `DESIGN.md`, machine-readable tokens и
self-contained interactive preview, а также десять измерений проверки:
color, typography, spacing, components, responsive, dark mode, animation,
accessibility, information density и polish. Отдельный AI-slop режим потребовал
проверить gradients, glassmorphism, radii, excessive motion и generic hero.
Предусмотренный skill шаг исследования закрыт read-only обзором трёх
daily-use интерфейсов ниже; они используются как pattern evidence, а не как
источник новых продуктовых функций.

### `frontend-design-direction`

Skill потребовал до реализации определить purpose, audience, tone, memorable
detail и constraints. Его ключевое ограничение для CB-58: landing composition
нельзя переносить на инструмент ежедневного использования. Поэтому первый
viewport preview показывает рабочий task catalog, а не marketing hero.

### `accessibility`

Skill перевёл общую ссылку на WCAG AA в проверяемые требования к semantic
HTML, accessible name/role/value, focus management, live regions, исправлению
ошибок, keyboard и single-pointer alternatives, reduced motion и reflow при
`400%` zoom. Проектный target `44×44` CSS px сохранён как более строгая норма,
чем базовый минимум WCAG 2.2 AA. Reduced motion сохранён обязательным как
проектное усиление/Level AAA, а не ошибочно включён в baseline AA.

### `browser:control-in-app-browser`

Использован только для read-only визуального и computed-style осмотра ссылки
владельца после того, как обычный web reader не смог открыть preview-домен из-за
URL safety filter. Никакие формы, ссылки и внешние действия на странице не
выполнялись.

## Наблюдения по референсу владельца

Референс просмотрен 2026-08-16 в Chromium при desktop `1536×695` и mobile
`390×844`.

### Подтверждённые computed values

- body: `Manrope, system-ui, sans-serif`, background `#05060A`, text
  `#F0F3FA`;
- display headings: `Unbounded, system-ui, sans-serif`;
- root colors: `#0C0F17`, `#12151F`, `#A9B1C4`, `#8891A6`, `#2EE6D6`,
  `#8B5CF6`, `#A78BFA`;
- spacing scale: `4, 8, 12, 16, 24, 32, 48, 64` px;
- radii: `10, 16, 20, 999` px;
- body line-height около `1.65`, display line-height `1.18`;
- focus: `2px solid #2EE6D6` с offset `3px`;
- primary CTA: minimum height `44px`, gradient cyan→violet, локальный glow;
- article surface: `#0C0F17`, border `rgba(255,255,255,.07)`, radius `20px`,
  padding `24px`;
- motion tokens: `160ms`, `220ms`; референс отключает animations/transitions
  при `prefers-reduced-motion: reduce`;
- desktop H1 фактически около `40.8/48.1px`, H2 `31.2/36.8px`;
- mobile H1 уменьшается до `24/28.3px`, CTA становится шириной контента и
  сохраняет высоту `44px`.

### Сильные стороны для заимствования

- высокий основной text contrast и спокойные холодные secondary colors;
- ограниченная cyan/violet идентичность;
- последовательные spacing/radius variables;
- видимый focus и reduced-motion support;
- responsive typography и action target 44 px;
- редкий glow вокруг значимого CTA вместо повсеместного свечения.

### То, что не подходит рабочему приложению

- большая hero-типографика и вертикальный section rhythm `96–160px`;
- декоративная сеть/сфера и page-level radial gradients;
- marketing navigation и full-screen mobile menu;
- gradient CTA как action model: в CB-58 primary actions закреплены solid-only;
- крупные одинаковые article cards для длинной лендинговой ленты.

Практический вывод: палитра и аккуратный технологичный тон переносятся, а
композиция, density и hierarchy проектируются заново вокруг повторяемых задач.

## Три сравнимых daily-use интерфейса

Исследование выполнено 2026-08-16 read-only по официальным product/help pages
со скриншотами. Оно не добавляет Community Bot чужие сущности или flows.

### Linear

Источники:

- <https://linear.app/docs/my-issues>;
- <https://linear.app/docs/custom-views>;
- <https://linear.app/docs/creating-issues>.

Подтверждённые patterns: curated priority groups вместо единой плоской ленты,
сохранённые filtered views в sidebar, contextual properties рядом с объектом,
command/keyboard parity и draft preservation при уходе из composer.

- **Берём:** спокойную плотность, устойчивые row dimensions, явное grouping по
  значимости, близость status/owner/metadata к task title, keyboard equivalence.
- **Не берём:** desktop-first трёхколоночную плотность, shortcut-only discovery,
  собственные issue/product сущности и бесконечную настраиваемость views.

### Discord Community Onboarding

Источник:
<https://support.discord.com/hc/en-us/articles/11074987197975-Community-Onboarding-FAQ>.

Подтверждённые patterns: новый участник сначала выбирает понятные интересы/
роли, получает персонализированный ограниченный список, а Channels & Roles
остаётся доступным для последующей коррекции; default channels предотвращают
пустой или хаотичный первый опыт.

- **Берём:** progressive disclosure, ясную role/context маркировку, полезное
  default state и возможность вернуться к выбору без скрытой магии.
- **Не берём:** лабиринт channel lists, несколько постоянных navigation rails,
  избыток badges/unread noise и перенос Discord onboarding в scope CB-58.

### Todoist

Источники:

- <https://www.todoist.com/help/articles/customize-views-in-todoist-AoHhBxFdZ>;
- <https://www.todoist.com/help/articles/board-layout-in-todoist-nutzen-AiAVsyEI>.

Подтверждённые patterns: одинаковые tasks могут иметь list/board/calendar
representations, sections помогают scan, quick add остаётся доступным рядом с
контекстом, а layout сохраняется между devices.

- **Берём:** list-first mobile representation, стабильное место primary action,
  короткие metadata и единый object identity при responsive representation.
- **Не берём:** board/calendar как новые продуктовые modes, drag-only movement,
  карточку вокруг каждой строки и персональную productivity terminology.

Общий вывод: Community Bot использует task-first density Linear, progressive
disclosure Discord и list-first responsiveness Todoist, но сохраняет собственные
domain states, Telegram-first shell и owner palette. Ни один референс не
копируется композиционно.

## Provenance Manrope и Unbounded

Authoritative distribution source — snapshot `google/fonts` commit
`352f6b7d9d6cc4fa9e242b931291d31b21a6dc84`, проверенный 2026-08-16.
`main`/неверсионированные Google Fonts CSS URL в реализации запрещены.

### Manrope

- pinned raw binary:
  <https://raw.githubusercontent.com/google/fonts/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/manrope/Manrope%5Bwght%5D.ttf>;
- input size `165420` bytes, SHA-256
  `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`;
- metadata:
  <https://github.com/google/fonts/blob/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/manrope/METADATA.pb>;
- metadata фиксирует upstream `https://github.com/aaronbell/manrope` commit
  `6f81ebecdf65e4463b798cc07b16a4f8d5216917`, variable weight `200–800` и
  Cyrillic/Cyrillic Extended support;
- copyright: `Copyright 2018 The Manrope Project Authors
  (https://github.com/sharanda/manrope)`.

### Unbounded

- pinned raw binary:
  <https://raw.githubusercontent.com/google/fonts/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/unbounded/Unbounded%5Bwght%5D.ttf>;
- input size `778272` bytes, SHA-256
  `323b511be380c8d474ef030686b71aedde501f8d9cd46da558b7c40454372c3f`;
- metadata:
  <https://github.com/google/fonts/blob/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/unbounded/METADATA.pb>;
- metadata фиксирует upstream `https://github.com/googlefonts/unbounded`
  commit `f3ec43228a864a72487e41552e2140efab9884ea`, variable weight `200–900` и
  Cyrillic/Cyrillic Extended support;
- copyright: `Copyright 2022 The Unbounded Project Authors
  (https://github.com/googlefonts/unbounded)`.

### Лицензия, acquisition и artifact integrity

Обе pinned family распространяются по SIL Open Font License 1.1:

- Manrope OFL:
  <https://github.com/google/fonts/blob/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/manrope/OFL.txt>;
- Unbounded OFL:
  <https://github.com/google/fonts/blob/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/unbounded/OFL.txt>.

Pinned inputs получаются и проверяются до subsetting:

```powershell
$fontDir = 'tmp/CB-58-fonts'
New-Item -ItemType Directory -Force -Path $fontDir | Out-Null
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/google/fonts/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/manrope/Manrope%5Bwght%5D.ttf' -OutFile "$fontDir/Manrope[wght].ttf"
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/google/fonts/352f6b7d9d6cc4fa9e242b931291d31b21a6dc84/ofl/unbounded/Unbounded%5Bwght%5D.ttf' -OutFile "$fontDir/Unbounded[wght].ttf"
if ((Get-FileHash -Algorithm SHA256 "$fontDir/Manrope[wght].ttf").Hash.ToLowerInvariant() -ne 'd0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40') { throw 'Manrope source hash mismatch' }
if ((Get-FileHash -Algorithm SHA256 "$fontDir/Unbounded[wght].ttf").Hash.ToLowerInvariant() -ne '323b511be380c8d474ef030686b71aedde501f8d9cd46da558b7c40454372c3f') { throw 'Unbounded source hash mismatch' }
```

Subset создаётся только после успешного hash gate через
`fonttools[woff]==4.63.0` из
<https://pypi.org/project/fonttools/4.63.0/>. Зафиксированный диапазон:
`U+0020-024F,U+0400-052F,U+2000-206F,U+20AC,U+20BD,U+2116`;
сохраняются layout features, name IDs/languages, `.notdef` и copyright metadata.
Канонические команды:

```powershell
uvx --from "fonttools[woff]==4.63.0" pyftsubset "tmp/CB-58-fonts/Manrope[wght].ttf" --output-file="tmp/CB-58-fonts/manrope-r2-subset.woff2" --flavor=woff2 --unicodes="U+0020-024F,U+0400-052F,U+2000-206F,U+20AC,U+20BD,U+2116" --layout-features="*" --name-IDs="*" --name-legacy --name-languages="*" --notdef-glyph --notdef-outline --recommended-glyphs
uvx --from "fonttools[woff]==4.63.0" pyftsubset "tmp/CB-58-fonts/Unbounded[wght].ttf" --output-file="tmp/CB-58-fonts/unbounded-r2-subset.woff2" --flavor=woff2 --unicodes="U+0020-024F,U+0400-052F,U+2000-206F,U+20AC,U+20BD,U+2116" --layout-features="*" --name-IDs="*" --name-legacy --name-languages="*" --notdef-glyph --notdef-outline --recommended-glyphs
```

После выполнения точная команда, observed Python/FontTools/Brotli versions и
output SHA-256/size записываются в `DESIGN.md` и `contracts.fontProvenance`;
произвольная ручная конвертация запрещена.

Гарантия намеренно называется `provenanceAndArtifactIntegrity`, а не
bit-reproducible build. `fonttools[woff]==4.63.0` не закрепляет единственную
версию Brotli/runtime, поэтому `bitReproducible=false`: повторный запуск в иной
environment может дать другой корректный WOFF2 byte stream. Проверяется другая
цепочка: pinned raw input + pre-subset SHA-256 → записанные tool/environment
facts → output SHA-256 → exact embedded bytes с тем же hash.

Поскольку subset является модифицированной копией font software, автономный
HTML обязан содержать human-readable блок `font-license-notice` с обоими
copyright notices и полным текстом OFL 1.1. `DESIGN.md` повторяет provenance и
notice; один только hyperlink недостаточен. Input TTF и промежуточные WOFF2 не
коммитятся отдельно: в product artifact входит embedded data URL, а source и
output hashes обеспечивают provenance и целостность конкретного artifact.

## Официальная документация Telegram Mini Apps

Источник: <https://core.telegram.org/bots/webapps>, проверен 2026-08-16.

Факты, влияющие на план:

- Telegram передаёт `colorScheme` и `themeParams` в реальном времени; событие
  `themeChanged` требует динамического обновления;
- официальные guidelines требуют mobile-first responsive UI, labels для inputs,
  theme-based colors, safe area/content safe area и ограничения эффектов на
  слабых Android devices;
- `ThemeParams` необязательны и включают background, text, hint, link, button,
  section, header, bottom bar, accent, subtitle, separator и destructive roles;
- `safeAreaInset` и `contentSafeAreaInset` имеют четыре стороны и отдельные
  change events;
- `viewportHeight` нестабилен во время жеста, а `viewportStableHeight` подходит
  для устойчивой layout-границы;
- Telegram предоставляет native BackButton и BottomButton, но ADR-0014 требует
  доступ к ним только через `PlatformBridge`.

Вывод для CB-58: design tokens не могут просто копировать Telegram variables.
Нужны optional mapping, platform-neutral defaults и детерминированный
`atomicValidatedOverlay`: либо весь candidate проходит contrast, либо
effective palette равен exact base semantic palette.

## Accessibility sources

Официальные W3C WCAG 2.2 Understanding documents, проверены 2026-08-16:

- Contrast Minimum:
  <https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html> —
  `4.5:1` для normal text и `3:1` для large text, без округления threshold;
- Non-text Contrast:
  <https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html> —
  `3:1` для meaningful control/state/focus cues;
- Target Size Minimum:
  <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html> —
  WCAG AA задаёт `24×24`, но Jira CB-58 сознательно устанавливает более сильный
  проектный minimum `44×44`;
- Animation from Interactions:
  <https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html>
  — это Level AAA, не baseline AA; CB-58 всё равно требует отключать
  несущественное motion через `prefers-reduced-motion` как проектное усиление.

## Факты о репозитории и ветке

- worktree: `C:/Users/User/community_bot-worktrees/CB-58`;
- branch: `task/CB-58`, отслеживает `origin/main`;
- базовый commit: `cbb1807fe281f022cb46caef75e3adaeb9cbce9e` — merge CB-49;
- на старте рабочее дерево было чистым;
- frontend directory, `package.json`, Vite/React и существующие CSS/tokens в
  репозитории отсутствуют;
- ADR-0014 и Release 2 capability уже слиты и являются каноническими;
- задача CB-58 создаёт design contract, но не должна преждевременно вводить
  frontend runtime/toolchain из CB-53.

## Зафиксированные планом решения

- canonical location: `docs/release-2/design/`;
- outputs: `DESIGN.md`, `design-tokens.json`, `design-preview.html`;
- отдельный исполняемый `tasks/CB-58/test-plan.md` уровня 3;
- token schema version: `1.0.0`, `semantic.shared`, color modes `dark/light`,
  resolver `system`;
- `modeId` отделён от `baseSemanticMode`; Telegram provider применяется только
  как atomic validated overlay либо полностью отбрасывается;
- одна autonomous HTML preview с embedded exact token JSON;
- exact state token records, 53-component inventory, 31-component preview
  partition и required variant/state cases проверяются Python contract test;
  интерактивность — `TP-01`—`TP-15`;
- preview имеет три built-in frames и read-only resolver diagnostics; test plan
  не предполагает detail scene или скрытые console capabilities;
- dark reference palette сохраняется как primitives, light проектируется
  отдельно;
- cyan/violet не используются как success/error;
- primary action всегда использует semantic solid fill; gradient разрешён
  только route/brand без foreground content;
- Manrope — рабочий font, Unbounded — короткий brand accent;
- fonts берутся по pinned raw URLs и pre-subset hash gate; гарантируются
  provenance/integrity конкретного embedded artifact, не bit reproducibility;
  copyright/OFL notice сохраняются внутри автономного HTML;
- minimum target `44×44`, 4 px spacing rhythm, compact/medium/wide breakpoints;
- Telegram styling описывается mapping contract, но SDK-код остаётся CB-53;
- browser readiness ограничена responsive/system/platform-neutral design;
- Storybook/React components не добавляются этой задачей.

## Открытые вопросы и границы решений

Открытых product/architecture вопросов нет. Реализация всё ещё заблокирована
процессным gate: третье и последнее plan review должно вернуть
`Status: approved`; при повторном непринятии требуется решение владельца.

Следующие решения намеренно остаются владельцам других задач:

- React/Vite filesystem layout и production token compiler — CB-53;
- фактический `PlatformBridge`, theme/safe-area events и native buttons — CB-53;
- auth/session/browser access — CB-52 и будущая browser-auth задача;
- feature flags, HTTPS edge и rollout — CB-56;
- новые product states, payments, public registration и services — вне CB-58 и
  зависят от отдельных продуктовых решений.

Во время реализации допускается корректировать конкретный light/status shade,
если автоматический contrast test не проходит. Это не открытый продуктовый
вопрос: правило выбора зафиксировано — semantic role сохраняется, значение
изменяется до прохождения объявленной пары и затем фиксируется в tokens и
`DESIGN.md`.
