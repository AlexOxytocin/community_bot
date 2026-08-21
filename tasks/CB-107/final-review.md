# CB-107 — независимый финальный review

Схема: `community_bot.final_review.verdict.v1`.

## Проверенная область

- Frozen Level-3 package: `plan.md`, `plan-source-context.md`, `test-plan.md`,
  утверждённый `plan-review.md` и полный `implementation-report.md`.
- Весь diff от точной базы
  `3656bbe6ee18ef27641ca1ccace15f0f1c91aaf0`, включая runtime, migration
  `0022`, unit/integration/browser tests и correction-cycle additions/deletions.
- Три канонические доски с утверждёнными SHA-256, `journey.json`, manifest и
  все 22 PNG в `tasks/CB-107/evidence/browser/375x812/` и
  `tasks/CB-107/evidence/browser/430x932/`.

## Findings

### Major

1. **PR-06 не совпадает с frozen screen contract и canonical board.**
   В `src/community_bot/transport/static/app.js:944` конфигурация `bio` задаёт
   `title: "Описание"`, а `showProfileState` использует это же значение как
   header экрана (`app.js:1763`). Поэтому оба фактических capture —
   `tasks/CB-107/evidence/browser/375x812/06-bio.png` и
   `tasks/CB-107/evidence/browser/430x932/06-bio.png` — показывают header
   `Описание`. Утверждённый `plan.md:147` и canonical
   `profile-v4-fields.png` задают экран `О себе`, при этом `Описание` является
   только label textarea. Browser test в
   `tests/browser/test_mini_app.py:427-435` проверяет textbox label и helper,
   но не screen title, поэтому зелёный результат не доказывает PR-06 parity.
   **Обязательное исправление:** разделить screen title и field label, вернуть
   header `О себе`, добавить exact heading assertion для PR-06 и заново
   сгенерировать оба PR-06 capture, `screenshots.sha256`, `journey.json` и
   связанные hashes/report evidence.

Других critical/major/minor findings в разрешённой области нет.

## Acceptance matrix

- JSONB links: server UUID, stable edit ID, order/max five, strict action shape,
  HTTPS/hostname/no credentials/control/length, missing-link rejection,
  serialized concurrent create и receipt-before-UUID replay/`409` проверены по
  domain/application/store/API diff и integration cases.
- Signed Telegram username: HMAC/age/shape, signed absence, identity advisory
  gate + member `FOR UPDATE`, no-op, один value-free audit, rollback, unknown
  identity и malformed public projection закрыты кодом и тестами.
- Privacy: own/public DTO разделены; `MeDto.statistics` и reliability DTO
  сохранены; `can_rate_karma` detail-only использует `require_karma_actor` и
  `karma_eligible` в одной UoW, mutation повторно авторизуется, list не получил
  дополнительного predicate query.
- Frontend: legacy profile identifiers и visible reliability oracle дают ноль;
  task statistics профиля отсутствуют; pencil/trash/большие `Удалить`, отсутствие
  profile-local `Отмена`, empty/public rules, max-five/order, safe opener chain,
  malformed username, modal focus и link-ID-specific Back/focus подтверждены.
- Browser matrix реально выполняет reload, list/edit/direct confirm Back,
  foreign deep-link fallback, initial/return focus, retry с тем же key, новый key
  после изменения, late response и horizontal containment в обоих viewport.
  Единственный незакрытый визуальный assertion — header PR-06 выше.
- Reliability domain/application/API/DTO/DB writers, corrections,
  disputes/appeals, leaderboard и docs не удалены и не изменены; разрешённые
  hunks в reputation owners добавляют только links/detail eligibility.
- Migration `0021 -> 0022 -> 0021 -> 0022`, default/NOT NULL/array/max-five
  checks и head `0022` подтверждены. `index.html`, dependency/lock/docs и
  исторические migrations не изменены; новых service/repository/framework нет.

## Validation evidence

- Независимо выполнено: unit `30 passed`; integration `29 passed`; после
  correction — affected integration `2 passed, 15 deselected`, web-auth unit
  `19 passed`, migration `1 passed, 16 deselected`.
- `node --check` для `app.js`/`platform.js`, Ruff для затронутых Python/test
  owners и `git diff --check` прошли.
- Manifest содержит ровно 22 записи; все 22 file hashes совпадают. SHA-256
  manifest —
  `BA5A310118306F93856BDA94362538E23BE426BEAA8CF79FCE88F2659717BE8A`,
  `journey.json` —
  `E7BC29D86A725FC35D5513945215ECFE5B57A7FF9738C1B703434BEA91C0B291`;
  journey содержит PR-01—PR-11 по одному разу для каждого viewport и ноль
  `pass=false`.
- Все 22 PNG просмотрены независимо. PR-04—PR-11 проверены отдельно в обоих
  viewport; отсутствие glyph/частей input в некоторых multi-image previews
  оказалось renderer artifact: пиксели исходных PNG и browser containment
  assertions присутствуют. Реальный несовпадающий элемент — только PR-06 title.
- Все implementation/evidence/final-review artifacts сейчас `untracked`,
  source/tests/plans — tracked modifications/additions до commit. Это ожидаемо
  для pre-commit final review, но commit обязан включить migration, report,
  review и весь `tasks/CB-107/evidence/**`; публичная поставка не заявлена.

## Security, Ponytail и остаточный риск

Secret-like значения в diff не обнаружены; совпадения сканера относятся к
именам auth API/test fixtures и самой документированной команде. Новых секретов,
dependency, слоя или параллельного renderer нет. Исправления переиспользуют
существующие UoW, receipt, audit, native platform boundary и static shell.

`Lean already. Ship.`

`net: -0 lines possible.`

После исправления finding требуется обычный повтор обязательных browser/evidence
gates перед commit. Production Telegram/WebView acceptance, merge и deployment
остаются последующими gates и не входят в локальный verdict.

## Единственный recheck после обязательного исправления

PR-06 исправлен без расширения области: в `editorConfigs.bio` screen title
теперь отделён от label поля (`О себе` / `Описание`), а connected browser test
проверяет exact `#screen-title == "О себе"` в обоих параметризованных viewport.
Повторно сгенерированы все 22 capture и manifest.

Независимый read-only visual recheck подтвердил:

- `375x812/06-bio.png` и `430x932/06-bio.png` показывают видимый Back, header
  `О себе`, label `Описание`, согласованные helper/current value и единственную
  кнопку `Сохранить`;
- PR-06 assertion реально выполняется при 375×812 и 430×932;
- `journey.json` содержит 22 записи, 22 `pass=true`, ноль отрицательных;
- 22/22 фактических PNG совпадают с `screenshots.sha256`;
- новый SHA-256 manifest —
  `7E4141713BB58429DE0D559B80290B91C3CDF6836B3A5C321CAD78E14570920B`,
  SHA-256 `journey.json` не изменился —
  `E7BC29D86A725FC35D5513945215ECFE5B57A7FF9738C1B703434BEA91C0B291`;
- follow-up не изменил unrelated runtime/domain/reliability scope;
  `git diff --check` остаётся чистым.

Единственный Major закрыт. Остальные ранее подтверждённые acceptance,
security, migration, privacy, browser-matrix и Ponytail gates сохраняют силу.

Status: approved
