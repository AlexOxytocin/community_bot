# Матрица переноса возможностей в Mini App

Это не паритет со старым Telegram UI. Матрица фиксирует, какой сохранённый backend-инвариант должен получить новый web-путь.

| Возможность | Backend | Новый UI/API | Задача | Обязательное доказательство |
|---|---|---|---|---|
| Identity и права | сохранён | planned | CB-51, CB-52 | auth proof → member; свежие role/status/permissions/ownership |
| Регистрация и профиль | сохранён | planned | CB-52, CB-54 | replay-safe mutations и серверная валидация |
| Каталог и задания | сохранён | planned | CB-52, CB-54 | immutable snapshot, reserve/refund ledger, race tests |
| Назначения и результаты | сохранён | planned | CB-52, CB-54 | exactly-once accept/submit/review |
| Споры и модерация | сохранён | planned | CB-52, CB-55 | authorization matrix, ledger/audit rollback |
| Кредиты и опыт | сохранён | planned | CB-52, CB-54 | append-only ledger и reconciliation |
| Карма и надёжность | сохранён | planned | CB-52, CB-55 | eligibility, privacy и administrative audit |
| Уведомления | plain Telegram sender | deep link planned | CB-54, CB-56 | allowlist, retry, no callback UI |
| Deployment | transitional worker-only | planned | CB-56 | TLS, migrations, readiness, rollback, restore |
| Acceptance | core regression | planned | CB-57 | browser + PostgreSQL + live Mini App |

Строка закрывается только когда API и frontend используют сохранённый application use case, сервер проверяет права, mutation имеет operation identity, а PostgreSQL-тест подтверждает state/ledger/audit/outbox.
