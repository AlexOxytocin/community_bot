# CB-6 — независимое ревью плана

`community_bot.plan_review.verdict.v1`

Status: approved

## status

`approved`

## reviewed_sources

- Jira `CB-6`: описание, критерии приёмки, родитель, статус, приоритет, комментарий, вложения и актуальные связи `Blocks`, повторно прочитанные через Atlassian Rovo API.
- Jira `CB-2`: область, ограничения и критерии успеха родительского эпика, повторно прочитанные через Atlassian Rovo API.
- Актуальные Jira-связи: входящая `CB-3` имеет статус `Готово`; исходящие `CB-7` и `CB-9` имеют статус `К выполнению`.
- `tasks/CB-6/plan-source-context.md`, `tasks/CB-6/plan.md`, `tasks/CB-6/test-plan.md` в окончательной редакции.
- Предложенный `docs/adr/0006-telegram-update-transaction-boundary.md` и индекс `docs/adr/README.md`; статус ADR не изменялся.
- `agents/plan-reviewer/instruction.md`, `docs/PROJECT_RULES_AND_GUARDRAILS_RU.md`, `docs/AGENT_WORKFLOW.md`, `docs/JIRA_WORKFLOW.md`, `agents/workflow.yaml`.
- `docs/adr/0004-risk-tiered-development-workflow.md`, `docs/adr/0005-mvp-technology-stack.md`, `docs/ARCHITECTURE.md`, `docs/mvp/TECH_STACK.md`, `docs/mvp/01_PRODUCT_REQUIREMENTS.md`, `docs/mvp/02_DOMAIN_RULES.md`, `docs/mvp/06_DATA_MODEL.md`, `docs/mvp/07_SECURITY_AND_PRIVACY.md`, `docs/mvp/09_IMPLEMENTATION_PLAN.md`, `docs/mvp/10_TEST_PLAN.md`, `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`.
- Текущее состояние ветки `task/CB-6` и исходная реализация CB-3 без прикладных моделей, репозиториев и unit-of-work.

## scope_findings

1. Jira-контекст согласован с пакетом источников. CB-6 разблокирована завершённой CB-3 и ограничена фундаментом участников, доступа, аудита, update receipt и минимального `/start`.
2. Экономика, регистрация, каталог, карма, санкции, admin UI, outbox, реальные Telegram-операции и production provisioning administrator явно исключены и не реализуются скрыто.
3. `/start` и `Обновить меню` имеют точный русский UI-контракт без неработающих переходов. Update без пригодного `from_user` имеет безопасный детерминированный отказ без receipt и ответа.
4. Матрица доступа полностью определяет actor, статус, ownership, self/admin-target и допустимые переходы: `active ↔ paused` и `member ↔ moderator`; все остальные переходы deny-by-default.
5. Открытые вопросы `Q-002`–`Q-012` не затрагиваются. Гранулярные права `restricted` и moderator остаются последующим продуктовым решением.

## design_findings

1. ADR-0006 обосновывает сквозную транзакционную границу и согласуется с ADR-0005. `update_id` ограничен потоком одного MVP-бота; transaction-scoped PostgreSQL advisory lock сериализует одинаковые updates; duplicate определяется точным PK receipt.
2. Протокол внутренне согласован: advisory lock → exact receipt read → разрешение actor UUID без решения доступа → ordered `member UUID ASC FOR UPDATE` → повторная авторизация → действие/audit → вставка полностью заполненного receipt → commit.
3. Полуготовый receipt не существует. Обязательные `outcome_code`, `received_at` и `processed_at` защищены `NOT NULL`; прямой incomplete insert отклоняется, а rollback освобождает advisory lock и сохраняет возможность retry.
4. Exactly-once корректно ограничен PostgreSQL-эффектом. Bot API запрещён внутри транзакции и вызывается после commit; повтор или потеря безопасного ответа не маскируются более сильной гарантией.
5. Ordered row locks закрывают stale authorization, lost update и неверный audit `before`. Политика запрещает self-target, изменение текущего administrator, назначение administrator и неутверждённые переходы.
6. Append-only port и PostgreSQL trigger против row-level `UPDATE/DELETE audit_events` соответствуют заявленной неизменяемости прикладного аудита.
7. Отдельная временная database на каждый integration test позволяет удалять тестовый контур через `DROP DATABASE ... WITH (FORCE)` после закрытия engine, не обходя audit trigger и не затрагивая чужие данные.
8. Compose-backed PostgreSQL и автоматический Testcontainers fallback соответствуют принятому стеку; недоступный Docker приводит к явной ошибке, а не тихому `skip`.

## verification_findings

1. Каждый критерий Jira имеет воспроизводимое доказательство: маршрутизация — сценарии 1–5/13; повтор и rollback — 6–7; авторизация и переходы — 8; audit и конкурентность — 9–11; restart — 12; migration — 14; incomplete receipt — 15.
2. Дедупликация проверяется постоянным эффектом `member + audit + receipt` в двух независимых сессиях, а не счётчиком в памяти.
3. Fault injection между изменением target и append audit доказывает общий rollback; concurrent admin chain доказывает сериализацию и согласованный `before → after`.
4. Synthetic aiogram updates и fake session доказывают точный UI, отсутствие реальной сети и вызов Bot API только после commit.
5. Миграция `0002` проверяется циклом `upgrade head → downgrade 0001 → upgrade head`, включая таблицы, constraints, indexes и audit trigger.
6. Compose-backed полный прогон и отдельный Testcontainers fallback обязаны завершаться без skipped/deselected integration tests; CI повторяет quality и PostgreSQL/Alembic проверки на точном merge-candidate.
7. Матрица критериев правильно ссылается на restart scenario 12 и migration scenario 14.

## required_actions

- Обязательных исправлений плана до решения владельца по ADR-0006 нет.

## residual_risks

- ADR-0006 остаётся `Предложено`. По процессу владелец должен явно принять его и только затем разрешить начало реализации; это не делает `plan-reviewer`.
- Безопасный Telegram-ответ остаётся best-effort/at-least-once; надёжная доставка критических сообщений должна использовать PostgreSQL outbox в последующих задачах.
- `processed_telegram_updates` растёт без ограничения. Политика хранения должна быть утверждена до пилота без допуска повторной обработки старых updates.
- Временная database на каждый integration test увеличит длительность набора, но обеспечивает строгую изоляцию и не ослабляет audit trigger.
