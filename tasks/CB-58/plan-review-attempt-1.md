# CB-58 — ревью плана

Status: changes_requested

## Проверенные источники

- Jira-задачи CB-58, родительский эпик CB-48 и потребитель CB-53: описания,
  критерии, статусы, комментарии, отсутствие вложений и связь, по которой CB-58
  блокирует CB-53;
- `tasks/CB-58/plan.md` и `tasks/CB-58/plan-source-context.md` целиком;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`,
  `docs/JIRA_WORKFLOW.md`, `agents/README.md`, инструкции `developer` и
  `plan-reviewer`;
- ADR-0004, принятый ADR-0014, `docs/release-2/README.md` и
  `docs/release-2/PARITY_MATRIX.md`;
- канонические MVP-документы: README, product requirements, domain rules,
  user flows, bot interface, security/privacy, moderation, technology stack и
  журнал решений, включая D-020–D-022 и D-033;
- skill-инструкции `design-system`, `frontend-design-direction`,
  `accessibility` и инструкция read-only browser inspection;
- визуальный референс владельца
  <https://feat-alex-neon-landing-alex-neon.ks-design.workers.dev/>: выполнен
  независимый read-only осмотр desktop `1536×695` и mobile `390×844`, DOM и
  computed styles;
- официальная документация Telegram Mini Apps:
  <https://core.telegram.org/bots/webapps>;
- официальные W3C Understanding documents для Contrast Minimum, Non-text
  Contrast, Target Size Minimum и Animation from Interactions.

Ветка и worktree соответствуют поручению: `task/CB-58` в
`C:\Users\User\community_bot-worktrees\CB-58`; `HEAD`, `origin/main` и
merge-base совпадают на `cbb1807fe281f022cb46caef75e3adaeb9cbce9e`.
До ревью в worktree находятся только два новых плановых артефакта CB-58.

## Область задачи

Область выбрана правильно. План создаёт дизайн-контракт, а не преждевременный
production frontend: `DESIGN.md`, machine-readable tokens, автономный preview,
Python contract test и ссылку из Release 2 capability. React/Vite setup,
production components, код `PlatformBridge`, Telegram SDK, API, auth, routing,
feature flags, deployment и новые product rules явно исключены.

Новый ADR не нужен: план реализует уже принятое сквозное решение ADR-0014 о
semantic tokens, light/dark, responsive layout, `PlatformBridge` и browser
readiness, не меняя архитектуру или стек. Зависимость CB-58 → CB-53 отражена
правильно, а browser readiness не объявляет отдельный browser product.

Обязательные выходы названы конкретно и расположены в каноническом
`docs/release-2/design/`. Автономность preview определена достаточно строго:
один HTML без CDN, API, Telegram SDK и сетевых зависимостей, с embedded JSON и
проверкой его точного равенства внешнему `design-tokens.json`.

## Логика решения

Сильные стороны плана:

- purpose, audience, tone и memorable detail соответствуют ежедневному
  рабочему приложению, а не лендингу;
- dark-палитра действительно опирается на референс, light проектируется
  отдельно, `system` трактуется как resolver, а Telegram colors — как
  необязательные visual hints с contrast-safe fallback;
- cyan/violet отделены от success/warning/danger/info и не создают новых
  доменных значений;
- `PlatformBridge` остаётся runtime-границей CB-53: CB-58 задаёт только имена,
  mapping и визуальное поведение;
- mobile/wide layout, safe areas, длинные русские labels, 400% reflow,
  keyboard/focus, 44×44 targets, reduced motion и системные состояния покрыты
  предметно;
- component inventory охватывает shell, actions, community data, forms,
  feedback, administration и error/conflict states;
- anti-AI-slop gate конкретен и защищает рабочую плотность от hero,
  повсеместных gradients/glow/glass, nested cards и декоративного motion.

Обязательные смысловые исправления:

1. Контракт tokens внутренне неполон для передачи в CB-53. План запрещает
   production-компонентам обращаться к `primitives` и разрешает только
   `semantic` aliases, но конкретизирует в `semantic.dark/light` только color
   roles. Typography, spacing, radius, shadow, size, breakpoint, motion и icon
   grid остаются только primitives; исполнитель вынужден либо нарушить запрет,
   либо сам придумать недостающий mode-neutral слой. Нужно выбрать и описать
   одну модель: например, `semantic.shared`/component aliases для всех
   потребляемых нецветовых ролей либо явно ограничить запрет прямого доступа
   только color primitives. JSON paths и правила наследования не должны
   оставаться на усмотрение CB-53.

2. `contracts.contrastPairs` назван, но его обязательная структура и полный
   набор контекстов не определены. Фраза «проходят 4.5:1 или 3:1» не позволяет
   детерминированному тесту понять, какой threshold относится к конкретной паре
   и на какой adjacent surface проверять control/focus/status state. Для каждой
   пары нужны как минимум foreground path, background/adjacent path, modes,
   `minRatio` и назначение; отдельно должны быть перечислены default/hover/
   pressed/disabled/destructive, focus ring с обеими соседними цветами,
   status variants, Telegram presets/fallback и gradient policy. Если gradient
   допускается для action, план должен задать проверяемое правило для всей
   фактической заливки либо выбрать solid fallback, а не оставлять смысл
   «каждого stop» исполнителю.

3. Между большим component inventory и доказательством нет трассируемой
   матрицы. План одновременно обещает «полную матрицу component states», но
   автоматический test проверяет лишь неопределённые «обязательные scenes,
   component states». Нужно перечислить стабильные component/sample IDs и
   применимые состояния либо разделить inventory на `preview-required` и
   `documented-only`; тест должен доказать наличие каждого обязательного sample
   и состояния, а browser/manual matrix — его интерактивные свойства. Иначе
   часть `Toast`, navigation, form, dialog/sheet, administrative или system
   states может исчезнуть при реализации без падения gate.

## Альтернативы и риски

Рассмотренные альтернативы соответствуют задаче: dark-only, прямое копирование
Telegram variables, CSS-only tokens, ранний Storybook/React и выбор стиля по
ходу CB-53 отклонены обоснованно. Риски contrast drift, механической light
инверсии, расхождения JSON/preview, скрытого frontend prototype, рыхлой desktop
плотности и расширения browser scope имеют рабочие меры снижения.

Пакет источников всё ещё требует двух уточнений:

- план обязуется встроить Manrope и Unbounded WOFF2 subsets, но source context
  не фиксирует точные upstream/source URL, версию или commit, лицензию и способ
  получения/subsetting. Это заставляет исполнителя принимать решение о
  происхождении бинарных assets во время реализации. Нужно добавить
  authoritative font sources и лицензионное доказательство, а также правило
  сохранения copyright/license notice для встроенного subset;
- source context утверждает применение режима генерации `design-system`, но
  содержит только один референс владельца. В workflow этого skill предусмотрен
  обзор трёх сопоставимых продуктов. Нужно либо добавить три релевантных
  daily-use/community/task интерфейса и коротко зафиксировать, что именно из них
  принимается или отклоняется, либо явно обосновать замену этого шага
  единственным owner reference и каноническими product flows.

Официальный W3C источник `Animation from Interactions` относится к Level AAA,
а не AA. Reduced motion остаётся правильным и обязательным проектным
требованием CB-58, но source context и будущий `DESIGN.md` должны явно называть
его усилением проекта/AAA, чтобы итоговый отчёт не приписывал этот критерий
базовому WCAG 2.2 AA. Аналогично 44×44 уже корректно отмечен как проектное
усиление относительно AA minimum 24×24.

## Стратегия проверки

Автоматическая, browser и ручная части в целом хорошо разделены. План включает
Python contract test, Ruff, diff/link/secret/scope gates, пять viewport/theme
комбинаций, keyboard-only проход, low-contrast Telegram preset, reduced motion,
400% reflow, computed target sizes и отдельный anti-slop audit. Live Telegram и
deployment обоснованно не требуются, потому что production runtime не меняется.

Однако для задачи уровня 3 автоматические тесты прямо не доказывают визуальную,
keyboard/focus и interaction часть. ADR-0004 и workflow требуют в таком случае
отдельный ручной `tasks/CB-58/test-plan.md`. Наличие подробной секции внутри
`plan.md` полезно, но не заменяет условный артефакт: в ней нет полей для
фактического результата каждого сценария, доказательства и отклонения. До
реализации нужно вынести browser/manual matrix в `test-plan.md` с
предусловиями, synthetic test data, шагами, ожидаемым результатом,
местом для фактического результата и правилами сохранения локальных
скриншотов/измерений без превращения их в канонический источник.

После уточнения token/contrast/component contracts проверки должны явно
сопоставлять:

- Jira criterion → JSON path/HTML sample → automated assertion → browser/manual
  evidence;
- каждый `contrastPair` → точный threshold без округления и проверенные modes;
- каждый `preview-required` component/state → sample ID → keyboard/name-role-
  value/size/focus evidence;
- `dark|light|system` и browser|Telegram presets → fallback и reflow evidence.

## Обязательные исправления

1. Устранить противоречие `primitives`/`semantic`: определить точные
   mode-neutral aliases или сузить запрет прямого использования primitives и
   привести конкретное дерево JSON, которое CB-53 сможет потреблять без
   догадок.
2. Задать machine-readable schema `contracts.contrastPairs` с явными paths,
   modes, adjacent surfaces и `minRatio`, перечислить обязательные state pairs
   и сделать gradient/provider fallback полностью детерминированным.
3. Добавить трассируемую матрицу обязательных components/states и стабильные
   sample IDs, которые действительно проверяют Python test и browser/manual
   сценарии.
4. Создать до реализации `tasks/CB-58/test-plan.md` для уже запланированной
   browser/manual проверки уровня 3 и добавить его в результаты и критерии
   готовности.
5. Дополнить `plan-source-context.md` точными upstream и license sources для
   Manrope/Unbounded и закрыть предусмотренный `design-system` skill шаг с
   тремя сравнимыми интерфейсами либо документированным обоснованием его
   замены.
6. Явно отметить, что reduced motion по Animation from Interactions является
   проектным усилением/Level AAA, а не частью заявленного Level AA; сохранить
   его обязательным gate.
7. После одного консолидированного цикла обновить весь плановый пакет и передать
   его на одну повторную независимую проверку до начала реализации.

## Остаточные риски

- Итоговые light/status shades допустимо уточнять по результатам contrast test,
  но semantic role и проверяемая пара не должны меняться молча.
- Автономный HTML с двумя Cyrillic font subsets может стать тяжёлым; размер и
  время открытия на слабом Android стоит зафиксировать в manual evidence, даже
  если production font packaging остаётся CB-53.
- Chromium preview доказывает дизайн-контракт, но не production WebView parity;
  реальные Telegram theme/safe-area events и native controls остаются gates
  CB-53 и последующего release acceptance.
- Визуальная оценка anti-slop и information density неизбежно содержит
  человеческое суждение; автоматические assertions должны проверять границы,
  но не выдавать себя за замену ручному review.
