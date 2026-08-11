# CB-14 — архитектурное решение эксплуатации пилота

## Проблема

CB-15 нельзя реализовать воспроизводимо, пока hosting, error reporting,
retention и PostgreSQL recovery остаются TBD.

## Граница

Выбирается минимальная эксплуатационная форма уже принятого модульного монолита.
Доменная модель, Telegram FSM, экономика и права не меняются.

## Решение

Render Pro запускает два процесса из одного GHCR image digest рядом с managed
PostgreSQL 18; Sentry получает только scrubbed exceptions. Единственный
migration gate — pre-deploy command image-backed `worker`; `bot` переключается
вторым. Expand-only schema остаётся совместима с предыдущим digest, поэтому
частичный deploy откатывает процесс, но не схему.
Long polling, PostgreSQL outbox и Telegram `file_id` остаются достаточными для
пилота. Backup-профиль измеряется RPO 24 часа/RTO 4 часа и доказывается
периодическим PITR-восстановлением в изолированную БД, а не наличием кнопки в
dashboard.

## Отклонённые варианты

- Самостоятельный VPS/PostgreSQL: дешевле на бумаге, но переносит backup,
  restart и monitoring на владельца до появления эксплуатационной команды.
- Kubernetes/Redis/Celery: не решают подтверждённую проблему когорты 20–30.
Application object storage и webhook исключены владельцем из решения CB-14 и
не считаются принятыми либо отклонёнными альтернативами ADR-0008.

## Проверка

Plan/final review проверяют непротиворечивость и полноту решения. CB-15 обязана
реализовать targeted PostgreSQL/outbox/observability tests, restore drill и
deployment smoke; CB-16 выполняет общую регрессию готового MVP.
