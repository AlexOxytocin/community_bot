# CB-58 — ревью плана

Status: approved

## Проверенные источники

- Jira CB-58, родительский эпик CB-48 и потребитель CB-53 повторно прочитаны
  через Atlassian Rovo в режиме чтения: описания, критерии, статусы, обе
  планировочные записи CB-58, отсутствие вложений и связь, по которой CB-58
  блокирует CB-53;
- `tasks/CB-58/problem-escalation.md`, обновлённые `plan.md`,
  `plan-source-context.md`, `test-plan.md`, обе сохранённые попытки review и
  прежний текущий `plan-review.md` прочитаны целиком;
- сохранённые попытки не изменились: attempt 1 содержит 204 строки и SHA-256
  `db1b35876f6b46220c076a46ca6eb03ec6e7e0f5e7cd7538593b712e14ffda27`,
  attempt 2 — 215 строк и SHA-256
  `b5360ee521456bb107d5a97751f9b655d4e83c7240cb5cdfe5223b3dde39fd53`;
  до записи этого третьего verdict прежний `plan-review.md` был побайтово
  идентичен attempt 2;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md`, инструкции `developer` и полный пакет роли
  `plan-reviewer`, включая R-008;
- ADR-0004, принятый ADR-0014, `docs/release-2/README.md`,
  `docs/release-2/PARITY_MATRIX.md` и релевантные MVP-документы о продуктовых,
  доменных, security/privacy и moderation границах;
- skill-инструкции `design-system`, `frontend-design-direction`,
  `accessibility` и read-only browser inspection;
- визуальный референс владельца
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>, официальная
  документация Telegram Mini Apps, W3C Understanding, официальные daily-use
  источники Linear/Discord/Todoist и pinned Google Fonts/FontTools источники из
  source context.

Worktree и ветка соответствуют поручению:
`C:\Users\User\community_bot-worktrees\CB-58`, `task/CB-58`. `HEAD`,
`origin/main` и merge-base совпадают на
`cbb1807fe281f022cb46caef75e3adaeb9cbce9e`. В worktree находятся только семь
новых плановых/evidence артефактов CB-58; runtime, toolchain, migrations и
канонические документы не изменены.

Read-only проверки полного пакета:

- component self-check: `all=53`, `previewRequired=31`,
  `documentedOnly=22`, union равен 53, intersection пуст; все 31 preview IDs
  встречаются в 17 уникальных samples, все 22 documented-only IDs имеют exact
  cases;
- найдены ровно 15 уникальных `TP-01`—`TP-15`; все TP/sample references
  разрешаются, каждый сценарий содержит `Actual`, `Evidence`, `Deviation` и
  `Result`;
- Manrope/Unbounded повторно загружены в память по pinned raw URLs: размеры
  `165420`/`778272` bytes и оба SHA-256 совпали с source context;
- `ruff format --check --no-cache .` сообщает `479 files already formatted`,
  `ruff check --no-cache .` — `All checks passed`;
- `git diff --check` завершился успешно; для untracked файлов отдельно
  проверены строки, trailing whitespace не найден;
- secret-like scan не нашёл совпадений; открытых `TODO`/`TBD`/`FIXME` нет;
  найденные слова `placeholder` являются именем semantic form token, а не
  незакрытым решением;
- в пакете нет внутренних Markdown links, поэтому missing internal links нет;
  19 внешних URLs источников были проверены в циклах review; YAML gate
  неприменим.

## Область задачи

Scope соответствует Jira и ADR-0014. CB-58 создаёт дизайн-контракт до CB-53:
`DESIGN.md`, versioned machine-readable tokens, автономный HTML preview, Python
contract test, ссылку из Release 2 capability и исполняемый ручной test plan.
React/Vite production setup, код `PlatformBridge`, Telegram SDK, API,
auth/session, routing, feature flags, deployment и новые product rules явно
исключены.

Новый ADR не требуется. План реализует принятые semantic tokens, light/dark,
responsive и platform boundary, не меняя архитектуру или стек. Browser
readiness остаётся визуальной/platform-neutral подготовкой; authenticated
browser product, публичная регистрация и отдельный backend не объявляются.

R-008 соблюдён: две непройденные попытки сохранены отдельно,
`problem-escalation.md` описывает корневые причины и единый remediation, а
реализация не начиналась до третьего verdict.

## Логика решения

Все четыре обязательных блока второго review закрыты.

1. **Palette и state paths.** `modeId` больше не образует token path. Шесть
   records `contracts.paletteModes` отдельно фиксируют
   `baseSemanticMode=dark|light`, platform, preset, provider result, effective
   source и fallback. `{baseSemanticMode}` подставляется только после resolver.
   `atomicValidatedOverlay` однозначно принимает весь contrast-safe candidate
   либо полностью возвращает exact base palette. Partial fallback отсутствует.

   Exact dark/light color leaf set и `contracts.componentStateTokens` задают
   каждый navigation, button, form, choice, status, route, card, overlay и
   system state. Матрица разворачивается в 114 однозначных
   family/variant/state records; paths, допустимые поля и `null` описаны, а
   contrast records ссылаются на их literal IDs. Исполнитель и `AT-03` больше не
   должны придумывать state → token mapping.

2. **Component/sample contract.** `contracts.componentInventory` стал
   единственным exact set. Разделение 53 IDs на 31 preview-required и 22
   documented-only полное и непересекающееся. Для каждой группы заданы exact
   variant/state cases. Grouped samples используют
   `componentRequirements[]`, а DOM обязан доказать каждый case через
   `data-component-id`, `data-variant`, `data-state` и literal state-token
   record. `TaskCard compact/full`, secondary/tertiary buttons и ранее
   пропущенные компоненты теперь либо проверяются preview, либо явно имеют
   documented-only contract.

3. **Preview/test capabilities.** Три размера
   `320×568|390×844|1440×900` объявлены built-in controls. Resolver diagnostics
   получили точный безопасный schema и DOM ID. Незаявленный `table→detail`
   переход удалён. `test-plan.md` использует ровно эти capabilities, различает
   встроенный 320 frame и отдельный 400% reflow, а evidence mapping обновлён.

4. **Fonts.** Inputs теперь имеют прямые pinned raw URLs и обязательный
   pre-subset size/hash gate. Source, metadata, upstream commits, copyright и
   OFL зафиксированы. Гарантия честно сужена до
   `provenanceAndArtifactIntegrity`: observed runtime/Brotli записываются,
   output hash связывается с embedded bytes, а `bitReproducible=false` прямо
   исключает ложное обещание одинакового повторного WOFF2 stream.

Semantic roles отделяют cyan/violet brand от success/warning/danger/info.
Gradient под action content запрещён `solidOnly`; route/brand gradient остаётся
без информативного foreground и дублируется label/icon/shape. Telegram values
остаются visual hints и не определяют business state или authorization.

## Альтернативы и риски

Альтернативы рассмотрены в границах задачи: копирование landing composition,
dark-only, безусловные Telegram variables, CSS-only contract, ранний
Storybook/React и выбор стиля по ходу CB-53 отклонены обоснованно. Три
официальных daily-use сравнения используются как pattern evidence, не добавляя
чужие product flows.

Эскалация правильно разделила font provenance, artifact integrity и
bit-reproducibility вместо дополнительного усложнения toolchain только ради
хеша. Atomic provider fallback консервативен, но безопасен и проверяем; это
допустимый design-level выбор внутри Jira-критерия contrast-safe Telegram theme,
а не новое архитектурное решение.

## Стратегия проверки

Стратегия уровня 3 достаточна и замкнута:

- `AT-01`—`AT-06` покрывают schema/references, aliases/platform resolver,
  expanded state/contrast paths, font/autonomy, exact component partition и
  static scope;
- каждый effective palette проверяется по exact threshold без округления;
  provider accepted/rejected/fallback results и resolver diagnostics должны
  совпасть с `paletteModes`;
- `AT-05` проверяет literal 53/31/22 sets, все required cases, DOM attributes,
  documented anchors и evidence IDs, а не свободный текст scene;
- `TP-01`—`TP-15` содержат предусловия, synthetic data, steps, expected,
  actual/evidence/deviation/result и правила screenshot/measurement evidence;
- keyboard/focus, name-role-value, 44×44, 400% reflow, low-contrast Telegram
  presets, reduced motion, privacy-safe system states и anti-AI-slop проходят
  отдельные ручные сценарии;
- WCAG 2.2 AA baseline корректно отделён от 44×44 project minimum и reduced
  motion / Animation from Interactions Level AAA enhancement;
- live Telegram, deployment и production React/WebView parity обоснованно
  остаются за CB-53 и release acceptance, поскольку CB-58 не меняет runtime.

Acceptance mapping сопоставляет все десять Jira criteria с JSON paths/HTML
samples, automated assertions и browser/manual evidence. План не разрешает
считать незаполненные `Actual` успешным результатом.

## Обязательные исправления

Нет.

## Остаточные риски

- Конкретные light/status shades будут выбраны во время реализации по contract
  tests; semantic roles, paths и thresholds при этом не должны меняться молча.
- Автономный HTML с двумя Cyrillic WOFF2 subsets может быть тяжёлым; размер и
  open time правильно измеряются как facts без выдуманного threshold.
- Полный provider overlay может быть отброшен из-за одной плохой пары; это
  намеренная fail-safe policy, которую нужно показать в diagnostics и TP-03/10.
- Chromium preview доказывает дизайн-контракт, но не production WebView parity;
  реальные Telegram events/native controls остаются gates CB-53.
- Визуальная оценка density и anti-AI-slop неизбежно ручная; static assertions
  охраняют границы, но не заменяют человеческое review.
