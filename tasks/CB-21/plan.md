# CB-21 — план синхронизации Telegram UX MVP

## Цель

Собрать поверх существующих сервисов единый navigation router, чтобы active member проходил
основные сценарии из главного меню без знания внутренних UUID, а active administrator получал
минимальное рабочее административное меню.

## Пользовательские потоки

1. `/start` для active member и `/help` показывают reply keyboard:
   `Найти задание`, `Создать задание`, `Мои задания`, `Моя карточка`, `Баланс`, `Статистика`,
   `Лидерборд`, `Участники`, `Помощь`; команды остаются эквивалентом кнопок.
2. `/tasks` читает не более 10 `published` заданий, доступных актуальному уровню, с живым
   дедлайном и свободным слотом. Собственные задания и уже занятые этим performer исключаются.
   При активной санкции на acceptance или достигнутом лимите активных назначений список пуст;
   это удобный read projection, а callback всё равно повторяет authoritative acceptance policy.
   Карточка содержит безопасные поля и inline `Взять` с существующим `task:accept:<UUID>`;
   callback повторно выполняет всю серверную acceptance policy. Порядок страницы —
   `(created_at DESC, id DESC)`; `Следующая страница` несёт только последний task UUID, по которому
   сервер восстанавливает cursor. Если cursor уже недоступен, показывается первая актуальная
   страница. Поэтому 11-е и последующие задания достижимы без ручного UUID.
3. `/create` вызывает `CatalogService.browse`; у каждой доступной версии есть callback
   `nav:create:<template_uuid_hex>`, который передаёт exact ID в существующий `TaskService.start`
   и открывает durable draft. UUID пользователю не показывается.
4. `/balance` берёт собственный profile balance и до 10 строк собственного immutable ledger;
   комментарии и чужие данные не показываются, типы операций переводятся в короткие подписи.
5. `/help` содержит актуальный короткий путь пользователя и список основных команд.
6. `/admin` и каждый `nav:admin:*` callback сначала проходят отдельный navigation gate по
   фактическим `role=administrator` и `status=active`. Только после него вызывается соответствующий
   прикладной сервис. Только active administrator видит callbacks:
   создать одноразовое приглашение на 7 дней, показать submitted registrations, показать moderation
   queue. Каждый callback заново авторизуется соответствующим прикладным сервисом; отказ одинаковый
   для non-admin и неизвестного actor.
7. Старые `/catalog`, `/task_create`, `/my_tasks`, `/invite_create`, `/registrations`, `/moderation`
   и остальные технические команды не меняются.

## Изменения

- application read query и PostgreSQL query для доступных заданий;
- `navigation.py` Telegram router с командами, reply/inline buttons и safe presenters;
- production Dispatcher composition и active registration main-menu markup;
- канонический `05_BOT_INTERFACE.md` и краткая инструкция пользователя/администратора;
- targeted unit/integration/E2E и финальный отчёт.

## Атомарность и безопасность

- Read-only меню не создаёт receipts и не держит транзакцию при Bot API;
- invite/create/accept используют существующие update gate, identity gate и receipts;
- callback UUID валидируется и никогда не заменяет application authorization;
- admin callbacks не раскрывают наличие queue или actor state при отказе;
- navigation router включается до task и registration text catch-all; он регистрирует только
  точные команды, точные тексты кнопок и собственные callback prefixes, поэтому не перехватывает
  FSM-ответы и не зависит от порядка остальных команд;
- Telegram Bot API вызывается только после завершения DB-вызова.

## Готовность

Все девять Jira AC доказаны одним production Dispatcher E2E и узкими тестами; Ruff, ty, build и
diff-check зелёные; independent final review одобрено. Full regression остаётся CB-16.
