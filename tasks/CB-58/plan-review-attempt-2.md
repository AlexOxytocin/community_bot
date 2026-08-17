# CB-58 — ревью плана

Status: changes_requested

## Проверенные источники

- Jira CB-58, родительский эпик CB-48 и потребитель CB-53 повторно прочитаны
  через Atlassian Rovo в режиме чтения: описания, критерии, статусы, комментарии,
  отсутствие вложений и связь, по которой CB-58 блокирует CB-53;
- `tasks/CB-58/plan.md`, `tasks/CB-58/plan-source-context.md`, новый
  `tasks/CB-58/test-plan.md` и исходный `tasks/CB-58/plan-review.md` прочитаны
  целиком;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md`, инструкции `developer` и полный пакет роли
  `plan-reviewer`, включая R-008;
- ADR-0004, принятый ADR-0014, `docs/release-2/README.md`,
  `docs/release-2/PARITY_MATRIX.md` и релевантные MVP-документы о продуктовых,
  доменных, security/privacy и moderation границах;
- skill-инструкции `design-system`, `frontend-design-direction`,
  `accessibility` и read-only browser inspection;
- визуальный референс владельца
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>: результаты
  desktop/mobile и computed-style осмотра из первого review повторно сверены с
  текущим source context;
- официальная документация Telegram Mini Apps
  <https://core.telegram.org/bots/webapps> и W3C Understanding для contrast,
  non-text contrast, target size и Animation from Interactions;
- официальные daily-use источники Linear, Discord и Todoist, перечисленные в
  source context; заявленные наблюдения о группировке, сохранённых views,
  keyboard/drafts, progressive disclosure и responsive representations в
  целом подтверждаются этими страницами;
- pinned Google Fonts snapshot для Manrope и Unbounded, его metadata и OFL 1.1,
  а также официальная страница `fonttools==4.63.0` на PyPI.

Worktree и ветка соответствуют поручению:
`C:\Users\User\community_bot-worktrees\CB-58`, `task/CB-58`. `HEAD`,
`origin/main` и merge-base совпадают на
`cbb1807fe281f022cb46caef75e3adaeb9cbce9e`. В дереве находятся только четыре
новых плановых артефакта CB-58; runtime, toolchain и канонические документы не
изменены.

Read-only проверки пакета:

- найдены ровно 16 уникальных `sample-*` records и 15 уникальных сценариев
  `TP-01`—`TP-15`; все TP-ссылки разрешаются, а каждый сценарий содержит поля
  `Actual`, `Evidence`, `Deviation` и `Result`;
- входные Manrope/Unbounded binaries из pinned snapshot независимо проверены:
  размеры `165420`/`778272` bytes и оба SHA-256 совпадают с source context;
- `git diff --check` завершился успешно; поскольку файлы untracked, отдельно
  проверены их строки — trailing whitespace не найден;
- `ruff format --check` сообщает `476 files already formatted`, `ruff check
  --no-cache` — `All checks passed`;
- secret-like scan планового пакета не нашёл совпадений; YAML gate неприменим;
- внешние official pages прочитаны через web reader; Telegram и Discord
  отклоняют простой автоматический GET/дают anti-bot response, но сами страницы
  доступны и были проверены, поэтому это не считается сломанной ссылкой.

## Область задачи

Scope по-прежнему выбран правильно. CB-58 создаёт дизайн-контракт до CB-53:
`DESIGN.md`, versioned JSON tokens, автономный HTML preview, Python contract
test, ссылку из Release 2 capability и отдельный ручной test plan. React/Vite,
production components, реализация `PlatformBridge`, Telegram SDK, API,
auth/session, routing, feature flags, deployment и новые product rules явно
исключены.

Новый ADR не требуется: пакет реализует уже принятый ADR-0014 и не меняет
архитектуру или стек. Browser readiness ограничена platform-neutral tokens,
responsive layout и `system` resolver; authenticated browser product не
объявляется. Связь CB-58 → CB-53 и запрет начинать implementation до approved
plan review отражены верно.

## Логика решения

Большая часть замечаний первого review закрыта качественно:

- добавлен точный mode-neutral слой `semantic.shared` для typography, spacing,
  radius, shadow geometry, size, breakpoints, motion и icons; production
  consumption ограничен semantic paths;
- задан record-level contrast contract с paths, modes, states, adjacent paths,
  purpose и exact `minRatio`, а `solidOnly` однозначно запрещает gradient под
  action content;
- source context теперь содержит три релевантных официальных daily-use
  сравнения, pinned font provenance, OFL и воспроизводимый замысел subsetting;
- reduced motion правильно назван обязательным project enhancement / Level AAA
  поверх baseline WCAG 2.2 AA;
- design direction, Telegram/browser границы, accessibility, responsive rules,
  anti-AI-slop gate и запрет новой доменной логики остаются содержательно
  сильными.

Однако центральный contrast contract всё ещё внутренне противоречив. В JSON
пример использует `semantic.{mode}.color.*`, а `modes` содержит `dark`, `light`,
`telegramDark`, `telegramLight`, `telegramFallbackDark` и
`telegramFallbackLight`. План одновременно говорит, что `{mode}` подставляется
из `modes`, хотя semantic subtrees существуют только для `dark` и `light`.
Прямая подстановка создаёт несуществующие paths вроде
`semantic.telegramDark.color.*`, которые тот же `AT-03` обязан отклонить как
unknown path. Фраза о предварительном mapper не определяет, к какому effective
palette и base semantic mode приводит каждый provider/fallback mode.

Связанная часть state contract также не полностью разрешена. Обязательные pairs
включают `pressed`, secondary/tertiary/destructive hover/pressed, form states и
другие варианты, но объявленное semantic color tree точно называет лишь часть
соответствующих leaves, например `action.primaryHover`, и оставляет
«соответствующие foreground/border roles» свободным текстом. Исполнитель и
автор `AT-03` пока должны сами придумать state → token path.

Трассируемая sample-матрица появилась, но не образует исчерпывающий контракт
component coverage:

- record schema обещает одно поле `component`, тогда как строки фактически
  группируют несколько компонентов: `AppShell` с тремя navigation components,
  `TaskStatusChip` с `InlineNotice`, `Dialog` с confirmation и другие;
- `AT-05` проверяет sample ID и state, но не может доказать, что внутри grouped
  sample действительно присутствует каждый названный компонент;
- часть inventory не попала ни в точный sample record, ни в перечисленный
  `documented-only` список: например `PageHeader`, `TaskStateTimeline`,
  `SlotCounter`, `RewardBadge`, `TimeSizeBadge`, `MemberListItem` и
  `SearchField`;
- обещанные `TaskCard compact/full` и `Button secondary/tertiary` не выражены
  как required variants/states. Sample может пройти существующий gate при
  отсутствии этих вариантов.

Следовательно, число 16 само по себе подтверждено, но первоначальное замечание
о полноте component/state coverage закрыто не полностью.

## Альтернативы и риски

Рассмотренные альтернативы обоснованы: копирование landing composition,
dark-only, безусловные Telegram variables, CSS-only contract, ранний Storybook
и выбор стиля по ходу CB-53 отклонены по причинам, связанным с ежедневной
плотностью, platform neutrality и проверяемостью. Три новых официальных
сравнения используются как pattern evidence и не расширяют продукт.

Font provenance значительно улучшен: commit, upstream commits, metadata,
copyright, OFL, unicode range, input hashes и предполагаемые output facts
описаны. Но заявленная точная воспроизводимость ещё не достигнута:

- ссылки, названные `binary`, ведут на GitHub `blob` HTML, а не на pinned raw
  bytes; команды начинают с уже существующего локального TTF и не фиксируют его
  получение с обязательной pre-subset hash verification;
- `fonttools[woff]==4.63.0` подтягивает для WOFF2 зависимость
  `brotli>=1.0.1`, то есть compressor version не pinned. `toolVersion` только
  для FontTools и output hash, записанный постфактум, доказывают целостность
  готового artifact, но не гарантируют повторение тех же bytes другой установкой.

Нужно либо закрепить direct raw URL, acquisition/checksum step и полную
существенную build environment для WOFF2, либо честно назвать этот контракт
artifact integrity/provenance, а не детерминированным воспроизведением.

## Стратегия проверки

Новый `test-plan.md` в целом соответствует уровню 3: есть предусловия,
synthetic data, запрет реальных Telegram/production данных, 15 scenario IDs,
steps/expected и четыре поля фактического результата, screenshot/measurement
структура, supersedes discipline и явные ограничения Chromium preview.
Keyboard, focus containment/return, name-role-value, low-contrast provider,
44×44 boxes, 400% reflow, reduced motion, privacy-safe states и anti-slop
проверяются отдельно.

Но три шага пока не исполнимы против объявленного preview contract без догадок:

- preview controls фиксируют только frames `390×844|1440×900`, тогда как
  `TP-15` требует переключение также на `320×568`; не указано, является ли это
  третьим control или внешним DevTools viewport;
- `TP-04` требует переход `table→detail sample`, но component/sample matrix не
  содержит detail sample или соответствующее состояние;
- `TP-03` требует read-only `resolver trace`, которого нет в перечне
  обязательных preview controls, samples или diagnostic outputs.

Эти расхождения нельзя оставлять до implementation: иначе failed scenario
можно будет объяснить разной трактовкой самого плана. Acceptance mapping в
`plan.md` покрывает все десять критериев Jira; после исправления выше её нужно
синхронно связать с точными component IDs, effective palette modes и
фактически доступными test controls.

## Обязательные исправления

1. Исправить schema contrast modes: отделить `modeId` от
   `baseSemanticMode=dark|light`, явно задать provider preset, effective palette
   и fallback result для каждого Telegram mode либо выбрать эквивалентную
   однозначную модель. Placeholder не должен резолвиться в несуществующий
   semantic subtree. Одновременно перечислить точные semantic paths для каждого
   обязательного action/form/status state, чтобы `AT-03` не изобретал их.
2. Сделать component partition исчерпывающим и machine-checkable: использовать
   точный массив component IDs или отдельный record на компонент, связать states
   и variants с конкретным component, а весь inventory однозначно разделить на
   `preview-required` и `documented-only`. Добавить пропущенные компоненты либо
   явно отнести их ко второй группе; `AT-05` должен падать при отсутствии любого
   preview-required component/variant, включая `TaskCard compact/full` и
   запланированные Button variants.
3. Согласовать исполняемый `test-plan.md` с preview contract: определить способ
   `320×568`, добавить и формализовать resolver trace либо убрать зависимость от
   него, а `table→detail` либо снабдить sample/state contract, либо удалить как
   незаявленную проверку. Обновить evidence mapping после этого согласования.
4. Закрыть точную font reproduction: зафиксировать direct pinned raw inputs и
   acquisition/hash gate, а также pin существенной WOFF2 compressor/runtime
   environment; альтернативно убрать утверждение о детерминированных одинаковых
   output bytes и оставить проверяемый provenance/integrity contract.
5. Это второе независимое review после первого `changes_requested`. По R-008 до
   следующего консолидированного исправления требуется отдельный
   `tasks/CB-58/problem-escalation.md`; роль reviewer его не создаёт и
   implementation до нового `Status: approved` начинать нельзя.

## Остаточные риски

- Конкретные light/status shades допустимо уточнять по результатам contrast
  tests, если semantic roles и объявленные pairs не меняются молча.
- Автономный HTML с двумя Cyrillic WOFF2 subsets может быть тяжёлым; размер и
  open time правильно оставлены измеряемыми facts без выдуманного threshold.
- Chromium preview не доказывает production React/WebView parity; реальные
  Telegram theme/safe-area events и native controls остаются gates CB-53 и
  release acceptance.
- Визуальная оценка density и anti-AI-slop неизбежно ручная; static assertions
  должны охранять контракт, но не изображать замену человеческому review.
