# CB-55 — исходный контекст плана

## Статус снимка

- Первичная проверка: 2026-08-17, часовой пояс `America/Buenos_Aires`.
- Повторная проверка перед реализацией: 2026-08-17.
- Процесс: уровень 3; narrowed scope одобрен владельцем.
- Jira прочитана через Atlassian Rovo MCP без изменений.
- `origin/main`: `64b2cd667c28e56d7f8f2df2a70b09f1e05278f8`, merge PR #67.

## Jira snapshot

### CB-55

- Статус: `К выполнению`.
- Текущее название: «Добавить полный административный и moderation UI».
- Текущая область объединяет invitations/applications, members, catalog/config,
  community tasks, disputes/appeals, sanctions, karma/risk/alerts, audit и
  conflict checks.
- Предусловие самой задачи: CB-54 merged и moderation/reputation import rows
  reconciled.
- Вывод: текущая формулировка не является одной самостоятельной ценностью и
  противоречит размеру задачи, Ponytail и запрету generic admin platform.

### CB-54

- Статус: `Готово`.
- Утверждённый scope: read-only путь участника
  `Мои задания -> Взятые мной -> Активные -> карточка назначения`.
- Вне CB-54 остаются `withdraw`, `submit`, review outcomes, disputes,
  moderation и notifications.
- PR #67 merged в `main`; merge commit
  `64b2cd667c28e56d7f8f2df2a70b09f1e05278f8`; Jira и GitHub фиксируют green CI.

### CB-64 и capability evidence

- Статус: `Готово`; Jira фиксирует merge PR #62, merge commit
  `5d039116840069f85e73df8d06702d69355aa365` и успешные CI gates.
- ADR-0017 принят владельцем: весь существующий backend engine сохраняется;
  простота достигается формой реализации, а не удалением функций.
- `tasks/CB-64/parity-map.json` сохраняет владельцев и exact oracle для
  `REGISTRATION`, `MEMBERS`, `CATALOG_CONFIG`, `COMMUNITY_TASKS`, `DISPUTES`,
  `APPEALS`, `SANCTIONS`, `RISK_ALERTS`, `CONFLICTS`, `KARMA`,
  `AUDIT_IDEMPOTENCY` и `MODERATION_DRAFT`.

## Канонические ограничения

- `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: один наблюдаемый результат на
  задачу, Mini App/web — единственный UI, Ponytail обязателен.
- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`: полный административный контракт
  остаётся продуктовым roadmap, но не обязан выпускаться одним increment.
- `docs/mvp/02_DOMAIN_RULES.md`: dispute settlement, community review,
  interaction alerts, penalties и config activation имеют разные permission,
  privacy, conflict и transaction boundaries.
- `docs/adr/0016-mini-app-only-runtime.md`: старый Telegram UI не возвращается.
- `docs/adr/0017-lean-community-mini-app-core.md`: весь backend parity
  сохраняется; generic layers и новые зависимости без доказанной нужды
  запрещены.
- `docs/release-2/README.md`: frontend не вычисляет права; прямой URL не
  обходит server-side authorization.

## Фактическое состояние кода на снимке

- `src/community_bot/transport/web.py::create_web_app` создаёт
  `RegistrationService`, `ReputationService`, `TaskService` и
  `AssignmentService`, но не `ModerationService`; moderation routes отсутствуют.
- `src/community_bot/application/moderation.py::ModerationService.queue`
  уже является владельцем privacy-safe очереди и фильтрует `fraud_review` для
  moderator. В текущем коде этот фильтр выполняется после DB `LIMIT`, поэтому
  web-контракт обязан перенести допустимость строки в существующий DB read до
  pagination.
- `src/community_bot/infrastructure/db/moderation.py::SqlAlchemyModerationMutation.list_cases`
  возвращает только `open|appealed`, сортирует по `opened_at,id` и не загружает
  связанные evidence или private notes. ORM model содержит `reason`, поэтому
  внешняя защита дополнительно опирается на DTO allowlist и negative assertions.
- `src/community_bot/application/moderation.py::ModerationCase` уже содержит
  минимальную безопасную проекцию: `id`, `assignment_id`, `case_type`,
  `status`, `revision`, `current_code`, `opened_at`, `resolved_at`.
- `src/community_bot/infrastructure/db/database.py::Database.unit_of_work` и
  `SqlAlchemyUnitOfWork` остаются единственной PostgreSQL transaction boundary;
  существующий `get_member(member_id)` можно повторно использовать для
  web `ActorContext`.
- Текущий gap: публичный moderation read-owner принимает
  `actor_telegram_user_id`, тогда как web session выдаёт внутренний
  `ActorContext.member_id`. Прямой вызов DB adapter из route запрещён.

## Независимые исследования

### Application/API explorer

Explorer выбрал первым consumer read-only очередь moderation cases. Причины:
готовый application owner, готовая безопасная DB projection, отсутствие
mutation/receipt/ledger effects и минимальный HTTP delta. Он отдельно отложил
решения кейсов, регистрации, sanctions, alerts и raw karma.

### UX/Ponytail reviewer

Reviewer вынес terminal verdict `defer`: до merge CB-54 и owner approval нельзя
реализовывать ни один привилегированный путь. Среди мутирующих кандидатов
registration approve/reject имеет наибольшую ценность, но approve атомарно
создаёт starting grant, audit и outbox; остальные варианты ещё дороже по
privacy/conflict/ledger risk.

Синтез: runtime сейчас не начинается. Если владелец после merge CB-54 одобрит
сужение, допустим только найденный explorer read-only consumer; это не принимает
ни одного мутирующего решения за пользователя.

## Решение владельца после merge CB-54

Владелец/Оркестратор подтвердил narrowed CB-55:

- только `Модерация -> open/appealed queue -> Назад`;
- один GET, без detail и mutation;
- CB-54 merge/CI/Jira gate закрыт;
- будущий CB-64 compact-db import/reconciliation **не является** runtime
  precondition этого slice.

Причинное различие: endpoint читает текущий authoritative moderation store,
не меняет schema/data, не выполняет import или cutover и не зависит от нового
compact store. CB-64 import/reconciliation gates сохраняются для будущей
миграции и deployment, но не блокируют этот read-only consumer.

## Hard gates

- zero new domain logic, tables, dependencies, frameworks, services,
  repositories;
- no generic admin platform, schema renderer, permission framework, workflow
  engine или design-system expansion;
- не менять invitation/application decisions, roles/status/permissions,
  categories/templates/config, community tasks, disputes/appeals/sanctions,
  karma/reliability/risk/alerts/audit/conflict rules;
- CB-54 merge, повторная сверка layout/API и approval narrowed scope должны
  быть подтверждены до runtime; по повторному снимку все три gate закрыты.
