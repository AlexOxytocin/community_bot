# CB-33 — отчёт о реализации

## Итог

Production release больше не может запустить worker/bot с пустой или неполной
product config. Исправление переиспользует существующий coordinator и не добавляет
таблиц, миграций, сервисов или зависимостей. Уровень процесса: 2 — локальный
bootstrap/readiness fix в существующей архитектуре.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| Исполнимый CLI/runbook bootstrap | пройден | `community-bootstrap-product-config`; config packaged в image; runbook и deploy order обновлены. |
| Идемпотентный replay | пройден | Integration test: два запуска, 1 version, 1 activation, 1 backfill. |
| Readiness fail-closed | пройден | Missing config и stale active member возвращают `product_config_incomplete`; complete snapshot возвращает `ready`. |
| Config-dependent production smoke | пройдено в discovery | CB-29 подтвердил восстановление card/balance/members/find/create после coordinator activation; полный повтор будет один раз после всего Bug-пакета. |
| Секреты и миграции | пройден | Новых secret fields и migrations нет; CLI не принимает Telegram ID/config payload и логирует только safe outcome/version. |

## Проверки

- targeted: `27 passed`, без skip/deselect (`--no-cov`, потому что это узкий набор);
- Ruff format/check: пройдено;
- `ty`: пройдено;
- sdist/wheel: собраны;
- bot/worker/bootstrap entrypoints: пройдены;
- Docker build: пройден; `/app/config/product-config.v2.json` существует, CLI доступна;
- `git diff --check`: пройдено;
- полная регрессия намеренно не повторялась: единый повтор закреплён за CB-29 после
  слияния CB-30–CB-33.

## Известная граница

CLI автоматически создаёт только первую active config. Если active pointer уже
существует, команда возвращает success и не разворачивает новую версию; будущий
управляемый rollout остаётся за существующим явным config activation API.
