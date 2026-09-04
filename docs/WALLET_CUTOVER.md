# Релиз кошелька: 0031 → 0032

Используется `ops/wallet_cutover.py` из точного чистого checkout `origin/main`.
`deploy_dev.py` и `release_contract.py` не подходят для этого перехода.
Production host/package определяются по labels работающих контейнеров, не по
`active.json`. Скрипт применим только к неизменённому Compose package и head 0031.

## Подготовка

1. Локально выполнить Ruff, ty, unit-тесты и
   `tests/integration/test_wallet_cutover.py` на общей тестовой PostgreSQL.
   Этот тест реально выполняет dump/restore, upgrade/downgrade и атомарную
   замену имени БД с сохранением failed-копии; отдельный сервер не запускается.
2. Зафиксировать и отправить согласованный commit. На сервере получить чистый
   checkout полного SHA из `AlexOxytocin/community_bot`. Перед запуском проверить
   наличие и SHA-256 скрипта и `ops/_runtime.py`, затем syntax check.
3. Из этого checkout выполнить `python3 -B -m ops.wallet_cutover prepare
   --source <checkout> --target <full-sha>`.
   Это проверяет текущий healthy runtime, services, config/head, строит image,
   проверяет его revision/head и создаёт root-private receipt. Сервисы не
   останавливаются. До runtime mutation сверить напечатанные source/target,
   PostgreSQL, package, services и planned backup/restore identities.
4. Выполнить `python3 -B -m ops.wallet_cutover apply --receipt <printed-path>`.
   Между prepare/apply изменение source image, Compose или head запрещает apply.
   Все вызовы используют общий `dev-deploy.lock`; второй deploy исключён.

## Последовательность и граница отката

- Остановить web/worker; проверить отсутствие оставшихся DB clients.
- Создать свежий backup после остановки записи; сохранить digest.
- Восстановить его в уникальную БД, проверить head и экономические hashes/counts.
  На копии выполнить `0031→0032→0031`, повторить проверки. Копия остаётся
  готовой для немедленного возврата старой схемы.
- Мигрировать рабочую БД, проверить неизменность экономических данных.
- Запустить target web/worker с `RELEASE_MAINTENANCE=true`: API возвращает 503,
  worker пишет только heartbeat, не закрывает задания и не отправляет уведомления.
  Проверить новую revision, schema/config/heartbeat и неизменность ledger/балансов.
- До открытия записи любой сбой возвращает прежнюю версию. Если схема уже
  изменилась, одна транзакция переименовывает failed-БД и восстановленную копию:
  исходное состояние не удаляется и не перезаписывается. После этого проверяется
  прежний runtime. При сбое восстановления данные сохраняются и требуется recovery.
- Перед открытием записи durably записывается `writers_enabled`. С этого момента
  автоматическое восстановление старых данных запрещено: могли появиться новые
  переводы, начисления и уведомления. Сбой запуска повторяет тот же target image.
  Режим обслуживания снимается пересозданием сервисов из исходного Compose.
- `ready` означает exact инфраструктурную готовность. Telegram acceptance —
  отдельный запуск из `@humanquest_bot` с настоящим initData; `/readyz` его не заменяет.

## Возобновление после прерывания

`python3 -B -m ops.wallet_cutover recover --receipt <exact-path>`:

- `stopping`, `backup`, `migrating`, `rolling_back` — вернуть старую версию;
- `writers_enabled` — только продолжить запуск новой, без отката данных;
- `ready`/`rolled_back` — повторный apply/recover запрещён.

Если ошибка после открытия записи не устраняется повторным запуском target,
не восстанавливать старый backup автоматически. Сначала сохранить новые данные
и согласовать восстановление/перенос операций. Backup и retained recovery DB
после успешного релиза остаются на сервере; скрипт не удаляет их автоматически.
Не публиковать env, backup, сессии и содержимое ledger в Jira или Git.
