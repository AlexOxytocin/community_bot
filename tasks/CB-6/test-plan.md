# CB-6 — план ручного и интеграционного тестирования

`community_bot.test_plan.v1`

## Предусловия

- ветка `task/CB-6` создана от актуального `origin/main`;
- WSL 2, Docker Desktop и Docker Engine работают;
- `docker compose up -d --wait` поднял healthy PostgreSQL 18 для основного прогона; отдельный контрольный прогон без `DATABASE_URL` использует Testcontainers;
- зависимости установлены `uv sync --locked --all-groups`;
- для Compose-backed прогона `DATABASE_URL` указывает на локальную тестовую БД; при отсутствии переменной integration fixture автоматически создаёт `postgres:18` и не пропускает тесты;
- миграция `0002` применена;
- Telegram token отсутствует, внешняя сеть Telegram не используется.

## Тестовые данные

- новый Telegram user ID, отсутствующий в `members`;
- участники с ролями `member`, `moderator`, `administrator`, включая двух активных администраторов для конкурентного сценария;
- участники каждого статуса: `pending`, `active`, `paused`, `restricted`, `suspended`, `left`, `banned`;
- два разных Telegram update ID и один повторяемый update ID;
- обезличенные UUID сущностей и причины административных изменений;
- fake aiogram Bot session, который только записывает вызовы API.

## Сценарии

| № | Сценарий | Шаги | Ожидаемый результат | Фактический результат |
|---|---|---|---|---|
| 1 | Новый пользователь | Передать synthetic `/start` с отсутствующим `telegram_user_id` | Получен маршрут `registration_required`; member не создан; один безопасный ответ через fake session | Пройдено автоматически |
| 2 | Ожидающий пользователь | Создать `pending` member, повторить `/start` | Получен `registration_pending`; главное меню недоступно | Пройдено автоматически |
| 3 | Активный пользователь | Создать `active` member, повторить `/start`, затем нажать `Обновить меню` | Текст `Главное меню`; единственная кнопка `Обновить меню` работает и не ведёт к несуществующей функции | Пройдено автоматически |
| 4 | Неактивные статусы | Повторить `/start` для `paused/restricted/suspended/left/banned` | Для каждого получен `account_unavailable`; доменные данные не меняются | Пройдено автоматически |
| 5 | Update без actor | Передать synthetic update без пригодного `from_user` | Нет ответа, транзакции, receipt и доменного изменения | Пройдено автоматически |
| 6 | Повтор и гонка update с постоянным эффектом | Одновременно выполнить двумя сессиями изменение `active → paused` с одним `update_id`, затем повторить после commit | Advisory gate сериализует вызовы; ровно одно изменение member, один audit, один complete receipt/outcome; повторы не меняют БД | Пройдено автоматически |
| 7 | Retry после fault rollback | Вставить fault после изменения target, но до append audit; затем повторить тот же update без fault | Первая транзакция не оставила member change, receipt или audit; повтор атомарно создал все три | Пройдено автоматически |
| 8 | Полная матрица доступа и переходов | Application-командой проверить active/inactive actor, member/moderator/administrator, self-target, admin-target, чужое владение и все current→requested role/status пары | Разрешены только `active↔paused` и `member↔moderator` для допустимого non-admin target; решение принято по заблокированным актуальным строкам | Пройдено автоматически |
| 9 | Аудит административного действия | Активным администратором изменить статус неадминистративного target с причиной | Member и один audit event зафиксированы атомарно; before/after/actor/reason корректны | Пройдено автоматически |
| 10 | Конкурентные admin changes | Двумя update ID и администраторами одновременно выполнить допустимые `active → paused` и последующее role change одного target | Операции сериализованы; нет lost update; цепочка audit `before → after` согласована с финальным member | Пройдено автоматически |
| 11 | Неизменяемость audit | После создания event выполнить прямые `UPDATE` и `DELETE` | PostgreSQL trigger отклоняет обе операции; event не изменён | Пройдено автоматически |
| 12 | Восстановление после restart | Зафиксировать member, audit и receipt; dispose engine; создать новый объект БД и перечитать | Все записи доступны; повтор update возвращает сохранённый outcome без нового действия | Пройдено автоматически |
| 13 | Граница Bot API | Обработать новый и duplicate update через fake session, наблюдая состояние транзакции | Fake Bot API вызывается только после commit; повтор может повторить безопасный ответ, но не DB-эффект | Пройдено автоматически |
| 14 | Миграционный цикл | На тестовой БД выполнить `upgrade head`, `downgrade 0001`, `upgrade head` | Все команды успешны; tables, trigger, constraints и indexes восстановлены | Пройдено автоматически |
| 15 | Неполный receipt | Прямым SQL попытаться вставить receipt без `outcome_code` или `processed_at` | `NOT NULL` отклоняет insert; committed полуготовой записи нет | Пройдено автоматически |

## Автоматизированные специальные проверки

- Полная параметризованная матрица role/status/current→requested/ownership/self/admin-target.
- Property-based проверка детерминированности маршрута для одного состояния.
- Две независимые async SQLAlchemy sessions для конкурентного receipt-протокола и двух admin changes одного target.
- Boundary-проверка advisory lock и exact receipt для `update_id` за пределами signed `int32`, включая максимальный signed `BIGINT`.
- Повтор административного `update_id` с подменёнными actor/target подтверждает возврат сохранённого outcome без чтения нового payload.
- Persisted read/ownership matrix проверяет self-only для member/moderator, deny для inactive и read-any для active administrator, включая administrator target.
- Проверка DB constraints на неизвестные role/status и дубли `telegram_user_id/update_id`.
- Проверка UTC-aware timestamps после чтения из PostgreSQL.
- Fault injection между target flush и audit append.
- Проверка PostgreSQL trigger против изменения/удаления audit row.
- Каждый integration test создаёт отдельную временную PostgreSQL database, применяет миграции и после закрытия connections удаляет database через `DROP DATABASE ... WITH (FORCE)` из maintenance connection. Audit rows не очищаются `DELETE`; project Compose volume не удаляется.
- Проверка двух режимов integration server: Compose через `DATABASE_URL` и автоматический Testcontainers fallback; оба содержат 0 skipped.
- Проверка отсутствия реальных сетевых Telegram-запросов и вызова fake session только после commit.

## Очистка тестовых данных

- Integration fixtures не выполняют row-level cleanup. Каждый тест работает в отдельной временной database; teardown закрывает engine и удаляет всю database через maintenance connection, поэтому immutable audit trigger не обходится и не мешает очистке.
- После ручного прогона миграция остаётся на `head`.
- PostgreSQL Compose остаётся поднятым как локальная тестовая среда; удаление volume не выполняется автоматически.

## Ограничения

- Реальная регистрация по приглашению и заполнение профиля не проверяются в CB-6.
- Реальные сообщения Telegram не отправляются.
- Детальные разрешения статуса `restricted` не моделируются; проверяется безопасный отказ.
- Production backup, hosting и error reporting находятся вне области задачи.
