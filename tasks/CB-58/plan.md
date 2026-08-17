# CB-58 — компактная дизайн-система Mini App

## Решение владельца

17.08.2026 владелец остановил старое Telegram-only направление и потребовал
убрать оверинжиниринг. Первоначальная реализация CB-58 формально закрывала
критерии, но разрослась до 16 816 строк: 12 158 строк токенов, большой
автономный preview и тесты, замораживавшие собственную спецификацию.

Текущая редакция заменяет её небольшим устойчивым контрактом для CB-53.

## Цель

Дать Mini App три логических переносимых артефакта:

1. `DESIGN.md` с визуальными принципами и anti-patterns;
2. `design-tokens.json` с primitives, semantic dark/light themes и общими
   размерами компонентов;
3. preview bundle: `design-preview.html`, официальный Manrope variable font и
   его SIL OFL license.

## Область

### Сохраняется

- направление «Технологичная взаимопомощь»;
- Manrope для рабочего UI и Unbounded только для короткого brand accent;
- semantic roles для background, surfaces, text, accent и statuses;
- dark/light themes;
- minimum target `44 × 44 CSS px`;
- WCAG AA contrast для текста и controls;
- Telegram theme/safe-area mapping через будущий `PlatformBridge`;
- focus-visible и reduced motion;
- task cards, action variants с pressed states, form/operation error,
  loading, empty, dialog и navigation samples.

### Удаляется

- производные token matrices, которые frontend может вычислить сам;
- точные component recipes до появления React components;
- дублирование каждого значения описанием;
- embedding большого JSON в preview;
- тесты точного текста и полного дерева документа;
- требования, не влияющие на CB-53.

## Файлы

- `docs/release-2/design/DESIGN.md` — не более 20 КБ;
- `docs/release-2/design/design-tokens.json` — не более 15 КБ;
- `docs/release-2/design/design-preview.html` — не более 30 КБ;
- `docs/release-2/design/assets/Manrope[wght].ttf` — не более 170 КБ и exact
  SHA-256 `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`;
- `docs/release-2/design/assets/Manrope-OFL.txt` — не более 5 КБ;
- `tests/documentation/test_release2_design_system.py` — контрактные проверки.

Исторические review attempts и process escalation сохраняются неизменными.
Approved reviews первоначальной реализации переименовываются как historical
evidence и не считаются проверкой нового diff.

## Проверки

- JSON schema shape и разрешение token reference;
- contrast основных foreground/background pairs;
- touch target и platform mapping;
- наличие mobile/desktop, focus, reduced-motion и UI states в preview;
- contrast default/hover/pressed для каждого action variant;
- low-contrast Telegram provider palette с атомарным fallback к base theme;
- accepted-but-unsafe provider counterexample со смешанными provider/base roles;
- semantic parity между JSON tokens и CSS variables preview;
- точное равенство machine-readable live contrast inventory и policy;
- регрессии для unsafe dark `background=#454545`, light
  `background=#A9A9A9` и dark `accent=#777777`;
- фактическая загрузка локального Manrope asset;
- dialog open/close, focus entry и возврат focus;
- запрет прямого Telegram SDK в preview;
- Ruff, ty, diff check;
- headless Chrome: desktop 1440px, mobile 375px, dark/light, console errors и
  horizontal overflow;
- новая независимая проверка плана и финального diff.

## Риски

- слишком ранняя фиксация React API: снижено отсутствием component library;
- случайная потеря accessibility contract: закрыто автоматическими проверками;
- расхождение Telegram/browser: themes и platform mapping остаются semantic,
  а SDK изолируется в CB-53;
- повторный рост спецификации: установлены явные file budgets.

## Не входит

- production React components;
- Telegram SDK adapter;
- API и authentication;
- browser authentication;
- полный экранный дизайн всех пользовательских сценариев.

## Готовность

- три logical artifacts и font/license bundle укладываются в budgets;
- targeted tests и static checks проходят;
- desktop/mobile dark/light визуально проверены;
- новый `plan-review.md` и `final-review.md` имеют `Status: approved`;
- PR CI зелёный и diff слит в `main`.
