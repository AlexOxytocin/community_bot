# CB-21 — отчёт реализации

## Результат

Telegram-интерфейс MVP собран в единый navigation router поверх существующих прикладных
сервисов. Active member получает полное главное меню, ищет и принимает задания, выбирает шаблон
создания, читает собственный баланс и справку без ручного ввода UUID. Active administrator через
`/admin` создаёт одноразовую кликабельную ссылку-приглашение и открывает очереди заявок и
модерации. Все административные callbacks имеют отдельную повторную проверку роли и статуса.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| Полное главное меню после active `/start` | Пройден | Production Dispatcher E2E проверяет девять кнопок и сохраняет существующий registration flow |
| Доступные задания без ручного UUID | Пройден | PostgreSQL query, карточки с `Взять`, 10-item keyset page и достижимое 11-е задание |
| Authoritative acceptance policy | Пройден | Уровень, дедлайн, слот, self/already-assigned, санкция и configurable active limit проверяются до показа или повторно при callback |
| Создание задания из каталога | Пройден | `/create` и template callback открывают durable draft; последующий FSM-текст доходит до task router |
| Баланс и история | Пройден | Только own profile balance и 10 safe ledger rows без комментариев |
| Краткая помощь | Пройден | `/help`, reply keyboard и `docs/operations/USER_GUIDE.md` |
| Рабочее admin menu | Пройден | Active-admin gate перед invite/registrations/moderation; invitation выдаётся как `t.me` deep link |
| Отказ для остальных ролей и tampering | Пройден | Member/moderator/pending/unknown и forged callbacks не получают данные или effects; invalid UUID даёт safe error |
| Совместимость и качество | Пройден | Synthetic registration/catalog/task/assignment flows, Ruff, ty, build, entrypoints и diff-check зелёные |

## Проверочная матрица

- production `_dispatcher` + fake Bot API: `/start`, reply buttons, `/tasks` → `Взять`, exact
  replay после реконструкции Dispatcher, `/create` → template → persistent next step, `/balance`,
  `/help`, `/admin` → invite/queues;
- pagination: 11 опубликованных задач дают страницы `10 + 1`, страницы не пересекаются,
  отсутствующий либо существующий, но уже недоступный task cursor безопасно перезапускает
  актуальную первую страницу;
- policy: три active assignments скрывают список при active limit `3`; active acceptance
  restriction отклоняет чтение до раскрытия карточек;
- authorization: member, moderator, pending administrator и unknown actor не проходят admin gate;
- tampering: malformed task/template callback не создаёт assignment, draft или invitation;
- invitation delivery: deep link с `_` в фактическом bot username и URL-safe token отправляется
  как explicit plain text без Telegram Markdown parsing;
- compatibility: существующие Telegram-сценарии регистрации, каталога, создания задания и
  отправки результата работают при новом порядке routers.

## Выполненные команды

- `uv run pytest -ra --no-cov tests/integration/test_navigation.py ...` — `7 passed`, без
  skip/deselect; в набор вошли четыре существующих synthetic Telegram сценария;
- повторный точный `tests/integration/test_navigation.py` — `3 passed`;
- `uv run ruff format --check .` — `300 files already formatted`;
- `uv run ruff check .` — успешно;
- `uv run ty check` — успешно;
- `uv build` — sdist и wheel собраны;
- `uv run community-bot --check` и `uv run community-worker --check` — успешно;
- `git diff --check` — успешно.

Полная регрессия намеренно не запускалась: по принятому процессу она выполняется один раз в
CB-16 после слияния CB-20 и CB-21.

## Отклонения и остаточные риски

Отклонений от одобренного плана нет. Список `/tasks` является актуальным read projection, но
конкурентное принятие последнего слота окончательно решает существующий assignment service —
карточка сама по себе не резервирует слот. Deep link строится по фактическому username Bot API,
а при отсутствии bot context остаётся рабочая команда `/start <token>`.
