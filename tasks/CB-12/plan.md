# CB-12 — план кармы, профилей, статистики и лидерборда

## Цель

Дать участнику цельную наблюдаемую ценность: безопасно открыть профиль или
каталог активных участников, оставить допущенному человеку карму, увидеть свою
статистику и основной лидерборд. Все записи идемпотентны, приватность автора
проверяется сервером, а расчёты воспроизводятся из журналов.

## Уровень и область

Уровень 3: migration `0008`, domain/application/infrastructure, Telegram router,
PostgreSQL integration и synthetic aiogram. Реализация выполняется одним крупным
циклом; targeted gate запускается после готовности всего кода. Полная продуктовая
регрессия не входит.

## Схема `0008`

### `members.permissions_json`

JSONB-массив с default `[]`, CHECK допускает только строки без повторов из
`karma_review|member_read`. Только существующие **active administrators** получают
оба права при upgrade; inactive administrators, moderators и members получают
`[]`; downgrade удаляет поле. Application всегда требует одновременно active
status, administrator role и exact permission, поэтому последующая приостановка
сразу блокирует сохранённое право.

### `karma_votes`

UUID, rater/target FK, value `-1|0|1`, normalized private comment 10–300,
created/updated timestamps, revision и last command UUID. DB-гарантии:
`UNIQUE(rater_id,target_id)`, запрет self-vote, допустимое value. Строка пары
блокируется перед изменением; первая конкурентная вставка защищена advisory pair
gate и unique constraint.

### `karma_vote_history`

Append-only UUID, vote FK, revision, old/new value и comment, command UUID,
actor/created timestamp; `UNIQUE(vote_id,revision)` и `UNIQUE(command_id)`.
Trigger запрещает UPDATE/DELETE. Каждая фактическая первая оценка или правка
добавляет ровно одну revision; exact replay возвращает сохранённый outcome.

### Возобновляемый диалог

Новая draft-таблица не создаётся. Существующая `conversation_states` хранит одну
durable karma draft на member: `flow_type=karma`, target, optional value/comment,
expected step и row revision. Stable identity callback — actor member из Telegram
identity плюс revision строки; отдельного draft UUID нет. `/karma` создаёт state
только если state отсутствует или уже имеет `flow_type=karma`; незавершённые
`registration`/`profile_edit`/другие flows не перезаписываются и дают понятный
отказ. Karma `/cancel` удаляет state только при `flow_type=karma`, иначе передаёт
управление владельцу другого flow. Подтверждение удаляет state в той же
транзакции, где создаются vote/history, audit/outbox/receipt.

## Допуск и карма

Eligibility не дублируется отдельной таблицей. Она выводится из неизменяемой
истории: существует исходная положительная `task_reward_earned` или
`partial_task_reward` transaction с assignment и member-origin task, где rater и
target были creator/performer в любом направлении. Reversal/correction не удаляет
исходную выплату, поэтому допуск сохраняется навсегда.

Mutation lock order: update gate → exact receipt → Telegram identity gate →
locked `conversation_states` row с exact `flow_type`/`expected_step`/revision →
canonical karma pair gate → canonical member rows → vote row →
history/audit/outbox/receipt → один commit. До записи повторно проверяются status,
self, eligibility, value/comment и target visibility. Один command UUID с иным
payload конфликтует; новый command после прошлого изменения создаёт следующую
revision. Агрегат — `SUM(current karma_votes.value)` и count текущих строк; history,
author UUID и comments никогда не входят в participant projection, callback,
outbox или runtime log.

Raw view выполняется отдельной query-command с audit event в одной транзакции.
Для active target нужны active administrator + exact `karma_review`; для
non-active target дополнительно обязателен exact `member_read`. Moderator,
administrator без нужного пересечения прав и клиентский permission token получают
одинаковый отказ без данных и без подтверждения существования target.

## Профили и статистика

- active actor видит safe projection всех active profiles, включая aggregate
  karma, reliability и вклад; active/paused actor видит собственный профиль;
- чужой non-active профиль скрыт; active administrator с `member_read` может
  открыть его safe projection;
- отсутствующий, скрытый, stale/forged callback и недопустимый actor получают
  один неразличимый `Profile unavailable`, без поля, count или косвенного признака;
- каталог использует keyset `(normalized_display_name, member_id)`; policy
  повторно применяется после cursor и непосредственно перед projection.

Личная статистика выводится запросом из assignments/tasks/ledger: выполненные
полностью и частично задания, заработанный опыт, уникальные получатели помощи,
категории вклада, no-show и reliability. Приватные comments/raw authors не
выбираются.

## Надёжность

История разделяется на три независимых факта:

- immutable `accepted` подтверждает факт принятия и сам никогда не supersede-ится;
- один terminal root `approved|partially_approved|rejected|no_show|
  cancelled_performer|cancelled_creator` задаёт исход;
- optional responsibility chain начинается от terminal root и содержит только
  `responsibility_excused|responsibility_restored`; каждый новый элемент обязан
  ссылаться на текущий leaf того же assignment.

Constraint trigger `0008` запрещает цикл, cross-assignment supersede, supersede
`accepted`, повторное supersede уже покрытого leaf и второй terminal root.
Effective responsibility — последний leaf: `cancelled_creator` или
`responsibility_excused` исключают assignment из denominator; restored и прочие
terminal roots включают. Numerator определяется исходным terminal root:
`approved=1`, `partially_approved=0.5`, остальные `0`; effective no-show — root
`no_show`, если responsibility не исключена. Публичный rate показывается только
от пяти учитываемых assignment, иначе `Недостаточно данных`.

CB-12 только читает этот контракт и добавляет DB foundation/fixtures для chain.
Публичная state-changing correction и её отдельное moderation permission остаются
CB-13; `karma_review` для изменения надёжности не используется.

## Лидерборд

Только active members. Порядок:

1. authoritative `SUM(account_transactions.experience_delta) DESC`;
2. число уникальных recipients member-origin paid assignments DESC;
3. reliability DESC, достаточный sample раньше недостаточного;
4. effective no-show ASC;
5. время первого достижения текущего experience total ASC;
6. member UUID ASC как технический стабильный tie-breaker.

Время достижения считается оконным запросом по account ledger: первое время,
когда running experience sum стал равен текущей authoritative сумме; для нулевого
опыта sentinel — `members.registered_at`. Полный total order сериализует cursor как
`(experience, recipients, sufficient_sample, reliability_or_zero, no_show,
reached_at, member_id)`, где `sufficient_sample=true` сортируется раньше, а rate
недостаточного sample кодируется `0` только после отдельного флага. Credits и
karma не входят ни в один sort key. Версия level cache не входит в cursor и не
влияет на порядок; профильный level отдельно разрешается по active config.
`experience_total_cached` используется лишь reconciliation assertion, а намеренно
stale `level_config_version_id` не меняет выдачу. Для 20–30 участников ledger
query проще и надёжнее отдельного leaderboard cache.

## Telegram

- `/profile [member_id]`, `/members`, `/stats`, `/leaderboard`;
- `/karma <member_id>` создаёт или восстанавливает state; value и comment
  сохраняются до preview, callback `karma:confirm:<revision>` применяет;
- `/cancel` удаляет только текущую karma draft;
- callback ≤64 bytes, exact replay стабилен, stale revision и forged target не
  раскрывают существование профиля;
- все ответы пользовательские на русском, технические runtime errors на
  английском и без private comment/author.

## Изменяемые компоненты

- migration/models и новый DB repository репутации;
- domain/application service и расширение общего UoW;
- Telegram router и bootstrap composition;
- `docs/mvp/05_BOT_INTERFACE.md`, `06_DATA_MODEL.md`, при необходимости точечная
  синхронизация `02_DOMAIN_RULES.md`, `07_SECURITY_AND_PRIVACY.md`,
  `10_TEST_PLAN.md`;
- unit/integration/synthetic Telegram tests и артефакты задачи.

## Готовность

- восемь Jira AC и все сценарии `test-plan.md` имеют фактические доказательства;
- empty/`0007↔0008` migration cycle, targeted PostgreSQL/Telegram suite без skip;
- Ruff, ty, build, bot/worker entrypoints, diff/link/secret checks зелёные;
- implementation report и одно независимое final review готового staged diff
  имеют `Status: approved`; затем PR, CI, merge в main и Jira `Готово`.

Дефекты, найденные до готовности targeted gate, исправляются в этой ветке.
Дефекты будущей полной регрессии CB-16 оформляются отдельно.
