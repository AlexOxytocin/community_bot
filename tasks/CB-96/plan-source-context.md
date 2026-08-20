# CB-96 — контекст frontend-only плана

## Каноническая Jira

- CB-96: «Mini App: реализовать полный UI-слой утверждённой концепции 05»,
  статус `В работе`, parent CB-48.
- Описание обновлено 2026-08-19; owner comment 10348 заменяет прежний порядок.
- Текущий этап — presentation layer. Engine/API connection является следующим
  отдельным этапом.
- Comment 10347 требует machine-countable transitions и запрещает 103
  synthetic routes.
- Comment 10346 фиксирует standing intent: после двух approved reviews новый
  вопрос владельцу перед implementation не нужен.

## Нормативный дизайн

- `tasks/CB-96/design/cb93-ui-plan-v5.md`;
- `tasks/CB-96/design/cb93-contract-coverage-v5.md`;
- `tasks/CB-96/design/cb93-complete-screen-board.html`;
- `tasks/CB-96/design/cb93-transition-map.html`;
- 18 PNG в `tasks/CB-96/design/`, включая полные board/map/coverage и длинные
  create/task screens в двух частях.

Текущие нормативные counts: 103 UI, 17 no-UI, 26 capabilities. Файл с названием
`cb93-acceptance-manifest-v5r.md` не используется: он содержит stale
concept-04 inventory 84/9/75.

`ui-contract.json` v2 добавляет 11 route patterns и 128 explicit product/user
transitions. Count выводится из key flows concept 05, а не выбирается заранее.
Back/reload/deep-link/system-state contracts хранятся отдельно как global
invariants и per-screen attributes. Generator assert-ит required key edges и
запрещённые success→mutation Back; все refs разрешаются только в current 103 IDs.

## Архитектурные источники

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md` — Jira/branch/Ponytail/review/delivery.
- `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md` — level 3 plan/final review.
- ADR-0016 — Mini App only; Telegram остаётся proof/deep-link/outbound каналом.
- ADR-0017 — native HTML/CSS/ES modules без React/Vite/Node.
- `docs/release-2/design/DESIGN.md` и `design-tokens.json` — semantic tokens,
  44px controls, AA/focus/safe-area/reduced-motion.
- ADR-0019 — immutable release, production activation, public smoke.
- `tasks/CB-64/parity-map.json` — 26 capability IDs.

Новый ADR не требуется: CB-96 не меняет frontend runtime или системную
архитектуру. Framework, generic screen/form engine или dependency являются
blocker, а не допустимой реализацией.

## Репозиторий и branch

- Worktree: `C:\Users\User\community_bot-CB-96`.
- Branch: `task/CB-96`.
- Planning base: `949c837dccaea9c3549737d6f14e782947a291ff`.
- Runtime UI: `src/community_bot/transport/static/index.html`, `styles.css`,
  `platform.js`, `app.js`, `manrope.ttf`.
- Existing tests: `tests/browser/test_mini_app.py`,
  `tests/integration/test_web_api.py`, `tests/unit/test_web_auth.py`.
- Пользовательские изменения в исходном worktree не перенесены.
- После Jira comment 10351 внешний runtime executor начал ограниченный static
  UI/test diff до завершения planning recheck. CB-96 planning не изменяет и не
  считает этот diff evidence до terminal approved reviews; snapshot хранится в
  `pre-gate-runtime-snapshot.md`.

## Проверенные текущие возможности

Existing Web UI/API частично поддерживает auth/bootstrap, catalog/freeform
task creation, assignments/result/review/dispute, member/profile/karma/
leaderboard и dispute moderation. CB-96 может только сохранить эти connections.

Onboarding/templates/result versions/group cancellation/task-detail deep link,
ledger/admin/config/community/alerts и другие поверхности подключены неполно.
Их UI реализуется, но production action остаётся unavailable. Точные gaps
сохранены в `next-task-engine-handoff.md`.

## Обязательные contract corrections

- `format` — только online/offline; поля «Формат результата» нет.
- `completion_criteria` отдельно от description.
- Solo=1; group≥2 независимых слота.
- Leaderboard — отдельная поверхность «Участники», не блок профиля.
- G08A metadata read-only, действие только active toggle representation.
- G09 — только template/schema version.
- Community reward остаётся фактической шкалой 1–4.
- Нет notification inbox, generic chat, raw/private payload windows,
  automatic punishment/assignment или прямого totals edit.

## Открытые вопросы

Продуктовых вопросов нет. Динамические gates: fresh `origin/main` remap,
отсутствие конфликта в static UI/test paths и два `Status: approved`. Любая
необходимость нового backend/API/schema/dependency останавливает CB-96 и
переносится в следующий этап.
