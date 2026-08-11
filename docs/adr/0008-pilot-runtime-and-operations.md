# ADR-0008 — Runtime и эксплуатационный профиль пилота

**Статус:** Принято

**Дата:** 2026-08-11

**Принято владельцем:** 2026-08-11. External daily backup, application object
storage и webhook явно исключены из области решения.

## Контекст

MVP уже имеет два процесса, PostgreSQL outbox и long polling, но не определяет
конкретное размещение, error reporting, сроки хранения, recovery objectives и
границу файлового хранения. Без этого CB-15 либо останется абстрактной, либо
молча выберет инфраструктуру в коде.

## Решение

1. Пилот запускается для закрытого межпрофессионального сообщества практической
   взаимопомощи: 20–30 приглашённых взрослых участников, ручное одобрение,
   4–6 недель.
2. Выбирается Render Pro workspace. `bot` и `worker` работают как два
   image-backed background workers, а PostgreSQL 18 — как платный managed
   database в том же project/region. GitHub Actions публикует reviewed
   `linux/amd64` image в GHCR; оба процесса запускаются только по одному SHA-256
   digest. Новый digest сначала назначается image-backed `worker`, чей
   единственный pre-deploy command под PostgreSQL advisory lock выполняет
   `alembic upgrade head`; `bot` не запускает миграции. Mutable tags и
   независимые rebuild запрещены.
3. Release-миграции только expand/backward-compatible с предыдущим digest. CI
   проверяет old/new smoke после upgrade. Порядок switch: `worker`, затем `bot`.
   При failure старый процесс продолжает работу; после частичного switch worker
   откатывается на предыдущий digest без schema downgrade. Предыдущий GHCR
   digest хранится минимум 30 дней и до успешного следующего release.
4. Render Pro хранит структурированные runtime-логи 14 дней. Sentry хранит scrubbed
   error events максимум 30 дней. Пользовательский контент, Telegram payload,
   credentials, invite-коды, evidence и приватные комментарии не отправляются.
5. Цели: RPO не более 24 часов и RTO не более 4 часов. Единственный принятый
   backup-механизм — непрерывный PITR платного Render PostgreSQL Pro с recovery
   window семь дней. До пилота и каждые четыре недели выполняется restore drill
   в новую изолированную БД. External daily backup не входит в решение.
6. CB-15 реализует heartbeat/readiness, scrubber, outbox delivery/retry,
   GHCR release pipeline, deployment manifest и PITR restore runbook.
   Создание облачных ресурсов и секретов выполняется отдельно от Git.

Application object storage и webhook не выбираются и не отклоняются этим ADR.

## Рассмотренные альтернативы

- VPS с самостоятельным PostgreSQL отклонён из-за лишней эксплуатационной
  нагрузки и риска непроверенного backup.
- Kubernetes, Redis, Celery и микросервисы отклонены как несоразмерные пилоту.
- Только provider dashboard без Sentry отклонён: ошибки Python нужны как
  дедуплицированные события с release/correlation context.

## Последствия

- CB-15 получает точную платформу и измеримые acceptance gates.
- Пилот требует Render Pro, платного PostgreSQL и контроля PITR/recovery до
  provisioning. Потеря данных старше семидневного recovery window принимается
  как ограничение этого пилотного решения.
- Vendor-specific deployment остаётся инфраструктурным адаптером; домен и
  application не импортируют Render/Sentry API.
- При изменении тарифа, провайдера или transport создаётся отдельная задача и,
  если меняется структурная форма, новый ADR.

## Связанные материалы

- [Технологический стек](../mvp/TECH_STACK.md)
- [Безопасность и приватность](../mvp/07_SECURITY_AND_PRIVACY.md)
- [Решения и открытые вопросы](../mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md)
- [Render service types](https://render.com/docs/service-types)
- [Render PostgreSQL backups](https://render.com/docs/postgresql-backups)
- [Render logs](https://render.com/docs/logging)
- [Render prebuilt images](https://render.com/docs/deploying-an-image)
