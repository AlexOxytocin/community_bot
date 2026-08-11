# ADR-0009 — Самостоятельное размещение пилота

**Статус:** Принято

**Дата:** 2026-08-11

**Принято владельцем:** 2026-08-11. Владелец выбрал собственный сервер и поручил
развернуть на нём весь runtime. External backup, application object storage и
webhook остаются за границей MVP.

## Контекст

ADR-0008 выбрал Render, но до provisioning владелец предоставил собственный
сервер с Ubuntu 24.04 и Docker. Jira CB-15 требует реальное восстановление
backup и документированную эксплуатацию, поэтому смена hosting должна сохранить
измеримые release, health и recovery gates без облачной инфраструктуры «на
всякий случай».

## Решение

1. Пилот запускается на одном сервере под Ubuntu 24.04 через Docker Compose.
   `bot`, `worker`, одноразовый `migrate` и PostgreSQL 18 образуют отдельный
   Compose project и внутреннюю сеть. PostgreSQL не публикует порт наружу;
   long polling не требует HTTP ingress.
2. `bot`, `worker` и `migrate` используют один проверенный `linux/arm64` image под
   архитектуру пилотного сервера. Штатный release после зелёного CI
   идентифицируется GHCR SHA-256 digest. Deployment сначала
   запускает PostgreSQL и migration gate, затем `worker` и его readiness, после
   этого `bot` и его readiness. Предыдущая image identity сохраняется для
   rollback; schema downgrade автоматически не выполняется.
3. Секреты находятся только в root-owned `/opt/community-bot/shared/.env` с
   правами `0600`. Репозиторий, Jira, логи и release metadata не содержат их.
   Существующие приложения сервера, reverse proxy и firewall не изменяются;
   Community Bot не открывает новых публичных портов.
4. Docker хранит ограниченные по размеру структурированные JSON-логи каждого
   контейнера. Sentry остаётся необязательным и получает только очищенные error
   events по правилам ADR-0008.
5. PostgreSQL использует отдельный persistent volume. Ежедневный локальный
   logical backup в custom format хранится семь суток в root-only каталоге
   `/var/backups/community-bot`. До запуска и затем не реже раза в четыре недели
   выполняется restore drill в отдельную временную БД с проверкой revision и
   базовых таблиц. Цели для логического сбоя: `RPO <= 24h`, `RTO <= 4h`.
6. Локальный backup не защищает от полной потери сервера или его диска. Этот риск
   явно принимается для MVP: внешний backup, R2 и иное object storage не входят
   в решение. Если появится требование переживать потерю хоста, оно оформляется
   отдельной задачей и решением владельца.

## Рассмотренные альтернативы

- Render и managed PostgreSQL заменены прямым решением владельца использовать
  собственный сервер.
- Kubernetes, Redis, Celery и отдельный reverse proxy для бота не нужны: long
  polling и PostgreSQL outbox работают без входящего HTTP-трафика.
- Копирование backup во внешний storage не выбрано владельцем для MVP.

## Последствия

- AC7 CB-15 проверяется реальным `pg_dump` → isolated restore drill на сервере,
  а не облачным PITR.
- Владелец отвечает за доступность одного хоста; ежедневный backup закрывает
  логическую порчу БД, но не потерю хоста.
- Hosting-специфика остаётся в Compose, shell scripts и runbook; application и
  domain не зависят от сервера.
- Положения ADR-0008 о когорте пилота, Sentry privacy и исключении application
  object storage/webhook сохраняются; hosting/release/backup положения заменены
  этим ADR.

## Связанные материалы

- [ADR-0008](0008-pilot-runtime-and-operations.md)
- [Технологический стек](../mvp/TECH_STACK.md)
- [Решения и открытые вопросы](../mvp/11_DECISIONS_AND_OPEN_QUESTIONS.md)
- [Runbook пилота](../operations/PILOT_RUNBOOK.md)
