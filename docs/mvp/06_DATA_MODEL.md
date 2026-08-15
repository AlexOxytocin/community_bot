# Концептуальная модель данных

Модель реализуется в PostgreSQL 18 через SQLAlchemy 2.x async и Alembic. Поля ниже концептуальны: точные типы, имена ограничений и индексов фиксируются миграциями без изменения описанных доменных инвариантов.

## 1. Участники

### `members`

```text
id UUID/INTEGER PK
telegram_user_id BIGINT UNIQUE NOT NULL
telegram_username TEXT NULL
display_name TEXT NOT NULL
city TEXT NULL
timezone TEXT NOT NULL
short_bio TEXT NULL
current_goal TEXT NULL
availability TEXT NULL
help_categories_json JSONB NOT NULL DEFAULT []
skill_tags_json JSONB NOT NULL DEFAULT []
role TEXT NOT NULL
status TEXT NOT NULL
level_number INTEGER NOT NULL
credit_balance_cached BIGINT NOT NULL DEFAULT 0
experience_total_cached BIGINT NOT NULL DEFAULT 0
level_config_version_id UUID FK NULL
invited_by_member_id FK NULL
registered_at TIMESTAMP NOT NULL
approved_at TIMESTAMP NULL
last_activity_at TIMESTAMP NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
```

### `member_skills`

```text
member_id FK
skill_tag_id FK
PRIMARY KEY(member_id, skill_tag_id)
```

### `member_help_categories`

```text
member_id FK
category_id FK
PRIMARY KEY(member_id, category_id)
```

До реализации управляемого каталога CB-9 регистрация хранит введённые категории
помощи и теги навыков как нормализованные JSON-массивы в `members`. CB-9 должна
перенести эти значения в справочники без потери пользовательского текста; JSON-
снимки не используются для решений о доступе.

## 2. Приглашения

### `invitations`

```text
id PK
code_hash UNIQUE NOT NULL
created_by_member_id FK
intended_telegram_user_id NULL
max_uses INTEGER NOT NULL DEFAULT 1
uses_count INTEGER NOT NULL DEFAULT 0
expires_at TIMESTAMP NULL
revoked_at TIMESTAMP NULL
created_at TIMESTAMP NOT NULL
```

В базе хранится хеш кода, а не открытый код.

### `invitation_redemptions`

```text
id UUID PK
invitation_id UUID FK NOT NULL
member_id UUID FK UNIQUE NOT NULL
redeemed_at TIMESTAMP NOT NULL
UNIQUE(invitation_id, member_id)
```

### `registration_applications`

```text
member_id UUID PK/FK
status TEXT NOT NULL  # draft/submitted/approved/rejected
consented_at TIMESTAMP NULL
submitted_at TIMESTAMP NULL
reviewed_at TIMESTAMP NULL
reviewed_by_member_id UUID FK NULL
review_comment TEXT NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
```

Отклонение не создаёт скрытый статус аккаунта: `members.status` остаётся
`pending`, а заявка возвращается из `rejected` в `draft` при исправлении.

## 3. Каталог

### `task_categories`

```text
id PK
code UNIQUE NOT NULL
name NOT NULL
description NULL
icon NULL
sort_order NOT NULL
visibility TEXT NOT NULL DEFAULT 'public'
creation_mode TEXT NOT NULL DEFAULT 'template'
is_active NOT NULL
```

### `task_templates`

```text
id PK
category_id FK
code NOT NULL
version INTEGER NOT NULL
name NOT NULL
description NOT NULL
creator_instructions NOT NULL
performer_instructions NOT NULL
completion_criteria NOT NULL
input_schema_json NOT NULL
result_schema_json NOT NULL
credit_reward INTEGER NOT NULL
estimated_minutes INTEGER NOT NULL
format TEXT NOT NULL
minimum_level INTEGER NOT NULL
maximum_performers INTEGER NOT NULL DEFAULT 1
moderation_required BOOLEAN NOT NULL
is_active BOOLEAN NOT NULL
created_at NOT NULL
UNIQUE(code, version)
```

Содержимое версии неизменяемо на уровне PostgreSQL; допускается только
переключение `is_active`. Частичный уникальный индекс разрешает не более одной
активной версии одного `code`. Изменение награды или другого содержимого
деактивирует прежнюю строку и вставляет следующую версию одной транзакцией.
Категория также не удаляется и сохраняет идентичность; для рабочего справочника
создания дополнительно задаются видимость `public|admin_only` и режим
`template|freeform|both`. В меню свободного создания попадают только active
категории с `creation_mode=freeform|both`, а `admin_only` доступна только
администратору.

`input_schema_json` и `result_schema_json` используют закрытые object-схемы
JSON Schema Draft 2020-12 без удалённых `$ref`. Input проверяется до создания
доменной команды задания, result — по точной исторической версии шаблона.

## 4. Задания

### `task_creation_drafts`

```text
id UUID PK
creator_id FK NOT NULL
origin TEXT NOT NULL DEFAULT 'member' CHECK(origin IN ('member', 'community'))
reviewer_admin_id FK NULL
community_approval_requested_at TIMESTAMP WITH TIME ZONE NULL
community_approved_by_admin_id FK NULL
community_approved_at TIMESTAMP WITH TIME ZONE NULL
template_id FK NULL
category_id FK NULL
task_kind TEXT NULL
time_size TEXT NULL
title TEXT NULL
description TEXT NULL
completion_criteria TEXT NULL
credit_reward_per_performer INTEGER NULL
estimated_minutes INTEGER NULL
input_payload_json JSON NULL
deadline_at TIMESTAMP WITH TIME ZONE NULL
format TEXT NULL
city TEXT NULL
materials_json JSON NULL
performer_slots INTEGER NULL
current_step TEXT NOT NULL
revision INTEGER NOT NULL
is_current BOOLEAN NOT NULL
publish_command_id UUID UNIQUE NOT NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
updated_at TIMESTAMP WITH TIME ZONE NOT NULL
```

У участника может быть несколько незавершённых черновиков, но только один
текущий. Каждый ответ сверяет ожидаемые шаг и revision. Для свободного задания
`template_id IS NULL`, а карточка собирается из полей `category_id`,
`task_kind`, `time_size`, `title`, `description`, `completion_criteria`,
`credit_reward_per_performer`, `materials_json`, срока и формата. Community-
черновик создаёт active administrator; до публикации в нём сохраняется другой
active administrator как независимый `reviewer_admin_id`. Если создатель не
является суперадминистратором, публикация сначала сохраняет
`community_approval_requested_at`; после подтверждения суперадминистратором
заполняются `community_approved_by_admin_id` и `community_approved_at`. После
публикации черновик остаётся исторической связью с заданием, получает
terminal-шаг и перестаёт быть текущим.

### `tasks`

```text
id PK
origin TEXT NOT NULL CHECK(origin IN ('member', 'community'))
template_id FK NULL
template_version INTEGER NULL
creator_id FK NULL
created_by_admin_id FK NULL
reviewer_admin_id FK NULL
community_approved_by_admin_id FK NULL
author_display_name TEXT NOT NULL
category_id FK NOT NULL
title NOT NULL
description NOT NULL
completion_criteria NOT NULL
materials_json NOT NULL
input_payload_json NOT NULL
credit_reward_per_performer INTEGER NOT NULL
performer_slots INTEGER NOT NULL
reserved_credit_total INTEGER NOT NULL
estimated_minutes INTEGER NOT NULL
time_size TEXT NULL
minimum_level INTEGER NOT NULL
format TEXT NOT NULL
city NULL
deadline_at TIMESTAMP NOT NULL
status TEXT NOT NULL
safety_snapshot_json JSON NOT NULL
high_reward_justification TEXT NULL
high_reward_confirmed_by_admin_id FK NULL
publish_command_id UUID UNIQUE NOT NULL
published_at TIMESTAMP NULL
cancelled_at TIMESTAMP NULL
closed_for_new_performers_at TIMESTAMP NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
```

Для задания участника `creator_id` обязателен, а
`reserved_credit_total = credit_reward_per_performer * performer_slots`.
Свободное задание участника имеет `template_id IS NULL`, `template_version IS NULL`;
его заголовок, описание, критерии, размер и категория сохраняются снимком
карточки. Статус `closed_for_new_performers` означает, что групповое задание уже
не доступно для новых исполнителей, но текущие активные assignments могут быть
отменены по согласию или доведены до результата.
Для нового задания сообщества `creator_id IS NULL`, `reserved_credit_total = 0`,
`created_by_admin_id`, `reviewer_admin_id` и `community_approved_by_admin_id`
заполнены; legacy community-строки без provenance остаются читаемыми.
Поля карточки являются снимком точной версии шаблона и после публикации не
редактируются. Исключение — операционный указатель `reviewer_admin_id`
community-задачи: его можно заменить только на другого active administrator,
который не является creator или performer. DB-trigger продолжает запрещать
изменение остальных полей снимка. Публикация и отмена имеют уникальные command
ID и выполняются в одной транзакции с ledger, audit, outbox и Telegram receipt.

### `outbox_events`

```text
id UUID PK
event_type TEXT NOT NULL
aggregate_type TEXT NOT NULL
aggregate_id UUID NOT NULL
payload_json JSON NOT NULL
business_key TEXT UNIQUE NOT NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
published_at TIMESTAMP WITH TIME ZONE NULL
status TEXT NOT NULL
attempt_count INTEGER NOT NULL
next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL
lease_token UUID NULL
lease_expires_at TIMESTAMP WITH TIME ZONE NULL
last_error_code TEXT NULL
```

CB-10 записывает `task.published` и `task.cancelled`. Доставка outbox является
отдельной ответственностью worker; приватные input и материалы в payload не
копируются.

`pending` и истёкший `processing` доступны для claim через `FOR UPDATE SKIP
LOCKED`. Актуальный `lease_token` ограждает завершение от старой копии worker.
Materialization одним commit создаёт адресные записи и переводит событие в
`materialized`; после пяти неуспешных попыток poison event становится `failed`.

### `notifications`

```text
id UUID PK
member_id UUID FK NOT NULL
notification_type TEXT NOT NULL
payload_json JSON NOT NULL
status TEXT NOT NULL
scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL
attempt_count INTEGER NOT NULL
next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL
lease_token UUID NULL
lease_expires_at TIMESTAMP WITH TIME ZONE NULL
sent_at TIMESTAMP WITH TIME ZONE NULL
last_error_code TEXT NULL
deduplication_key TEXT UNIQUE NOT NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
updated_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Payload строится по allowlist и не копирует input, материалы, комментарии,
доказательства или токены. Успешная отправка сохраняет `sent`; временная ошибка
использует ограниченный backoff, permanent error или пятая попытка — `failed`.
Окно доставки участника по умолчанию `[09:00,21:00)` в его IANA timezone.

### `process_heartbeats`

```text
process_name TEXT PK
release TEXT NOT NULL
migration_revision TEXT NOT NULL
observed_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Readiness сверяет PostgreSQL, Alembic head, свежий heartbeat и отсутствие
terminal failed outbox events. Таблица не содержит секретов или пользовательских
данных.

### `assignments`

```text
id PK
task_id FK
performer_id FK
slot_number INTEGER NOT NULL
status TEXT NOT NULL
accepted_at TIMESTAMP NOT NULL
cancelled_at TIMESTAMP NULL
submitted_at TIMESTAMP NULL
review_deadline_at TIMESTAMP NULL
rejected_at TIMESTAMP NULL
reject_dispute_deadline_at TIMESTAMP NULL
terminal_command_id UUID UNIQUE NULL
terminal_outcome TEXT NULL
cancellation_reason TEXT NULL
UNIQUE(task_id, performer_id)
UNIQUE(task_id, slot_number) WHERE status занимает слот
```

### `assignment_result_versions`

```text
id PK
assignment_id FK
version INTEGER NOT NULL
payload_json NOT NULL
submitted_at TIMESTAMP NOT NULL
UNIQUE(assignment_id, version)
submit_command_id UUID UNIQUE NOT NULL
```

Любая строка назначения сохраняется как история. Только состояние `cancelled`
освобождает slot и разрешает replacement новой строкой; частичный уникальный
индекс защищает все остальные состояния. В частности, оплаченный `approved` или
`partially_approved` slot остаётся занятым и не назначается повторно, пока другой
slot задачи свободен.

### `assignment_submission_drafts`

```text
id UUID PK
assignment_id FK NOT NULL
performer_id FK NOT NULL
submit_command_id UUID UNIQUE NOT NULL
revision INTEGER NOT NULL
payload_json JSONB NULL
submitted_result_id FK NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
updated_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Это сохраняемый Telegram-диалог отправки одной версии результата.
`submit_command_id` создаётся один раз при начале ввода, предпросмотр изменяется
только по точной `revision`, а подтверждение связывает черновик с одной
append-only версией. Для v2 создаётся следующий черновик с новой command identity;
состояние процесса не хранится в памяти бота.

### `assignment_disputes`

```text
id UUID PK
assignment_id FK UNIQUE NOT NULL
performer_id FK NOT NULL
comment TEXT NOT NULL
open_command_id UUID UNIQUE NOT NULL
opened_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Запись открытия спора неизменяема. Приватный комментарий не копируется в outbox
и логи; административное решение добавит CB-13.

## 5. Экономика

### `account_transactions`

```text
id UUID PK
member_id UUID FK
credit_delta BIGINT NOT NULL
experience_delta BIGINT NOT NULL DEFAULT 0
transaction_type TEXT NOT NULL
idempotency_key UNIQUE NOT NULL
payload_hash TEXT NOT NULL
created_by_member_id UUID FK NULL
reason TEXT NULL
comment TEXT NULL
reversed_transaction_id UUID FK UNIQUE NULL
task_id UUID FK NULL
assignment_id UUID FK NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Ограничения:

- запись не редактируется после создания;
- коррекция создаёт новую обратную запись;
- кэш баланса и опыта обновляется в той же транзакции;
- периодическая сверка сравнивает кэш с суммой журнала.
- допустимые типы и соотношения дельт ограничены PostgreSQL CHECK;
- один участник получает не более одного `starting_grant`;
- `fraud_reversal` является точной обратной записью и может быть создана для
  исходной операции только один раз;
- поля `task_id` и `assignment_id` добавлены CB-11 с настоящими внешними ключами;
  `interaction_alert_id` появится вместе с таблицей алертов, а не как висячий UUID.

## 6. Продуктовая конфигурация и уровни

### `product_config_versions`

```text
id UUID PK
version BIGINT UNIQUE NOT NULL
schema_version INTEGER NOT NULL
content_hash TEXT UNIQUE NOT NULL
payload_json JSONB NOT NULL
created_by_member_id UUID FK NOT NULL
created_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Версия неизменяема. Повторная загрузка той же пары `version + content_hash`
идемпотентна; коллизия номера или повтор снимка под новым номером отклоняется.

### `product_config_activations`

```text
id UUID PK
activation_command_id UUID UNIQUE NOT NULL
product_config_version_id UUID FK NOT NULL
activated_by_member_id UUID FK NOT NULL
outcome_code TEXT NOT NULL
reason TEXT NOT NULL
activated_at TIMESTAMP WITH TIME ZONE NOT NULL
```

### `active_product_config`

```text
singleton_key BOOLEAN PK CHECK(singleton_key)
product_config_version_id UUID FK NOT NULL
activation_id UUID FK NOT NULL
updated_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Активация одной транзакцией создаёт историю команды и переключает единственную
строку-указатель. Откат — новая строка активации к старой неизменяемой версии.

### `levels`

```text
product_config_version_id UUID FK NOT NULL
level_number INTEGER NOT NULL
experience_required BIGINT NOT NULL
display_name TEXT NOT NULL
description TEXT NULL
level_up_message TEXT NULL
permissions_json JSONB NOT NULL
PRIMARY KEY(product_config_version_id, level_number)
UNIQUE(product_config_version_id, experience_required)
```

`members.level_number` — восстанавливаемый кэш. Все проверки доступа сверяют
активную версию через `LevelResolver`; backfill после активации идемпотентен.

### `level_backfill_runs`

```text
id UUID PK
activation_id UUID FK UNIQUE NOT NULL
product_config_version_id UUID FK NOT NULL
processed_members INTEGER NOT NULL
outcome_code TEXT NOT NULL
completed_at TIMESTAMP WITH TIME ZONE NOT NULL
```

История версий, уровней, активаций и завершённых backfill является append-only.
Активный указатель нельзя удалить или сменить его singleton key; разрешено
только атомарно переключить его на сохранённую версию через новую активацию.

## 7. Карма

### `karma_votes`

```text
id PK
rater_id FK NOT NULL
target_id FK NOT NULL
value INTEGER NOT NULL CHECK(value IN (-1, 0, 1))
comment TEXT NOT NULL
revision INTEGER NOT NULL CHECK(revision > 0)
last_command_id UUID UNIQUE NOT NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
UNIQUE(rater_id, target_id)
CHECK(rater_id <> target_id)
```

### `karma_vote_history`

```text
id PK
karma_vote_id FK NOT NULL
revision INTEGER NOT NULL
old_value INTEGER NULL
new_value INTEGER NOT NULL
old_comment TEXT NULL
new_comment TEXT NOT NULL
command_id UUID UNIQUE NOT NULL
actor_member_id FK NOT NULL
created_at TIMESTAMP NOT NULL
UNIQUE(karma_vote_id, revision)
```

`karma_vote_history` защищена trigger от `UPDATE`/`DELETE`. История и текущие raw
строки доступны только active administrator с `karma_review`; non-active target
дополнительно требует `member_read`, а каждый фактический просмотр создаёт audit.

Возобновляемый диалог кармы использует общую `conversation_states` с
`flow_type=karma` и монотонной `revision`; отдельная draft-таблица не создаётся.
Поле `members.permissions_json` допускает только `karma_review`, `member_read`,
`interaction_review` и `superadministrator`.

Eligibility не дублируется: он выводится из исходной положительной
`task_reward_earned|partial_task_reward` с `assignment_id` и member-origin task.
Append-only ledger сохраняет этот факт навсегда даже после reversal.

## 8. Споры и санкции

### `assignment_disputes` и `moderation_cases`

```text
assignment_disputes: immutable opening comment/performer/command/opened_at
moderation_cases: assignment_id, case_type, mutable status/current_resolution/revision
dispute_evidence: append-only safe reference metadata
dispute_resolutions: append-only version 1|2, code, actor, payload hash, effect links
dispute_appeals: не более одной append-only appeal на case
moderation_decision_drafts: restart-safe Telegram preview/confirm identity
```

`reliability_outcome_corrections` хранит append-only смену effective terminal
outcome при appeal. `assignments.slot_ever_paid=true` необратим и сохраняет
занятость оплаченного слота независимо от последующего статуса.

### `member_sanctions`

```text
member_sanctions: target/author/type/actions/reason/start/end/previous+applied status/state/command
sanction_events: append-only issued|revoked|expired с actor/reason/command
```

### `interaction_alerts`

```text
id PK
first_member_id FK NOT NULL
second_member_id FK NOT NULL
state TEXT NOT NULL
opened_at TIMESTAMP NOT NULL
closed_at TIMESTAMP NULL
interaction_count INTEGER NOT NULL
window_days INTEGER NOT NULL
threshold INTEGER NOT NULL
config_version_id FK NOT NULL
outcome TEXT NULL
meeting_notes TEXT NULL
```

Частичный уникальный индекс разрешает не более одного открытого алерта на
неупорядоченную пару. Создание и обновление сериализуются блокировкой пары.

### `interaction_alert_assignments`

```text
interaction_alert_id FK NOT NULL
assignment_id FK NOT NULL
PRIMARY KEY(interaction_alert_id, assignment_id)
```

Penalty хранится в общем immutable ledger с idempotency key
`interaction-alert:{alert_id}:penalty:{member_id}` и audit-ссылкой на alert.

### `moderation_risk_signals` и `karma_vote_moderation`

Risk signal содержит приватный тип, target, нормализованный entity key, UTC
bucket idempotency key и безопасные details без raw comment. Karma moderation —
append-only `excluded|restored` события для exact `karma_vote_id + revision`;
aggregate использует последнее событие только для текущей revision.

Приватные заметки доступны только активным администраторам с правом
`interaction_review` и исключаются из прикладных логов и уведомлений.

### `reliability_events`

```text
id PK
assignment_id FK NOT NULL
event_type TEXT NOT NULL
supersedes_event_id FK NULL
reason TEXT NULL
created_by_member_id FK NULL
created_at TIMESTAMP NOT NULL
```

Коррекция `no_show` добавляет событие, а не изменяет или удаляет исходное.

## 9. Уведомления и диалоги

### `notifications`

```text
id PK
member_id FK
type TEXT NOT NULL
payload_json NOT NULL
status TEXT NOT NULL
scheduled_at TIMESTAMP NOT NULL
sent_at TIMESTAMP NULL
attempt_count INTEGER NOT NULL DEFAULT 0
deduplication_key UNIQUE NOT NULL
```

### `conversation_states`

```text
member_id PK/FK
flow_type TEXT NOT NULL
current_step TEXT NOT NULL
payload_json NOT NULL
expires_at TIMESTAMP NULL
updated_at TIMESTAMP NOT NULL
```

Строка является единственным долговечным владельцем следующего свободного
текста участника. `flow_type` выбирает ровно один из диалогов регистрации,
редактирования профиля, создания задания, результата, спора или кармы;
`payload_json` хранит только техническую ссылку и revision, а предметные данные
остаются в своих таблицах. Начало другого flow атомарно переключает владельца,
но не удаляет сохранённый предметный черновик. Регистрацию и редактирование
профиля нельзя вытеснить без явной отмены.

Для регистрации и редактирования профиля mutation-протокол использует порядок
`update gate → telegram identity gate → locked state → expected_step`.
Команда `/cancel` переводит регистрационный flow в `registration_paused`, не
удаляя шаг и payload; следующий `/start` возвращает flow в `registration`.
Незавершённое редактирование профиля при отмене удаляется без изменения уже
подтверждённых полей карточки.

## 10. Аудит

### `audit_events`

```text
id PK
actor_member_id FK NULL
action TEXT NOT NULL
entity_type TEXT NOT NULL
entity_id TEXT NOT NULL
before_json NULL
after_json NULL
reason TEXT NULL
created_at TIMESTAMP NOT NULL
```

## 11. Обработанные Telegram updates

### `processed_telegram_updates`

```text
update_id BIGINT PK
update_type TEXT NOT NULL
actor_member_id UUID FK NULL
outcome_code TEXT NOT NULL
received_at TIMESTAMP WITH TIME ZONE NOT NULL
processed_at TIMESTAMP WITH TIME ZONE NOT NULL
```

Инварианты этапа фундамента участников:

- receipt создаётся для каждого принятого transport update, включая read-only `/start`; update без пригодного `from_user` отбрасывается до транзакции;
- первая операция транзакции получает advisory lock по детерминированному 64-битному хешу namespace `telegram_update` и полного `BIGINT update_id`, после чего duplicate подтверждается точным чтением первичного ключа;
- запись добавляется только полностью заполненной в конце успешной транзакции; `outcome_code` и `processed_at` не могут быть `NULL`;
- receipt, доменное изменение и audit event фиксируются одним commit; rollback не оставляет ни одного из этих эффектов;
- сохранённый `outcome_code` является результатом для повторной обработки и не зависит от повторно переданного payload;
- гарантия «не более одного эффекта» относится к PostgreSQL. Ответ Bot API выполняется после commit и до появления outbox может безопасно повториться или потеряться;
- политика удаления старых receipts должна быть определена до пилота и не должна разрешать повторную обработку updates в пределах окна доставки Telegram.

### Точные ограничения реализованного этапа

- `members.id`, `audit_events.id` и внешние ключи участников используют UUID;
- `members.role` ограничен значениями `member`, `moderator`, `administrator`;
- `members.status` ограничен значениями `pending`, `active`, `paused`, `restricted`, `suspended`, `left`, `banned`;
- `audit_events` является append-only: PostgreSQL trigger отклоняет row-level `UPDATE` и `DELETE`;
- все временные поля этапа сохраняются как UTC-aware `TIMESTAMP WITH TIME ZONE`.

## 12. Индексы

Минимально необходимы индексы:

- задания по `status`, `deadline_at`, `template_id`;
- задания по `origin`, `status`, `reviewer_admin_id`;
- выполнения по `performer_id`, `status`;
- выполнения по `review_deadline_at`, `reject_dispute_deadline_at`;
- транзакции по `member_id`, `created_at`;
- участники по `status`, `experience_total_cached`;
- уведомления по `status`, `scheduled_at`;
- споры по `status`, `opened_at`.
- алерты по неупорядоченной паре и частичный уникальный индекс открытого статуса;
- версии конфигурации по `version` и `content_hash`, активации по идентификатору команды.

## 13. Миграционные последствия принятых решений

CB-4 фиксирует концептуальную модель и не добавляет миграции. Будущие задачи
реализации должны атомарно и обратно совместимо добавить:

1. Неизменяемые версии продуктовой конфигурации, историю активаций, единственный
   активный указатель и привязанные к версии уровни с backfill кэша участников.
2. `origin`, nullable-связи пользовательского шаблона и автора, снимок требований
   безопасности, независимого проверяющего и подтверждение большой награды для
   задания сообщества.
3. Пер-слотовые сроки проверки и отклонения, состояние `reviewer_required`,
   поколения замены проверяющего и append-only коррекции надёжности.
4. Алерты пары, связи с оплаченными слотами, исход встречи, приватные заметки и
   уникальные идемпотентные штрафы.
5. Тип `community_task_reward` и ссылки операций `penalty` на алерт без изменения
   существующих записей журнала.

До переключения чтения миграция должна заполнить `origin=member` для текущих
заданий и создать первую валидную активную версию конфигурации. Ни один backfill
не должен переписывать append-only журналы или историю аудита.
