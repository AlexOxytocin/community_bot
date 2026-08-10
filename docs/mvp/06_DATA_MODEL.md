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
role TEXT NOT NULL
status TEXT NOT NULL
level_number INTEGER NOT NULL
credit_balance_cached INTEGER NOT NULL DEFAULT 0
experience_total_cached INTEGER NOT NULL DEFAULT 0
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

## 3. Каталог

### `task_categories`

```text
id PK
code UNIQUE NOT NULL
name NOT NULL
description NULL
icon NULL
sort_order NOT NULL
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
repeat_limit_per_pair INTEGER NOT NULL
moderation_required BOOLEAN NOT NULL
is_active BOOLEAN NOT NULL
created_at NOT NULL
UNIQUE(code, version)
```

## 4. Задания

### `tasks`

```text
id PK
template_id FK
template_version INTEGER NOT NULL
creator_id FK
title NOT NULL
description NOT NULL
input_payload_json NOT NULL
credit_reward_per_performer INTEGER NOT NULL
performer_slots INTEGER NOT NULL
reserved_credit_total INTEGER NOT NULL
format TEXT NOT NULL
city NULL
deadline_at TIMESTAMP NOT NULL
status TEXT NOT NULL
published_at TIMESTAMP NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
```

### `assignments`

```text
id PK
task_id FK
performer_id FK
status TEXT NOT NULL
accepted_at TIMESTAMP NOT NULL
cancelled_at TIMESTAMP NULL
submitted_at TIMESTAMP NULL
approved_at TIMESTAMP NULL
result_payload_json NULL
creator_decision TEXT NULL
creator_comment TEXT NULL
idempotency_key UNIQUE NOT NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
UNIQUE(task_id, performer_id)
```

### `assignment_result_versions`

```text
id PK
assignment_id FK
version INTEGER NOT NULL
payload_json NOT NULL
submitted_at TIMESTAMP NOT NULL
UNIQUE(assignment_id, version)
```

## 5. Экономика

### `account_transactions`

```text
id PK
member_id FK
credit_delta INTEGER NOT NULL
experience_delta INTEGER NOT NULL DEFAULT 0
transaction_type TEXT NOT NULL
task_id FK NULL
assignment_id FK NULL
idempotency_key UNIQUE NOT NULL
created_by_member_id FK NULL
comment TEXT NULL
reversed_transaction_id FK NULL
created_at TIMESTAMP NOT NULL
```

Ограничения:

- запись не редактируется после создания;
- коррекция создаёт новую обратную запись;
- кэш баланса и опыта обновляется в той же транзакции;
- периодическая сверка сравнивает кэш с суммой журнала.

## 6. Уровни

### `levels`

```text
level_number INTEGER PK
experience_required INTEGER UNIQUE NOT NULL
display_name TEXT NOT NULL
description TEXT NULL
level_up_message TEXT NULL
permissions_json NOT NULL
is_active BOOLEAN NOT NULL
```

## 7. Карма

### `karma_votes`

```text
id PK
rater_id FK NOT NULL
target_id FK NOT NULL
value INTEGER NOT NULL CHECK(value IN (-1, 0, 1))
comment TEXT NOT NULL
created_at TIMESTAMP NOT NULL
updated_at TIMESTAMP NOT NULL
UNIQUE(rater_id, target_id)
CHECK(rater_id <> target_id)
```

### `karma_vote_history`

```text
id PK
karma_vote_id FK NOT NULL
rater_id FK NOT NULL
target_id FK NOT NULL
old_value INTEGER NULL
new_value INTEGER NOT NULL
old_comment TEXT NULL
new_comment TEXT NOT NULL
changed_at TIMESTAMP NOT NULL
```

История доступна только администраторам и аудиту.

## 8. Споры и санкции

### `disputes`

```text
id PK
assignment_id FK UNIQUE NOT NULL
opened_by_member_id FK NOT NULL
reason_code TEXT NOT NULL
description TEXT NOT NULL
evidence_json NULL
status TEXT NOT NULL
resolved_by_member_id FK NULL
resolution_code TEXT NULL
resolution_comment TEXT NULL
opened_at TIMESTAMP NOT NULL
resolved_at TIMESTAMP NULL
```

### `member_sanctions`

```text
id PK
member_id FK NOT NULL
type TEXT NOT NULL
reason TEXT NOT NULL
starts_at TIMESTAMP NOT NULL
ends_at TIMESTAMP NULL
created_by_member_id FK NOT NULL
revoked_at TIMESTAMP NULL
```

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

## 11. Индексы

Минимально необходимы индексы:

- задания по `status`, `deadline_at`, `template_id`;
- выполнения по `performer_id`, `status`;
- транзакции по `member_id`, `created_at`;
- участники по `status`, `experience_total_cached`;
- уведомления по `status`, `scheduled_at`;
- споры по `status`, `opened_at`.
