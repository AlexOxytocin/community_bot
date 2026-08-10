# CB-8 — контекст источников плана

## Jira

- CB-8: «Реализовать регистрацию по приглашению и профиль участника», статус на
  старте `К выполнению`, после начала работы `В работе`.
- Единственный входящий блокер CB-7 имеет статус `Готово`.
- CB-8 блокирует итоговую подготовку пилота CB-16.

## Канонические требования

- `docs/mvp/01_PRODUCT_REQUIREMENTS.md`: регистрация только по приглашению,
  изменение собственной карточки, администратор выдаёт invite, moderator/admin
  рассматривает регистрацию.
- `docs/mvp/02_DOMAIN_RULES.md` и D-012: первое одобрение создаёт ровно один
  `starting_grant` на `5` кредитов и `0` опыта.
- `docs/mvp/03_USER_FLOWS.md`: полный порядок полей анкеты и возврат `/start` к
  незавершённому шагу.
- `docs/mvp/05_BOT_INTERFACE.md`: `/start`, `/profile`, `/registrations`,
  PostgreSQL как источник состояния и собственная карточка.
- `docs/mvp/06_DATA_MODEL.md`: `members`, `invitations`,
  `conversation_states`, receipts, audit и экономика.
- `docs/mvp/10_TEST_PLAN.md`: invite, restart, конкурентное одобрение,
  отсутствие прав у pending и стабильность Telegram user ID.
- `docs/mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md`: D-012 принят; Q-011 остаётся
  открытым, поэтому чужие профили исключены.
- ADR-0005: Python 3.13, aiogram 3.x, PostgreSQL 18, SQLAlchemy async, Alembic,
  модульный монолит и единый unit of work.

## Фактическая база реализации

- `members.telegram_user_id` уже `BIGINT UNIQUE` и является идентичностью.
- `processed_telegram_updates` и update advisory gate дают защиту повторной
  доставки Telegram update.
- `account_transactions` уже гарантирует один `starting_grant` на member и
  append-only журнал.
- `SqlAlchemyEconomyMutation` получает economy gates до member rows; составное
  approval сохраняет этот порядок через публичный `prepare_batch`, включает
  actor в общий lock scope и выполняет authorization до `apply()`.
- Текущий router отвечает после commit, но реализует только минимальный `/start`.

## Решения плана, не меняющие продукт

- Свободные категории помощи и skill tags временно хранятся JSON-снимками в
  профиле, потому что управляемый каталог принадлежит CB-9. Это не открывает
  каталог и не создаёт право просмотра чужих карточек.
- Отклонённая заявка остаётся `pending` и может быть исправлена/отправлена снова;
  существующий закрытый набор account statuses не расширяется скрытым статусом.
- Invite-token не хранится открыто; runtime secret поступает только через env и
  не попадает в git/Jira/артефакты.
- Telegram update gate защищает повтор одного update, а новый identity gate по
  полному Telegram user ID защищает разные конкурентные updates. Каждая FSM-
  мутация дополнительно сверяет переданный `expected_step` с locked state.

## Границы

План не разрешает Q-011, не добавляет production deployment, не реализует CB-9
и не переносит полную регрессию CB-16 внутрь текущей задачи.
