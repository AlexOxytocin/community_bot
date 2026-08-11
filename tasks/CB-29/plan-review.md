# CB-29 — эскалационный контроль плана

Status: changes_requested

Schema: `community_bot.plan_review.verdict.v1`

## reviewed_sources

- Jira `CB-29`, заново прочитанная через Atlassian Rovo JQL API 11 августа
  2026 года: семь критериев приёмки, статус `К выполнению`, labels и связи с
  CB-24/CB-28; требования не изменились.
- Полный актуальный пакет `tasks/CB-29/plan-source-context.md`, `plan.md`,
  `test-plan.md` на ветке `task/CB-29`, HEAD
  `829f170ad0a1316b597e037d8d4d006f448774c0`.
- Предыдущие findings P-001–P-003 и M-001/M-002, канонические project
  rules/workflow, ADR-0007, domain/UI/test contracts и фактические current
  Telegram navigation handlers для invitation/task draft.
- Проверена фактическая структура `tasks/CB-29`: `reviews/plan/attempt-01.md`,
  `attempt-02.md` и `problem-escalation.md` отсутствуют.

Jira, Git remote, production, Telegram, план, тест-план и код не изменялись.
Реальные Telegram/production действия не выполнялись.

## scope_findings

- Основной процесс не регрессировал: один полный discovery без исправлений,
  затем root-cause grouping, отдельные Jira Bug/ветки, targeted gate каждого
  Bug и один широкий повтор после слияния всего пакета.
- 51 сценарий остаётся практичной общей регрессией MVP. Новая архитектура,
  framework, dependency, web-admin или нагрузочный контур не добавлены.
- Real Telegram остаётся owner/admin reachability smoke; роли и destructive
  ветки выполняются production Dispatcher + fake Bot + PostgreSQL. Output-driven
  запрет ручных UUID/callback сохранён.

## design_findings

- **P-002 закрыто и не регрессировало.** Единый `cb16-regression` JQL,
  `defect → Bug|duplicate` reconciliation, один severity, `Relates` CB-29,
  отдельные ветки, отсутствие open critical/high и owner disposition каждого
  open medium/low заданы явно.
- **P-003/M-002 закрыты.** Phase 3 и test-plan теперь одинаково задают:
  full/partial применяются немедленно; только reject открывает
  `[rejected_at,rejected_at+24h)`; appeal доступна в
  `[resolved_at,resolved_at+7d)`.
- Partial conservation/replay, другой active administrator без конфликта,
  atomic reversal/rollback, paid-slot retention и вечная eligibility после
  correction/reversal сохранены без ослабления.
- **P-001/M-001 закрыты не полностью.** Конкретные stop points для кнопок
  `Создать приглашение` и выбора task template исправлены, но общий fallback без
  cleanup по-прежнему разрешает дойти до preview — см. E-001.

## verification_findings

- Фактический handler подтверждает: `nav:admin:invite` сразу вызывает
  `create_invitation`, а выбор `Создать по шаблону` сразу вызывает `tasks.start`
  и создаёт durable draft. Поэтому preview текущего task flow не является
  read-only границей.
- Plan и test-plan одновременно требуют cleanup для собственной mutation, но
  следующей строкой разрешают при отсутствии cleanup закончить на preview. Эти
  два правила дают исполнителю разные допустимые действия на одном сценарии.
- После двух предыдущих `changes_requested` пакет не содержит обязательной
  истории попыток и `problem-escalation.md`; следовательно, утверждение об одном
  консолидированном escalation fix невозможно проверить по артефактам задачи.

## required_actions

1. **E-001 — устранить последнюю неоднозначность production boundary.** В
   `plan.md` и `test-plan.md` заменить правило «нет product cleanup — smoke
   заканчивается на preview» на: «нет product cleanup — smoke останавливается до
   первого durable write; preview допустим только если он доказан read-only либо
   владелец отдельно разрешил конкретную disposable mutation и существует её
   штатный cleanup». Конкретные запреты нажимать `Создать приглашение` и выбирать
   task template без разрешения уже корректны и не требуют иной переработки.
2. **E-002 — восстановить обязательный escalation package.** Сохранить два
   предыдущих непройденных verdict как `reviews/plan/attempt-01.md` и
   `attempt-02.md`, а P-001–P-003/M-001–M-002 и выполненное консолидированное
   исправление — в `problem-escalation.md`. Это прямо требуется процессом после
   двух failed reviews и пользовательским правилом эскалации; текущий каталог
   содержит только перезаписываемый `plan-review.md`.

## residual_risks

- Остальные ранее найденные plan blockers закрыты; новых продуктовых или
  архитектурных замечаний нет.
- Это третий непройденный контроль после двух review failures. Согласно
  escalation process автоматический цикл должен остановиться для решения
  владельца после фиксации E-001/E-002, а не запускать ещё одно обычное узкое
  исправление/review.
