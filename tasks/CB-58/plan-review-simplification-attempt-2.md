# CB-58 — повторное ревью плана компактной редакции

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

## Проверенные источники

- Jira CB-58 и CB-62 повторно прочитаны через Atlassian Rovo в режиме чтения.
  Критерии CB-58 не изменились; удаление полноценного legacy Telegram UI и
  замена fallback-части ADR-0014 по-прежнему принадлежат CB-62.
- Повторно проверены полный текущий пакет: `plan.md`,
  `plan-source-context.md`, `test-plan.md`, `implementation-report.md`,
  capability README, ADR-0014, `DESIGN.md`, `design-tokens.json`,
  `design-preview.html`, оба font assets и
  `test_release2_design_system.py`.
- Первый verdict упрощения сохранён отдельно как
  `plan-review-simplification-attempt-1.md`: 10 470 байт, SHA-256
  `8c268b9af502cc116f91da7a901486a5e454a165b84374dd535e64e4ab381af7`.
  Прежние approved plan/final reviews остаются побайтовыми `R100` rename и
  честно не используются как gate нового diff.
- Read-only gates повторены независимо: targeted pytest — `4 passed`; Ruff —
  passed; ty — passed; `git diff --check` — passed. Manrope asset имеет
  165 420 байт и ожидаемый SHA-256
  `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`;
  этот hash совпадает с pinned Google Fonts source, сохранённым в историческом
  source context. OFL присутствует.

## Замечания по области

1. **Medium — подтверждено: plan budget больше не описывает полный переносимый
   результат.** `plan.md:14-18` обещает ровно три переносимых артефакта, а
   `plan.md:47-49` задаёт budgets только для Markdown, JSON и HTML. После
   remediation preview зависит ещё от обязательных
   `assets/Manrope[wght].ttf` и `Manrope-OFL.txt` общим размером 169 804 байта;
   поэтому формулировка `self-contained preview` в `test-plan.md:29` также
   верна только для каталога-бандла, не для HTML-файла. Это не возврат к ранней
   component library и фактический объём остаётся компактным, но план должен
   перечислить font/license как части preview bundle и задать им явный budget
   либо exact pinned size/hash gate.

## Замечания по дизайну

1. **High — подтверждено: pressed state перекрывается hover state на desktop.**
   Pressed rules находятся в `design-preview.html:235-246`, а
   pointer hover rules — позже, на строках 293-301. Для primary, secondary и
   danger selectors имеют одинаковую specificity. Во время mouse press
   `:active` и `:hover` истинны одновременно, поэтому более поздний hover-rule
   выигрывает cascade: live pressed color не показывается. То же происходит с
   постоянным specimen `data-state="pressed"`, когда на него наведён pointer.
   Token contrast tests проходят, потому что проверяют значения отдельно и не
   проверяют computed CSS state. Это оставляет исходный Jira-критерий
   action states закрытым только декларативно.

2. **High — подтверждено: `platform.contrastPolicy.validatedPairs` всё ещё не
   гарантирует безопасный atomic Telegram overlay.** Список на
   `design-tokens.json:182-189` проверяет default text/surface/accent и focus,
   но не проверяет смешанные provider/base пары, реально используемые после
   overlay: `accentText` с `accentHover|accentPressed`, `text` с
   `surfaceHover|surfacePressed`, а также `success|warning|danger|info` с
   provider `surface`.

   Контрпример воспроизведён тем же алгоритмом luminance. Для dark candidate
   `background=surface=#BE123C`, `text=textMuted=#FFFFFF`,
   `accent=#000000`, `accentText=#FFFFFF` все шесть объявленных pairs проходят:
   text/background и text/surface `6.285:1`, accent `21:1`, focus/background и
   focus/surface `3.404:1`. Policy принимает candidate, но live
   `danger/surface` получает только `2.335:1`, а
   `accentText/accentHover` — `1.858:1`. Текущий low-contrast test использует
   только очевидный all-`#777777` candidate и проверяет локальное выражение
   `resolved = candidate if valid else dark`; accepted-but-unsafe palette он
   не ловит. Следовательно критерий WCAG-safe tokens для Telegram dark/light
   ещё не доказан.

3. **Medium — подтверждено: canonical tokens и preview CSS не имеют parity
   gate и уже расходятся для overlay.** Tokens задают dark overlay
   `rgba(5, 6, 10, 0.78)` и light overlay `rgba(23, 27, 38, 0.56)`
   (`design-tokens.json:116,142`), но `design-preview.html:288` всегда применяет
   dark literal `rgb(5 6 10 / 78%)`. Tests сравнивают token values между собой
   и ищут HTML markers, но не связывают канонический JSON с computed preview
   CSS. Поэтому последующий drift снова может пройти gate.

## Замечания по проверкам

- Первый набор обязательных исправлений в основном реализован: dialog,
  operation error, status specimens и variant-specific token roles добавлены;
  исходные hover ratios исправлены; Manrope реально поставляется локально и
  hash-pinned; preview по-прежнему не выдаётся за production library.
- Переданное browser evidence для dialog open/focus/Escape/focus return,
  `document.fonts=true`, dark/light, console errors и mobile overflow
  согласуется с текущим HTML и закрывает эти сценарии.
- Однако static marker `data-state="pressed"` не доказывает computed pressed
  style, а один rejected provider candidate не доказывает полноту
  `validatedPairs`. Именно поэтому `4 passed` совместимы с двумя
  воспроизведёнными дефектами выше.

## Обязательные исправления

1. Исправить cascade так, чтобы `pressed/:active` имел приоритет над hover для
   primary, secondary и danger; добавить browser/computed-style assertion для
   каждого варианта во время реального pointer press или эквивалентного
   принудительного состояния.
2. Расширить Telegram contrast policy до всех live foreground/background
   сочетаний, которые могут образоваться из provider-mapped и base roles, либо
   определить derivation state roles из принятого provider palette. Добавить
   accepted-but-unsafe counterexample и доказать, что он вызывает полный
   rollback.
3. Связать CSS preview с canonical tokens компактной parity-проверкой и
   использовать theme-specific `overlay`, а не dark literal в обеих темах.
4. Уточнить плановый inventory/budget: три logical entry artifacts плюс
   обязательный font/license bundle с ограничением размера и pinned hash.

## Остаточные риски

- ADR-0014 и capability README временно сохраняют старый bot fallback. Более
  новое решение владельца и CB-62 однозначно назначают его удаление отдельной
  задаче, поэтому для CB-58 это не блокер.
- Static HTML доказывает дизайн-контракт, но не production React/WebView parity;
  эти runtime gates корректно остаются за CB-53 и release acceptance.
- Pixel baseline отсутствует и visual regression честно обозначена как
  `inconclusive`; это допустимый residual risk после закрытия обязательных
  замечаний выше.
