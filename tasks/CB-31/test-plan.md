# План проверок CB-31

1. Первый bootstrap по-прежнему создаёт один active administrator с безопасным
   нейтральным профилем и одним provenance audit event.
2. Repair принимает русское Unicode-имя, сохраняет его без искажения и не
   меняет роль, статус, permissions, ledger/cache и остальные поля профиля.
3. Повтор repair с тем же значением возвращает no-op и не создаёт второй audit.
4. Другой Telegram ID, отсутствие provenance, несколько active administrators
   и невалидное имя завершаются без изменений.
5. Fault между обновлением member и audit полностью откатывает repair; retry
   успешно завершает операцию.
6. Production-composed Dispatcher после repair и product-config bootstrap
   показывает точное имя в карточке, каталоге участников и leaderboard.
7. Process argv, логи и audit не содержат Telegram ID или display name.
8. Targeted PostgreSQL, Ruff, ty, build и оба bootstrap entrypoint проходят;
   full regression остаётся за CB-29.
