# CB-14 — контекст и источники плана

## Jira

- Задача: CB-14 «Утвердить модель пилота и эксплуатационные решения».
- Родитель: CB-2 «Реализовать и подготовить к пилоту Community Bot MVP».
- Статус на старте: `К выполнению`; после проверки связей переведена в
  `В работе`.
- Входящих блокирующих связей нет. CB-14 блокирует CB-15.
- После решения владельца от 2026-08-11 пять критериев требуют определить
  когорту, runtime `bot`/`worker`/PostgreSQL, error reporting и хранение логов,
  RPO/RTO/backup и синхронизацию документов/ADR. Application object storage и
  webhook исключены из CB-14.

## Каноническая документация

- `01_PRODUCT_REQUIREMENTS.md`: закрытый Telegram-пилот на 20–30 приглашённых
  взрослых участников, длительность 4–6 недель, продуктовые метрики и условия
  остановки.
- `TECH_STACK.md` и ADR-0005: Python-монолит, два постоянно работающих процесса,
  PostgreSQL 18, JSON-логи, health checks, long polling и запрет лишней
  инфраструктуры.
- `07_SECURITY_AND_PRIVACY.md`: минимизация данных, запрет секретов и приватных
  комментариев в логах, сохранение Telegram `file_id`, если локальная копия не
  нужна, и проверяемое восстановление.
- `09_IMPLEMENTATION_PLAN.md`: CB-15/этап 9 реализует outbox, наблюдаемость,
  backup/restore и эксплуатационные инструкции после принятия решений CB-14.
- `11_DECISIONS_AND_OPEN_QUESTIONS.md`: CB-14 закрывает Q-001, hosting,
  error reporting/log retention и PostgreSQL recovery. Остальные технические
  вопросы не входят в изменённую владельцем область.

## Актуальные внешние факты

- Render поддерживает постоянно работающие background workers, cron jobs,
  prebuilt Docker images по digest, pre-deploy command и управляемый PostgreSQL;
  платный PostgreSQL имеет PITR. Pre-deploy command выполняется новым artifact
  конкретного сервиса до его переключения, поэтому migration gate закрепляется
  только за `worker`, а не за one-off job старого base service.
- В Render срок доступности runtime-логов зависит от workspace plan: 7/14/30
  дней; для пилота явно выбирается Pro workspace с 14 днями.
- Telegram Bot API допускает только один из двух взаимоисключающих режимов:
  `getUpdates` либо webhook. Long polling уже принят для MVP.
- Sentry используется только как error reporting, не как хранилище доменных или
  пользовательских данных.

Официальные источники:

- [Render service types](https://render.com/docs/service-types)
- [Render PostgreSQL backups](https://render.com/docs/postgresql-backups)
- [Render logs](https://render.com/docs/logging)
- [Render health checks](https://render.com/docs/health-checks)
- [Render cron jobs](https://render.com/docs/cronjobs)
- [Render prebuilt images](https://render.com/docs/deploying-an-image)
- [Telegram Bot API](https://core.telegram.org/bots/api)

## Факты о репозитории

- `bot` и `worker` уже имеют отдельные entry points и используют общую БД.
- Доменные изменения уже создают PostgreSQL outbox-события; CB-15 должна
  реализовать их доставку, retries, heartbeat и эксплуатационные проверки.
- Для доказательств выполнения достаточно Telegram `file_id`, валидируемых
  HTTPS-ссылок и текстовых данных. Собственного blob API в MVP нет.
- В репозитории нет deployment manifest, Sentry integration и runbook
  восстановления; это ожидаемая область CB-15 после принятия ADR-0008.
- Текущие миграции уже выполняются Alembic; CB-15 должна добавить release
  orchestration и compatibility smoke, а не второй механизм схемы.

## Ограничения

- Никакие production credentials, DSN, backup-файлы и приватные данные не
  фиксируются в Git или Jira.
- CB-14 принимает решения и обновляет документацию, но не разворачивает
  production и не реализует worker/observability.
- Полная регрессия продукта остаётся CB-16.

## Решение владельца

11 августа 2026 года владелец принял профиль Render/Sentry/release и исключил
Cloudflare R2, application object storage и webhook из области CB-14. ADR-0008
обновляется ровно в этих границах.
