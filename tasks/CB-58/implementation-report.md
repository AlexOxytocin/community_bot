# CB-58 — отчёт о компактной реализации

## Результат

Первоначальная дизайн-система сокращена без потери критериев Mini App:

- общий diff уменьшен удалением более 13 тысяч строк производной спецификации;
- tokens теперь содержат primitives, semantic themes и четыре общих component
  size contracts;
- preview больше не встраивает 400+ КБ JSON и остаётся self-contained;
- preview загружает локальный официальный Manrope variable font с OFL;
- action hover/pressed states имеют variant-specific contrast-safe colors;
- плохая Telegram provider palette атомарно откатывается к base theme;
- accepted-but-unsafe смешанная provider/base palette также отклоняется;
- JSON semantic tokens и CSS variables связаны parity test;
- полный live contrast inventory связан точным equality test с policy;
- три unsafe provider overrides из terminal review откатываются целиком к
  соответствующей base theme;
- добавлены dialog, operation error и semantic status specimens;
- contract tests проверяют свойства, а не точный текст документа;
- прежние approved reviews помечены как historical evidence.

## Сопоставление критериев

| Критерий | Реализация | Доказательство |
| --- | --- | --- |
| semantic palette | `themes.dark/light` | token contract |
| cyan/violet не statuses | отдельные green/amber/red/blue roles | JSON review |
| WCAG AA | contrast checks для обеих themes | targeted test |
| targets 44px | control/navigation tokens и CSS | targeted test |
| Telegram/browser | platform mapping + theme fallback | test и DESIGN |
| SDK isolation | только `PlatformBridge` guidance | preview не содержит SDK |
| typography | Manrope body, Unbounded accent | tokens и DESIGN |
| purposeful motion | 120–180ms + reduced motion | DESIGN и preview |
| mobile/desktop | responsive preview | Chrome screenshots |
| Manrope | локальный variable font + OFL | hash и browser font check |
| Telegram fallback | atomic base-theme policy | low-contrast provider test |
| dialog/error/pressed | компактные specimens | browser и contract tests |

## Выполненные проверки

- targeted pytest: `5 passed`;
- Ruff: passed;
- ty: passed;
- `git diff --check`: passed;
- Chrome desktop/mobile dark/light: console errors `0`;
- mobile body width `375` при viewport `375`.
- Manrope loaded: `true`;
- dialog open/focus/Escape/focus return: passed.
- desktop computed hover → pressed differs for primary, secondary и danger;
- dark/light dialog overlays differ and match canonical theme variables.
- post-terminal targeted remediation: `5 passed`, Ruff passed, ty passed,
  `git diff --check` passed;
- post-terminal Chrome recheck: Manrope loaded, dialog open/focus/Escape/focus
  return passed, primary/secondary/danger hover и pressed различаются,
  theme overlays различаются, mobile `body=375` при viewport `375`, console
  errors `0`;
- после первого final review исправлены только два mechanical findings:
  contract test отформатирован, trailing whitespace из OFL удалён;
- CI-equivalent recheck: `ruff format --check --no-cache .` — 518 files passed,
  `ruff check .` — passed, `ty check` — passed, targeted pytest — `5 passed`,
  staged `git diff --cached --check` — passed.
- full pytest: `604 passed, 1 skipped`, coverage `80.35%`; пять entrypoint
  smoke cases в первом запуске не нашли commands без activation;
- повтор `tests/smoke/test_entrypoints.py` в активированной `.venv`:
  `5 passed`.

Полный CI и новый независимый final review выполняются после фиксации
обновлённого planning package.

## Известные ограничения

- preview не является production React library;
- pixel baseline отсутствует, поэтому visual regression не объявляется;
- Telegram SDK integration принадлежит CB-53;
- решение об удалении полноценного bot fallback принадлежит CB-62.
