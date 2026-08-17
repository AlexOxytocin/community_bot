# CB-58 — план проверки компактной дизайн-системы

## Автоматические проверки

| Gate | Проверяет |
| --- | --- |
| `token contract` | themes, primitives, components и file budget |
| `contrast` | WCAG AA для всех live preview foreground/background pairs |
| `interaction` | 44px, action states и atomic Telegram palette fallback, включая три unsafe counterexamples из terminal review |
| `preview` | responsive layout, themes, dialog/error/pressed и reduced motion |
| `font` | официальный Manrope asset, hash и OFL license |
| `ruff` / `ty` | качество и типы contract tests |
| `git diff --check` | whitespace defects |

Targeted commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/documentation/test_release2_design_system.py -q --no-cov
.\.venv\Scripts\ruff.exe check tests/documentation/test_release2_design_system.py
.\.venv\Scripts\ty.exe check tests/documentation/test_release2_design_system.py
git diff --check
```

`--no-cov` применяется потому, что тест проверяет документы и не импортирует
runtime package. Общий CI остаётся обязательным перед merge.

## Browser QA

Headless Chrome открывает локальный self-contained preview bundle:

- desktop `1440 × 1000`;
- mobile `375 × 812`;
- dark и light themes;
- theme toggle;
- фактическая загрузка Manrope через `document.fonts`;
- dialog: open, focus inside, `Escape`, focus return;
- computed pressed background отличается от hover для primary, secondary и
  destructive controls при реальном pointer down;
- console/page errors;
- `document.body.scrollWidth <= innerWidth`.

Скриншоты используются для визуального осмотра, но не коммитятся как baseline.
Без утверждённого pixel baseline visual regression считается
`inconclusive`, а не автоматическим pass.

## Ручной осмотр

- одна primary action на карточке;
- status имеет текст, а не только цвет;
- success/warning/danger/info samples соответствуют своей семантике;
- mobile navigation доступна и учитывает safe area;
- карточки не превращаются во вложенную декоративную сетку;
- light/dark сохраняют иерархию;
- glow/gradient ограничены линией маршрута и brand mark.

## Gate

После любых изменений tokens, preview или tests повторяются targeted checks и
browser QA. Затем обязательны новый independent final review и полный PR CI.

После разрешённого владельцем terminal remediation targeted gates повторены:
`5 passed`, Ruff passed, ty passed, `git diff --check` passed. Тест требует
точного равенства `data-contrast-inventory` и `validatedPairs` и отдельно
воспроизводит dark `background=#454545`, light `background=#A9A9A9` и dark
`accent=#777777`.
