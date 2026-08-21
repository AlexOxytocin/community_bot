# CB-107 — независимый recheck плана

Status: approved

Схема: `community_bot.plan_review.verdict.v1`.

## Проверенные источники

- Owner snapshot Jira `CB-107` под `CB-48`, Level 3, включая финальную
  reliability-границу и обязательные acceptance/review gates.
- Полностью обновлённые `tasks/CB-107/plan.md`, `plan-source-context.md` и
  `test-plan.md` на точной базе
  `3656bbe6ee18ef27641ca1ccace15f0f1c91aaf0`, ветка `task/CB-107`.
- Канонические project/process/product/domain/architecture/Mini App/release
  источники и runtime/test owners, перечисленные в исходном review.
- Три канонические доски с ранее подтверждёнными SHA-256:
  `AA28A3A8943DD5AEA4F52C42C64F81D2C4097FB2B6C4F608ED3BF38B33835B55`,
  `2D1BEF481BF0DB6FD1C0727505FFBFF38419A8B89FBFBA4F96061E98DE051E0E`,
  `0CB51AA87C616FBC1B3DB6DE7492BCD1C4EC7153C501EF72BB13E5D233AAADC0`.

## Результат recheck F-01—F-06

1. **F-01 закрыт.** Все функциональные pytest-команды используют `--no-cov`;
   добавлен отдельный исполнимый targeted line/branch coverage gate для
   изменяемых Python owners с `--cov-fail-under=0` и обязательной фиксацией
   per-owner результата в `implementation-report.md` (`test-plan.md:13-17,
   28-32,50-54,84-90`).
2. **F-02 закрыт.** Trusted username имеет точную signed shape
   `^[A-Za-z0-9_]{5,32}$`; absence→`NULL`, malformed proof закрыт. Session
   transaction сериализует identity и member row; equal value — no-op без
   audit, change/clear — ровно один allowlisted audit без proof/username;
   unknown identity и injected failure не оставляют member/audit/session
   effects (`plan.md:106-117`, `test-plan.md:23,41-42`).
3. **F-03 закрыт.** `MemberDetailDto.can_rate_karma` вычисляется по одному
   snapshot и ровно тому же non-self/effective-active/historical-eligibility
   predicate, что `begin_vote`; mutation reauthorizes, `/members` не получает
   поле или per-row query. Есть eligible/ineligible/self/status-change matrix
   (`plan.md:98-104`, `test-plan.md:24-26,43,71`).
4. **F-04 закрыт.** Для delete-confirm определены разные history-aware возвраты
   из list/edit, deterministic direct/reload fallback, focus targets и
   no-mutation Back; browser journey проверяет все входы (`plan.md:149-152`,
   `test-plan.md:67-70`).
5. **F-05 закрыт.** Foreign-only valid username открывает фиксированный
   `https://t.me/<username>` через `openTelegramLink`/`openLink` и безопасный
   browser fallback; own/absent/malformed username не является action. Контракт
   и positive/negative browser cases согласованы с доской 02
   (`plan.md:143,160-167`, `test-plan.md:71-73`).
6. **F-06 закрыт.** Placeholder удалён: manifest точно сопоставляет PR-01—PR-11,
   обе директории viewport, 22 capture paths и соответствующую canonical board
   (`test-plan.md:178-200`).

## Сохранённые gates и область

- Три source planning-файла занимают `300 + 160 + 227 = 687` строк: потолок не
  превышен. Дополнительного planning artifact нет; `plan-review.md` —
  обязательный Level-3 review artifact.
- `MeDto.statistics` и `own_statistics` явно сохраняются. Reliability удаляется
  только из user-visible Mini App owner/foreign profiles, participant
  list/cards/detail и frontend helpers/formatters. Backend/domain/application,
  API/DTO/DB, writers, corrections, disputes/appeals, leaderboard ordering,
  docs и reliability tests не меняются.
- Одна JSONB migration `0022`, stable server UUID, max five/order, owner lock,
  receipt-before-UUID, exact replay/conflict, stale rejects, up/down/schema и
  production no-destructive-downgrade остаются полными. При непригодности
  существующей receipt boundary действует characterization/stop gate без новой
  idempotency subsystem.
- Все 11 screen/transition/deep-link/reload/Back/focus состояния определены для
  `375x812` и `430x932`; сохранены exact pencil/trash/`Удалить`, отсутствие
  hub/inline/preview/`Отмена`, empty/public privacy, server URL validation,
  hard legacy deletion и один static/browser zero-visible-reliability oracle.
- Dependency/service/repository/framework/endpoint не добавляются; native
  frontend и существующие FastAPI/Pydantic/SQLAlchemy/Alembic owners
  переиспользуются. Новый ADR не требуется при сохранении этой формы.
- Release/Telegram gates остаются post-final-review/post-merge: exact immutable
  release, schema `0022`, deployment, health/readiness, разрешённые test
  accounts и public smoke. До них нельзя заявлять публичную готовность.

## Validation evidence

- `git rev-parse HEAD` → exact base; `git status` показывает только три source
  planning-файла и этот review artifact.
- Точная unit-команда из обновлённого плана → `UNIT_EXIT=0`.
- Обновлённая integration-команда с `--no-cov --collect-only` →
  `INTEGRATION_COLLECT_EXIT=0`.
- Точная targeted-coverage команда с `--collect-only` →
  `COVERAGE_COLLECT_EXIT=0`; все указанные modules/options распознаны.
- Поиск `те же|TBD|TODO|placeholder|заполнитель` в трёх planning-файлах → ноль
  совпадений. Runtime/source/tests/migrations/Jira/remote не изменялись.

## Ponytail

Нового слоя, dependency, fallback или дублированной implementation path нет.
`Lean already. Ship.`

`net: -0 lines possible.`

## Остаточные риски

Открытых semantic blockers в plan package нет. Реализация обязана остановиться
на уже перечисленных stop conditions и доказать фактические migration,
idempotency, privacy, browser, final-review и production gates; их наличие не
является незакрытым вопросом плана.
