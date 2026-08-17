# CB-58 — источники компактной редакции

## Jira

- CB-48: Mini App является единственным новым продуктовым направлением.
- CB-58: semantic tokens, design guidance и preview должны быть готовы до
  полноценной реализации CB-53.
- CB-62: старый Telegram-only UI будет удалён; допускается только минимальный
  Telegram shell, необходимый Mini App.

## Решения

- D-033 и ADR-0014 сохраняют один backend, `PlatformBridge` и responsive
  frontend без второго набора бизнес-правил.
- Решение владельца 17.08.2026 отменяет полноценный bot fallback и требует
  убрать лишнюю сложность. Изменение ADR оформляется в CB-62.

## Критерии CB-58

- semantic dark/light roles вместо случайных hex;
- cyan/violet не обозначают success/error;
- WCAG AA и targets от 44px;
- один набор tokens для Telegram и browser;
- Telegram SDK изолирован от компонентов;
- Manrope для рабочего интерфейса;
- glow/motion показывают состояние, а не украшают всё;
- mobile и desktop previews.

## Технические источники

- `docs/release-2/README.md`;
- `docs/adr/0014-multi-interface-release-2.md`;
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`;
- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`.
- официальный Google Fonts Manrope:
  `https://github.com/google/fonts/tree/main/ofl/manrope`, SIL OFL 1.1,
  pinned TTF SHA-256
  `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`.

Внешний референс использовался только для направления: тёмные поверхности,
cyan/violet accent и спокойная типографика. Реализация не копирует landing page.

## Историческое evidence

Первоначальные plan/final reviews и две неуспешные plan-review attempts остаются
в каталоге задачи. После существенного упрощения прежние approved verdicts
переименованы и не используются как текущий gate.
