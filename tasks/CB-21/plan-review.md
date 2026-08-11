# CB-21 — независимое повторное ревью плана

Status: approved

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-21`, повторно прочитанная через Atlassian Rovo JQL API 11 августа
  2026 года: девять критериев приёмки, статус `В работе`, приоритет `High`,
  комментарий и связи с `CB-16`/`CB-2`; требования не изменились.
- Актуальные `tasks/CB-21/plan-source-context.md`, `plan.md`, `test-plan.md` и
  двенадцать целевых сценариев.
- Ранее проверенные обязательные project/MVP документы,
  `docs/mvp/05_BOT_INTERFACE.md`, ADR-0005/0006 и фактические Catalog/Task/
  Assignment/Economy/Registration/Moderation services, Telegram routers и
  production `_dispatcher` на базе
  `becb556fa152454f66e83c0b472b56137666a59d`.

Jira, код, Git index/remote и Telegram не изменялись.

## scope_findings

- План остаётся практичным MVP bug-fix: один navigation router и одна read model
  поверх существующих сервисов, без новой FSM, таблиц, миграций или внешнего UI.
- Старые технические команды сохраняются, UUID остаются только внутри
  server-generated callback/cursor data, а full regression не дублируется в
  ветке бага и остаётся единым проходом CB-16.
- Все девять Jira AC теперь имеют реализуемые transport/application проверки;
  обязательных архитектурных решений или непрочитанных барьеров нет.

## design_findings

- **P-001 закрыто.** `/tasks` использует безопасную предварительную проекцию
  published/live/level/free-slot заданий, исключает собственные задания и уже
  занятую пару; authoritative `AssignmentService.accept` повторяет всю policy
  под существующими gates. Стабильный `(created_at DESC, id DESC)` cursor несёт
  только внутренний UUID; stale cursor безопасно начинает актуальную выдачу
  заново. Page size 10 больше не скрывает 11-е и последующие задания.
- **P-002 закрыто.** `/admin` и каждый `nav:admin:*` callback сначала проходят
  отдельный exact `role=administrator,status=active` navigation gate. Только
  после него вызываются Registration/Moderation services, чья legacy queue
  policy может оставаться шире для moderator commands. Member, moderator,
  pending и unknown получают одинаковый отказ до queue read и effects.
- **P-003 закрыто.** Navigation router включается до task и registration
  catch-all handlers и регистрирует только точные команды, тексты menu buttons
  и собственные callback prefixes. Поэтому menu action не становится ответом
  durable draft/registration flow, а обычный свободный текст продолжает
  доходить до текущего flow. `/start` остаётся единственным registration route
  и получает общий active-menu presenter без дублирующего handler.
- `/create`, `/balance`, `/help`, profile/tasks/statistics/leaderboard/members
  menu actions и admin actions переиспользуют существующие application
  authorization/replay contracts; read-only ответы не создают receipts и не
  держат DB transaction во время Bot API call.

## verification_findings

- Production `_dispatcher` + fake Bot + PostgreSQL E2E проходит `/start`,
  `/tasks`/pagination/accept, `/create`/template/durable draft, `/balance`,
  `/help` и admin invite/queues без ручного UUID и проверяет persisted effects.
- Boundary cases доказывают reachability 11-го задания, safe invalid/stale
  callback, exact-update replay и сохранение draft/assignment/invite после
  restart. Callback всегда остаётся финальной authoritative проверкой
  изменившегося task state.
- Реальный router order проверяется при существующих task/registration flows:
  точная menu button не поглощается catch-all и не меняет payload, свободный
  flow text не забирается navigation router.
- Admin E2E включает moderator/member/pending/unknown callback denial, а legacy
  `/catalog`, `/task_create`, `/my_tasks`, `/invite_create` остаются совместимы.
- Документационный contract сопоставляет показанные команды/кнопки с runtime.
  Targeted pytest, Ruff, ty, build и diff-check достаточны для CB-21; full
  regression корректно выполняется позже в CB-16.

## required_actions

Обязательных исправлений нет.

## residual_risks

- Read page является snapshot и может устареть до нажатия; безопасный callback
  повторно проверяет всю acceptance policy, поэтому это UX race, а не нарушение
  доменного состояния.
- Fake Bot API доказывает production Dispatcher wiring, но не доступность сети
  Telegram; для обнаруженного runtime UI defect это корректная граница.
