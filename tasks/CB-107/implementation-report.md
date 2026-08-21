# CB-107 — отчёт о реализации

## Результат

Локально реализован весь утверждённый thin slice профиля без второго renderer,
feature flag или fallback. Публичная поставка не заявляется: commit, push, PR,
независимый final review, merge и deployment находятся за границей этого turn.

## Добавлено

- Миграция `0022`: ordered `profile_links_json` JSONB с default `[]`, проверкой
  массива и лимитом пять; upgrade/downgrade и повторный upgrade проверены.
- Доменная команда links с server UUID, строгой action-specific shape,
  нормализацией label и только `https` URL. Create/update/delete используют
  существующую profile mutation transaction, identity gate, row lock, receipt,
  audit и exact replay/stale `409` boundary.
- Signed Telegram identity теперь несёт валидный username либо явное отсутствие.
  Sync/clear выполняется в transaction создания session под identity advisory
  lock и member `FOR UPDATE`; no-op не пишет audit, изменение/очистка пишет один
  allowlisted value-free audit. Неизвестная identity не создаёт member/session.
  Реальный конфликт unique session digest доказывает общий rollback username,
  audit и session insert.
- Own/public projections получили ссылки. `can_rate_karma` выдаётся только в
  detail и вычисляется в одном UoW точным предикатом `begin_vote`
  (`require_karma_actor` + `karma_eligible`); participant list не делает N+1.
- Один profile renderer покрывает 11 утверждённых состояний, прямые routes,
  reload/back/focus, request-count guards, оба viewport и безопасное открытие
  username/link через Telegram `openLink` либо browser fallback.
- Visual correction cycle восстановил canonical helper/value content в name/bio,
  populated skills с remove/duplicate/max20, presets/hint новой ссылки и явную
  SVG-корзину. Link-ID-specific Back/focus проверен для list/edit/direct/reload;
  modal удерживает Tab/Shift+Tab, а UI Back остаётся его недеструктивным выходом.
- Публичный Telegram username дополнительно фильтруется на server projection и
  в UI: legacy malformed stored value не попадает в DTO и не становится action.

## Удалено

- Старые `profileDetails`, `profileFields`, `profile-settings`, inline/preview/
  cancel branches, старые handlers/selectors/routes и текст
  `Параметры профиля`.
- Видимые profile task statistics и reliability из own profile, participant
  list/card и foreign detail. Backend reliability, writers, corrections,
  disputes, appeals, leaderboard и DTO-поля сохранены без изменения.
- Тестовый callback из session API удалён после Ponytail-аудита; rollback test
  использует настоящий отказ PostgreSQL.

## Ponytail / reuse audit

Проверены все 13 runtime/migration owners. Новых сервисов, репозиториев,
dependencies и параллельных render paths нет. Переиспользованы существующие
`RegistrationService`, `ReputationService`, `SqlAlchemyUnitOfWork`, receipt,
audit, auth и platform boundaries. Exact static oracles для legacy profile и
visible reliability возвращают ноль совпадений.

`application/reputation.py` изменён обоснованно: safe detail уже принадлежит
этому service; здесь добавлена только links projection и detail-only eligibility
в той же UoW, чтобы не разносить authorization и не создавать list N+1.
Reliability folding/writers не затронуты.

`infrastructure/db/database.py` изменён обоснованно: существующий
`create_web_session` — единственная transaction boundary, где подписанная
Telegram identity превращается в session. Username sync внутри неё даёт общий
lock/commit/rollback без нового subsystem; второй addition только делегирует
links mutation из существующего UoW в существующий registration store.

## Проверки

| Контур | Результат |
|---|---|
| replay characterization gate | `1 passed` |
| unit | `30 passed` |
| integration | `29 passed` |
| post-audit `test_web_api.py` | `17 passed` |
| targeted coverage | `59 passed`, total `79%` |
| browser connected journey | `2 passed`, `20 deselected`; `11/11` states в каждом viewport; расширенная матрица `16.13s`; PR-06 проверяет точный заголовок `О себе` |
| полный browser suite после correction cycle | `22 passed in 48.15s`; cache TTL/dedup/invalidation, profile XSS/privacy/retry/stale, participant density/race/periods и karma retry работают на новом profile renderer |
| migration | head `0022`; `1 passed` round-trip/schema/checks |
| Ruff format/check, ty | `383 files already formatted`; все проверки прошли |
| JS syntax, diff whitespace | прошли |
| legacy/reliability zero-occurrence | ноль совпадений |
| dependency/docs и reliability writer/test gates | нулевой diff |

Targeted coverage по owners: `application/registration.py` 75%,
`application/reputation.py` 52%, `domain/registration.py` 96%,
`database.py` 83%, `models.py` 100%, DB registration 74%, DB reputation 33%,
`transport/web.py` 92%. Непокрытые строки относятся главным образом к ранее
существовавшим assignment/reputation веткам; новые validation, replay,
username sync/rollback, projection и migration paths покрыты targeted tests.

Полные команды и краткие результаты сохранены в `evidence/verification.txt` и
`evidence/migration.txt`.

## Визуальное evidence

- `evidence/browser/journey.json`: 22 записей с route, assertion, focus и pass.
- `evidence/browser/screenshots.sha256`: SHA-256 для всех 22 PNG.
- SHA-256 manifest: `7e4141713bb58429de0d559b80290b91c3cdf6836b3a5c321cad78e14570920b`;
  SHA-256 journey: `e7bc29d86a725fc35d5513945215ecfe5b57a7ff9738c1b703434bea91c0b291`.
- `evidence/browser/375x812/` и `evidence/browser/430x932/`: состояния PR-01—PR-11.
- Выполнена ручная сверка с тремя canonical boards: hierarchy/actions совпадают,
  shell/nav сохранены, горизонтального overflow и чёрных inputs нет, owner/public
  privacy и empty-state правила соблюдены.
- Отдельно просмотрены финальные PR-04—PR-11 в обоих viewport; PR-07 содержит
  три ordered chips и duplicate error, а все 22 SHA-256 повторно сверены.

## Остаточный риск и следующий gate

Локальный остаточный риск — browser journey работает на intercepted synthetic
API и не заменяет production Telegram/WebView acceptance. Независимый Level-3
final review завершён со `Status: approved`. Post-review gate подтвердил:
non-integration `422 passed`, полный browser `22 passed`, PostgreSQL/migration
`585 passed` с coverage `82.36%` и чистый цикл `0022 -> base -> 0022`.
Следующий шаг — штатные commit/PR/CI/merge/deployment и live acceptance точного
release/schema `0022`.
