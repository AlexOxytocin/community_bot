# CB-33 — план исправления production product config readiness

## Цель

Сделать чистый self-hosted запуск детерминированным: после migrations и первого
administrator bootstrap активировать packaged `product-config.v2.json` до запуска
worker/bot, а readiness считать зелёным только при полном config snapshot.

## Минимальное решение

1. Добавить CLI `community-bootstrap-product-config`, который:
   - при существующей active config возвращает success без изменений;
   - при её отсутствии требует ровно одного active administrator;
   - загружает packaged candidate, выводит стабильный activation command ID из
     content hash и применяет существующий `ProductConfigBootstrapCoordinator`;
   - не принимает и не выводит секреты.
2. Копировать `config/` в application image.
3. В `deploy_self_hosted.sh` после migrations при optional bootstrap Telegram ID
   сначала создать первого administrator, затем всегда выполнить config bootstrap,
   и только после этого запускать worker/bot.
4. Расширить `readiness_report`: active pointer должен ссылаться на version с десятью
   уровнями, а каждый active member — на эту же config version.
5. Обновить первый запуск в runbook.

Новых сервисов, таблиц, миграций и зависимостей не требуется.

## Критерии завершения

- clean database: admin bootstrap → config bootstrap → readiness green;
- повтор обеих bootstrap-команд не создаёт version/activation duplicates;
- missing/incomplete/stale config даёт readiness code `product_config_incomplete`;
- deploy order: migrate → optional admin → config → worker health → bot health;
- targeted tests, Ruff, `ty`, build и entrypoint checks зелёные.
