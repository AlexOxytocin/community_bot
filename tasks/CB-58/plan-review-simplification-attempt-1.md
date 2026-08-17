# CB-58 — ревью плана компактной редакции

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

## Проверенные источники

- Jira CB-58 и CB-62 прочитаны через Atlassian Rovo в режиме чтения. CB-58
  находится в статусе `На проверке`, сохраняет исходные критерии дизайна и
  блокирует CB-53; CB-62 отдельно закрепляет удаление полноценного legacy
  Telegram-only UI и будущую корректировку fallback-части ADR-0014.
- Полностью прочитаны `tasks/CB-58/plan.md`, `plan-source-context.md`,
  `test-plan.md`, `docs/release-2/README.md`, ADR-0014,
  `docs/release-2/design/DESIGN.md`, `design-tokens.json`,
  `design-preview.html`, `tests/documentation/test_release2_design_system.py`,
  а также канонические правила проекта и релевантные D-033/MVP-требования.
- Исторические `plan-review-attempt-1.md`, `plan-review-attempt-2.md` и
  `problem-escalation.md` проверены по текущему Git-состоянию. Прежние approved
  verdicts переименованы с similarity `R100`; blob hashes исходных и новых имён
  совпадают. Они честно обозначены как evidence до упрощения и не используются
  как текущий gate.
- Read-only проверки текущей редакции: targeted pytest — `4 passed`; Ruff —
  passed; ty — passed; `git diff --check` — passed. Размеры артефактов:
  `DESIGN.md` — 8 951 байт при budget 20 КБ, tokens — 4 027 при 15 КБ,
  preview — 11 664 при 30 КБ. Budgets разумно ограничивают повторный рост и не
  маскируют production component library.

## Замечания по области

1. **High — подтверждено: сокращённый план молча теряет часть области CB-58.**
   Jira требует определить dialogs, loading/empty/error states и состояния
   primary/secondary/destructive actions. `plan.md` сохраняет только task cards,
   actions, form error, loading, empty и navigation samples; dialog и общий
   operation error отсутствуют. `DESIGN.md:79-86,108-118` обещает pressed,
   dialogs и retry/back error, но в `design-preview.html` нет dialog,
   `:active`/pressed или общего error state, а
   `test_release2_design_system.py:146-161` проверяет лишь наличие нескольких
   строковых markers. Это не вопрос полноты component library: компактные
   specimens основных состояний нужны, чтобы CB-53 не угадывал уже принятый
   контракт.

## Замечания по дизайну

1. **High — подтверждено: текущий preview нарушает заявленный WCAG AA в hover.**
   `design-preview.html:241` применяет один `.button:hover` ко всем вариантам и
   заменяет их background на `accentStrong`, сохраняя прежний foreground.
   Расчёт по тем же формулам relative luminance, что использует тест, даёт:
   light primary `2.300:1`, dark secondary `2.164:1`, dark destructive
   `1.170:1`, light destructive `2.732:1` вместо `4.5:1` для обычного текста.
   Кроме контраста destructive hover теряет destructive background semantics.
   Тест `test_theme_contrast_meets_wcag_aa` на строках 94-107 проверяет только
   базовый `accentText/accent` и status text, поэтому выдаёт зелёный результат
   при фактическом дефекте состояния. Это прямо противоречит Jira-критерию
   «текст и controls соответствуют WCAG AA».

2. **High — подтверждено как пробел контракта: Telegram theme mapping не имеет
   contrast-safe resolver/fallback.** `DESIGN.md:25-28` разрешает Telegram theme
   переопределять CSS variables, а `design-tokens.json:155-161` содержит только
   прямую карту provider variables. Нет правила валидации итоговых foreground /
   background / focus / control pairs и нет полного semantic fallback при
   плохом provider palette. `test_interaction_and_platform_contract` проверяет
   только одну строку mapping, а browser QA проверяет лишь две статические base
   themes. Поэтому пакет не доказывает критерий одного WCAG-safe набора tokens
   для Telegram dark/light и browser. Риск плохого Telegram provider palette
   остаётся гипотезой до runtime, но отсутствие обязательной политики и теста —
   факт текущего контракта.

3. **Medium — подтверждено: Manrope заявлен, но фактически не используется в
   автономном preview.** Tokens и CSS перечисляют `Manrope` первым
   (`design-tokens.json:63-67`, `design-preview.html:27`), однако в preview нет
   `@font-face`/font asset/link, в репозитории нет Manrope, и на машине проверки
   шрифт не установлен. Автономный Chrome поэтому переходит к `Segoe UI`.
   Нынешний gate вообще не проверяет загрузку шрифта, хотя Jira требует Manrope
   для рабочего UI, а implementation report объявляет этот критерий закрытым.
   Production packaging можно оставить CB-53, но preview должен либо поставлять
   проверяемый compact asset, либо критерий и доказательство должны быть честно
   перенесены владельцем.

4. **Medium — подтверждено: samples противоречат собственным semantic roles.**
   `DESIGN.md:43-46` определяет `success` как успешно завершённое действие, а
   `warning` как внимание/приближающийся срок. Preview использует
   `chip success` для статуса «Открыто» (`design-preview.html:310`) и
   `chip warning` для «На проверке» (`:324`). Статусы имеют текст, но цветовая
   семантика сообщает другое состояние и оставляет CB-53 неверный пример.

## Замечания по проверкам

- Автоматические shape/file-budget проверки, базовые dark/light contrast pairs,
  44px size tokens, отсутствие прямого `Telegram.WebApp`, Ruff, ty и diff check
  проходят и полезны.
- Headless Chrome по заявленным `1440`/`375`, dark/light, console errors и
  overflow достаточен для базовой responsive-проверки, но не закрывает
  interaction-state contrast, фактический font load, Telegram provider
  fallback, dialog focus/return и pressed/error specimens.
- Формулировка «preview не является production component library» корректна в
  `DESIGN.md:164-167`, `README.md` и implementation report. Пакет не выдаёт
  статический HTML за React/runtime implementation.

## Обязательные исправления

1. Вернуть в компактный план и test plan недостающие Jira cases: dialog,
   operation error с retry/back и проверяемые pressed states для action
   variants; либо получить явное изменение области CB-58 в Jira.
2. Задать variant-specific hover/pressed/focus colors и проверять все активные
   foreground/background пары без округления; исправить уже воспроизведённые
   hover failures.
3. Зафиксировать компактную fail-safe политику Telegram theme: валидировать
   итоговые semantic pairs и атомарно откатываться к dark/light base palette;
   добавить low-contrast provider case в автоматический или browser gate.
4. Сделать использование Manrope в автономном preview фактическим и
   проверяемым либо явно согласовать перенос этого acceptance criterion в
   CB-53; одного имени в font stack недостаточно.
5. Привести status samples к значениям `success|warning|danger|info`, описанным
   в `DESIGN.md`, не меняя доменные состояния.

## Остаточные риски

- ADR-0014 и release-2 README всё ещё описывают полноценный bot fallback, но
  более новое решение владельца и Jira CB-62 явно назначают их замену другой
  задаче. Для CB-58 это не блокер, пока текущий дизайн не добавляет новый
  Telegram-only UI; до завершения CB-62 документы временно расходятся.
- Static preview может доказать дизайн-контракт, но не parity будущих React
  components и реального Telegram WebView. Эти runtime gates корректно остаются
  за CB-53/release acceptance.
- Pixel baseline отсутствует, поэтому визуальная регрессия честно обозначена
  как `inconclusive`; это не блокирует контракт после закрытия замечаний выше.
