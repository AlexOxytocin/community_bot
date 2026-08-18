# CB-54 — исходный контекст плана

## Статус пакета

- Уровень процесса: `3` — большой исходный контекст, web security/privacy и
  зависимость от ещё не слитой CB-53.
- Режим: только планирование. Runtime-код, Jira, ветка и remote не изменяются.
- Снимок репозитория: `HEAD = origin/main =
  ea8550f4255fb69f7e90828d6b38454f6a743d80` (merge CB-52).
- Обязательная runtime-предпосылка: CB-53 слита в `main`; до этого реализация
  CB-54 запрещена.

## Снимок Jira на 2026-08-17

- `CB-54`, тип `История`, статус `К выполнению`, приоритет `Medium`.
- Summary: «Добавить в Mini App полный движок заданий».
- Родитель: `CB-48`, статус `В работе`.
- `CB-54` заблокирована `CB-53`; в свою очередь блокирует `CB-57`.
- `CB-53` на момент чтения имеет статус `К выполнению`, а `CB-52` — `Готово`.
- Доступные переходы CB-54: `К выполнению`, `В работе`, `На проверке`, `Готово`.
  Отдельного перехода `Планирование` нет; переход не выполнялся.
- Jira read выполнен через Atlassian Rovo MCP. Jira write не выполнялся.

Исходное описание CB-54 перечисляет весь task engine: catalog/templates,
durable drafts, member/group/community tasks, публикацию и reviewer,
accept/withdraw/replacement/cancellation, submission/result versions/review,
deadlines/finalizers, disputes и settlement. Это roadmap capability inventory,
а не безопасный объём одного diff для пилота на 20–30 участников.

## Канонические решения

1. `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`: Jira-first, русский язык,
   Mini App-only, Ponytail full, один наблюдаемый результат на задачу.
2. `docs/mvp/01_PRODUCT_REQUIREMENTS.md`: участнику нужны каталог, принятие,
   отказ, сдача результата и история; admin/moderation — отдельная область.
3. `docs/mvp/02_DOMAIN_RULES.md`: settlement, deadlines, no-show, review window,
   partial outcome, cancellation и ledger остаются authoritative backend rules.
4. `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`: D-013, D-014, D-027,
   D-031, D-032 и D-033 фиксируют slot lifecycle, review/finalizers,
   cancellation responses, историю участия и multi-interface boundary.
5. `docs/adr/0016-mini-app-only-runtime.md`: старый Telegram chat UI не
   восстанавливается.
6. `docs/adr/0017-lean-community-mini-app-core.md`: весь task engine сохраняется,
   но UI и backend добавляются feature slices; frontend — native
   HTML/CSS/ES modules; без React/Vite/Node.
7. `docs/adr/0014-multi-interface-release-2.md`: пока применимо требование к
   HTTP operation identity — namespace, internal actor, external key, command,
   payload fingerprint и stored outcome; Telegram `update_id` нельзя
   имитировать для HTTP.
8. `docs/release-2/README.md` и `docs/release-2/PARITY_MATRIX.md`: backend —
   единственный источник состояния; каждая mutation требует exact replay;
   CB-54 отвечает за task screens, но не обязана закрыть всю матрицу одним diff.
9. `tasks/CB-64/parity-map.json`: authoritative capability IDs и planned
   scenario oracles для `CATALOG_CONFIG`, `MEMBER_TASKS`, `GROUP_TASKS`,
   `COMMUNITY_TASKS`, `ASSIGNMENT_LIFECYCLE`, `DEADLINES`, `DISPUTES`,
   `CONFLICTS`, `NOTIFICATIONS`, `TASK_CREATION_DRAFT`, `SUBMISSION_DRAFT`.

Новый ADR для этого плана не нужен: план не меняет принятый stack, schema,
domain boundary или operation identity; он выбирает меньший slice внутри
ADR-0017. Любое решение ослабить HTTP receipt contract потребует отдельного
owner approval и, вероятно, нового/заменяющего ADR.

## Проверенный текущий web-контур

- `src/community_bot/transport/web.py:148` создаёт auth, registration,
  reputation и `TaskService`; `AssignmentService` не подключён.
- Текущие routes: auth/session, `GET /api/v1/me`, members, `GET /api/v1/tasks`,
  leaderboard. Assignment routes отсутствуют.
- Cookie session разрешается в `ActorContext(member_id, "telegram",
  authenticated_at)`; клиентские role/status/permissions не принимаются.
- Ответы DTO собираются whitelist-полями и получают `Cache-Control: no-store`.
- На текущем `main` frontend shell ещё отсутствует: его добавляет CB-53.

## Authoritative owners выбранного slice

- Performer-scoped list/detail projections:
  `AssignmentService.cards` и `AssignmentService.card` в
  `src/community_bot/application/assignments.py:367` и `:392`.
- UoW projection owners: `list_assignment_cards` и `get_assignment_card` в
  `src/community_bot/infrastructure/db/assignments.py:130` и `:153`.
- `AssignmentCard` содержит assignment/task snapshot, `result_summary` и
  case status, но не должен сериализоваться напрямую:
  `src/community_bot/application/assignments.py:109`.
- Existing lifecycle oracle:
  `tests/integration/test_assignments.py:116` и соседние assignment scenarios.
- Текущий gap: read methods принимают `actor_telegram_user_id`, тогда как web
  session authoritative subject — internal `member_id`. Допустима только тонкая
  actor-native read перегрузка внутри существующего owner с уже доступным
  `get_member`; новый service, repository или domain rule запрещены.
- Detail projection сама по себе возвращает terminal owner assignment. Узкий
  active-only contract обязан дополнительно проверить
  `ACTIVE_ASSIGNMENT_STATUSES` в application owner и одинаково скрыть terminal,
  foreign, missing и test-run-invisible UUID.
- Existing DB pagination сортируется по `(accepted_at, assignment_id)`. Cursor
  кодирует последнюю выданную строку; actor-native page owner читает
  `page_limit+1` напрямую через projection, включая boundary `limit=50`.

## Почему mutation исключена сейчас

- `AssignmentService.cancel` (`application/assignments.py:630`) уже корректно
  проверяет ownership/status/reason и обновляет aggregate, refund, outbox и
  receipt. Это лучший кандидат для следующего mutation slice.
- `AssignmentService.submit` (`:699`) и staged draft flow `begin_submission →
  save_submission_draft → confirm_submission_draft` (`:481`, `:521`, `:568`)
  сохраняют immutable result versions и schema validation.
- Однако обе mutation-группы используют `update_id`,
  `actor_telegram_user_id` и receipt `processed_telegram_updates`. На `main` нет
  доказанного HTTP namespaced operation receipt owner.
- Поэтому POST в CB-54 сейчас нарушил бы hard gate либо создал бы скрытый
  transport/domain refactor. Это точный gap, а не отсутствующая доменная функция.

## Capability map исходной формулировки CB-54

| Capability | Существующий owner/projection | UI нужен | Зависимость | Рекомендуемый slice |
|---|---|---:|---|---|
| Категории и шаблоны | `CatalogService`; versioned config и Draft 2020-12 validation | Да, для создания | creator workflow + config projections | Позже: creator catalog |
| Free-form durable task draft | `TaskService.start/advance/preview/publish`; draft revision/ownership | Да | HTTP receipt + form design | Позже: создание задания |
| Member task publish/reserve | `TaskService.publish`; ledger/operations/outbox | Да | draft slice + mutation identity | Вместе с creator publish |
| Group slots/close intake/cancellation responses | `TaskService` owner/cancellation methods; assignments + ledger | Да | owner task screen; race oracle | Позже: owner lifecycle |
| Community publish/approval/reviewer | `TaskService`; conflict rules | Да, admin | CB-55/admin permissions | Не входит в CB-54 slice |
| Accept | `AssignmentService.accept`; CB-53 планирует один POST | Да | CB-53 merged | Не дублировать в CB-54 |
| Мои assignments list/detail | `AssignmentService.cards/card`; scoped DB projections | Да | CB-53 shell + thin actor glue | **CB-54** |
| Withdraw | `AssignmentService.cancel`; exact state/refund/outbox | Да | HTTP receipt owner decision | Следующий performer mutation |
| Replacement | assignment generation/slot owners | Да | withdraw + owner lifecycle | Позже отдельным slice |
| Submission drafts/result versions | staged `AssignmentService` draft/confirm + immutable versions | Да | HTTP receipt + schema-driven form | После withdraw |
| Full/partial/reject/revision | `AssignmentService.decide`; settlement/ledger | Да, creator/reviewer | owner/reviewer screen | Позже, не admin moderation |
| Deadlines/reminders/expiry/no-show/finalizers | worker + `AssignmentService.finalize_*`; outbox | Только read state | worker/deployment | UI показывает, не реализует engine |
| Dispute entry/history | `AssignmentService.begin_dispute`; moderation case projection | Да | privacy + receipt + CB-55 boundary | Позже performer dispute |
| Authoritative conflicts | application/moderation owners | Ошибка/receipt UI | reviewer/admin authorization | Позже рядом с review |
| Notifications | PostgreSQL outbox worker | Deep links позже | CB-56 | Не входит |

Ни одна строка не разрешает domain-engine rewrite. Отсутствующий owner означает
stop/gap; capability остаётся в roadmap и не удаляется.

## Ponytail full и одноразовый аудит

Лестница Ponytail остановилась на reuse: нужные list/detail projections уже
есть. Не нужны endpoint framework, client SDK, state manager, frontend
framework, websocket, event bus, новый repository/service/table или generic
pagination abstraction.

`yagni:` исходная формулировка «полный движок одним diff» заменяется
последовательной capability map и одним read slice; replacement — существующие
owners + два GET routes. `[CB-54]`

`delete:` из scope удалены POST withdraw/submit/review/dispute до появления
authoritative HTTP receipt owner; replacement — отдельные owner-approved
vertical slices. `[CB-54]`

`net: -0 lines, -0 deps possible` в текущем репозитории: planning-only аудит
ничего не удаляет. Потенциально предотвращены новые framework/abstraction files
и dependencies; line-golf и несвязанный cleanup запрещены.
