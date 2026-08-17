# CB-58 — терминальное ревью плана компактной редакции

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

## Проверенные источники

- Jira CB-58 и CB-62 ранее в текущем независимом review-chain прочитаны через
  Atlassian Rovo в режиме чтения; критерии CB-58 и отдельная область удаления
  legacy bot в CB-62 остаются однозначными.
- Повторно проверены полный текущий пакет: `plan.md`,
  `plan-source-context.md`, `test-plan.md`, `implementation-report.md`,
  capability README, ADR-0014, `DESIGN.md`, `design-tokens.json`,
  `design-preview.html`, font/license assets,
  `test_release2_design_system.py` и
  `problem-escalation-simplification.md`.
- Обе попытки упрощения сохранены отдельно и неизменны:
  `plan-review-simplification-attempt-1.md` — 10 470 байт, SHA-256
  `8c268b9af502cc116f91da7a901486a5e454a165b84374dd535e64e4ab381af7`;
  attempt 2 — 9 154 байта, SHA-256
  `635396ccac730ef00ef0b727ff026858a80b45173cb3f668178464a71e0ac41e`.
  Post-escalation packet соответствует
  `agents/workflow.yaml#/review_retry_policy`: это единственная терминальная
  проверка после консолидированного fix.
- Read-only gates повторены независимо: targeted pytest — `5 passed`; Ruff —
  passed; ty — passed; `git diff --check` — passed. File budgets соблюдены:
  `DESIGN.md` 10 355/20 000, tokens 5 970/15 000, preview 15 577/30 000,
  Manrope 165 420/170 000, OFL 4 384/5 000 байт; font SHA-256 совпадает с
  pinned source.

## Замечания по области

Обязательных scope-замечаний не осталось. План теперь честно описывает три
логических артефакта и preview bundle с отдельными font/license budgets.
Dialog, operation error, action states, semantic status samples, mobile и
desktop входят в проверяемую область. Static preview нигде не объявлен
production component library.

## Замечания по дизайну

1. **High — подтверждено: Telegram contrast policy всё ещё принимает палитры с
   нечитаемым live text.** `platform.contrastPolicy.validatedPairs` расширен до
   16 записей, но в нём отсутствуют как минимум реальные пары
   `textMuted/background` и `accent/surface`:

   - `.toolbar .muted` наследует page `background`
     (`design-preview.html:79-80,160`), а mobile current navigation рисует
     `accent` как обычный текст на `surface`
     (`design-preview.html:322,332`);
   - mapping разрешает Telegram provider независимо менять `background` и
     `accent`, но policy проверяет `textMuted` только с `surface`, а `accent` с
     `surface` не проверяет вообще (`design-tokens.json:174-199`).

   Контрпримеры воспроизведены тем же алгоритмом relative luminance:

   - dark candidate, отличающийся от base только
     `background=#454545`, проходит все 16 declared pairs, но
     `textMuted/background` получает `4.462:1 < 4.5:1`;
   - light candidate с единственным `background=#A9A9A9` тоже принимается, но
     даёт `2.078:1`;
   - dark candidate с единственным `accent=#777777` принимается, хотя
     `accent/surface` для 12px mobile navigation равен `4.277:1`.

   Следовательно atomic fallback не запускается для реально небезопасных
   provider palettes. Jira-критерий WCAG AA и один safe semantic contract для
   Telegram dark/light и browser остаётся незакрытым.

Остальные замечания второго review закрыты: active/data-state rules находятся
после pointer hover и имеют приоритет; JSON↔CSS parity gate покрывает все
semantic variables; dialog использует theme-specific `--overlay`; status и
action specimens соответствуют заявленным ролям.

## Замечания по проверкам

- Browser evidence для real pointer down подтверждает разные hover/pressed
  computed backgrounds primary, secondary и danger. Dialog focus/Escape/focus
  return, Manrope load, dark/light overlay, console и overflow также закрыты.
- Новый parity test корректно связывает canonical JSON и CSS, а size/hash gates
  закрывают preview bundle.
- Provider test теперь отклоняет прежний accepted-but-unsafe status/action
  candidate, но остаётся примером по заранее перечисленным pairs. Он не
  сопоставляет policy с полным набором live foreground/background usages,
  поэтому три новых counterexample выше проходят при зелёных `5 passed`.

## Обязательные исправления

1. Для принятия плана policy должна включать как минимум
   `textMuted/background` и `accent/surface` с threshold `4.5`, а tests —
   воспроизводить все три принятые небезопасные candidates и требовать полный
   rollback.
2. Чтобы не продолжать ручной цикл пропусков, необходимо один раз сопоставить
   все live text/control foreground/background combinations preview с
   `validatedPairs` либо добавить компактный machine-checkable inventory.

По `review_retry_policy` новая автоматическая remediation/recheck после этого
терминального `changes_requested` запрещена: CB-58 останавливается до решения
владельца.

## Остаточные риски

- ADR-0014 и capability README временно сохраняют старый bot fallback; более
  новое решение владельца и CB-62 однозначно назначают замену отдельной задаче,
  поэтому это не причина текущего verdict.
- Static HTML не доказывает production React/WebView parity; runtime gates
  корректно остаются за CB-53 и release acceptance.
- Pixel baseline отсутствует и visual regression честно обозначена как
  `inconclusive`; этот residual risk допустим и не связан с обязательным
  contrast defect выше.
