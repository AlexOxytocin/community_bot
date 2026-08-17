# Дизайн-система Community Bot

## Направление

`Технологичная взаимопомощь` — спокойный рабочий интерфейс с почти нейтральными
поверхностями и редкими cyan/violet акцентами. Интерфейс должен помогать быстро
понять состояние задания, следующий шаг и последствия действия. Неон здесь
сигнал, а не обои.

Основной пользователь работает с телефона внутри Telegram Mini App. Тот же
интерфейс должен оставаться читаемым на desktop и в обычном браузере, но
Telegram-специфичные возможности изолируются в `PlatformBridge`.

## Источник токенов

Канонический machine-readable файл —
[`design-tokens.json`](design-tokens.json). Он содержит:

- небольшие primitive scales для цвета, размеров, типографики и motion;
- semantic themes `dark` и `light`;
- общие размеры controls, cards, chips и navigation;
- карту Telegram theme variables и safe-area variables.

Компоненты используют semantic роли (`text`, `surface`, `accent`, `danger`),
а не primitive hex. Telegram theme может переопределить соответствующие CSS
variables через platform adapter. При отсутствии SDK используются значения
выбранной темы.

Platform adapter применяет Telegram palette только атомарно. После mapping он
проверяет пары из `platform.contrastPolicy`: обычный текст не ниже `4.5:1`,
focus и графические controls не ниже `3:1`. Если хотя бы одна пара не проходит
или значение не является валидным цветом, вся provider palette отбрасывается и
используется base `dark` либо `light` по Telegram `colorScheme`. Смешивать
частично принятые provider colors с base theme запрещено.

## Цвет

### Бренд

- `accent` — основное действие и активное состояние;
- `brandSecondary` — короткий брендовый акцент и линия маршрута;
- cyan и violet не обозначают success/error.

Градиент cyan → violet допускается только в линии маршрута, небольшом brand
mark или одном ключевом акценте экрана. Постоянный градиент на карточках и
каждой кнопке запрещён.

### Состояния

- `success` — успешно завершённое действие;
- `warning` — обратимое внимание или приближающийся срок;
- `danger` — разрушительное действие или ошибка;
- `info` — нейтральная системная информация.

Статус передаётся одновременно текстом или иконкой. Один цвет не является
единственным носителем смысла.

## Типографика

`Manrope` используется для всех рабочих текстов. Preview загружает официальный
variable font из локального `assets/Manrope[wght].ttf`; лицензия SIL OFL лежит
рядом. `Unbounded` допустим только
для короткого brand mark или display-заголовка; длинные заголовки, формы и
таблицы остаются в Manrope.

Минимальный рабочий размер текста — `15px`, подписи — `12px`. Основной текст
имеет line-height `1.5`; display — `1.2`.

## Ритм и форма

- базовый шаг — `4px`;
- обычный внутренний отступ карточки — `16px`;
- минимальная интерактивная область — `44 × 44 CSS px`;
- радиусы: `8px` для малых элементов, `12px` для controls, `16px` для cards;
- pill применяется только к chips и компактным переключателям.

Карточка объединяет один объект или одно решение. Вложенные карточки и
декоративные контейнеры без информационной роли не используются.

## Компоненты

### Действия

Primary action использует `accent` и `accentText`. На экране обычно одна
primary action. Secondary action остаётся нейтральной. Destructive action
использует `danger` и всегда требует ясного текста последствия.

Все actions имеют состояния:

- default;
- hover только для pointer-capable browser;
- focus-visible с кольцом `focus`;
- pressed;
- disabled без ложной кликабельности;
- loading без изменения ширины.

Hover и pressed задаются отдельно для primary, secondary и destructive
вариантов. Destructive hover не превращается в brand accent. Каждая активная
foreground/background пара проходит тот же contrast gate, что default.

Атрибут `data-contrast-inventory` в preview перечисляет все фактически
используемые foreground/background пары. Документационный тест требует его
точного совпадения с `platform.contrastPolicy.validatedPairs`, поэтому новая
визуальная пара не может появиться без явного порога и автоматической проверки.

### Карточка задания

Минимальный состав:

- название;
- статус chip;
- короткие metadata: размер, срок, награда;
- один следующий шаг;
- при необходимости тонкая линия маршрута состояния.

Полное описание и история не должны заглушать список. Они открываются в detail
surface.

### Формы

Label остаётся видимым после ввода. Placeholder не заменяет label. Ошибка
привязана к полю текстом и `aria-describedby`. Submit блокируется только когда
это действительно предотвращает некорректное действие; серверная ошибка
показывается рядом с результатом команды.

### Navigation и dialogs

Mobile navigation содержит 3–5 основных разделов и учитывает safe area.
Desktop может использовать боковую навигацию. Dialog применяется для короткого
решения; длинное редактирование открывается отдельным экраном.

### Loading, empty и error

- loading сохраняет геометрию будущего контента;
- empty state объясняет, почему данных нет, и предлагает реальный следующий шаг;
- error state содержит понятное действие retry/back;
- optimistic success не показывается до подтверждённого API outcome.

Preview содержит operation error, pressed specimen и native dialog. Dialog
получает начальный focus по browser semantics, закрывается явной кнопкой или
`Escape` и возвращает focus на открывший control.

## Telegram и browser

`PlatformBridge` — единственное место, которое читает Telegram WebApp SDK,
theme events, viewport, safe-area, back button, haptics и deep links.
Компоненты получают нормализованные capabilities и semantic CSS variables.

`start_param`, query string и прямой URL являются navigation hint. Они не
доказывают identity, permission или ownership.

В обычном браузере до появления browser auth показывается только безопасный
unauthenticated режим. Layout при этом остаётся полноценным и responsive.

## Accessibility

- обычный текст соответствует WCAG AA `4.5:1`;
- крупный текст и графические controls — минимум `3:1`;
- focus-visible не скрывается;
- touch targets не меньше `44 × 44 CSS px`;
- keyboard order совпадает с визуальным;
- `prefers-reduced-motion: reduce` отключает декоративное движение;
- safe area не перекрывает navigation и primary action;
- статус не передаётся только цветом.

## Motion

Motion объясняет изменение состояния: открытие detail, появление результата,
смену active navigation. Базовая длительность `120–180ms`. Scroll theatrics,
постоянное свечение, parallax и бесконечные декоративные циклы запрещены.

## Anti-patterns

- градиент на каждой кнопке;
- glassmorphism без функциональной причины;
- фиолетовый как универсальный success/error;
- несколько competing primary actions;
- display font в формах и длинном тексте;
- случайные hex и spacing вне tokens;
- hover-only управление;
- Telegram SDK внутри React components;
- имитация успеха до ответа API.

## Preview

[`design-preview.html`](design-preview.html) — автономная проверочная страница.
Она показывает dark/light темы, controls, task cards, form/error/empty/loading
states, mobile navigation и desktop layout. Preview не является production
component library и не должен дублировать будущий frontend CB-53.
