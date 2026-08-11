# CB-21 — контекст и источники плана

## Источник дефекта

- Jira CB-21: канонические `/tasks`, `/create`, `/balance`, `/help`, `/admin` и главное меню
  отсутствуют в production Dispatcher.
- Дефект найден после готовности к общей регрессии CB-16 и исправляется отдельной веткой.
- Технические команды и прикладные сервисы уже работают; проблема находится в пользовательской
  композиции и одной недостающей read model доступных заданий.

## Повторно используемые границы

- `CatalogService.browse` даёт доступные участнику immutable шаблоны.
- `TaskService.start` создаёт durable draft, `AssignmentService.accept` атомарно занимает слот.
- `RegistrationService.own_profile` и `EconomyQueryService.history` дают собственный баланс и
  ledger history.
- Registration и Moderation services уже авторизуют заявки и очередь.
- Все мутационные callbacks продолжают использовать exact Telegram update receipt.

## Ограничения

- Пользователь не копирует UUID; UUID допустим только внутри callback data.
- Старые технические команды сохраняются для операций и совместимости.
- Новый web UI, FSM, таблицы и миграции не нужны.
- Полная регрессия выполняется один раз в CB-16 после слияния CB-21.
