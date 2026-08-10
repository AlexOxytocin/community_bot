# CB-8 — целевой план проверки

## Среда

- PostgreSQL 18 из существующего Compose/Testcontainers контура;
- синтетические aiogram updates и fake Bot API session;
- отдельная временная database на integration test.

## Сценарии

| № | Сценарий | Обязательный результат |
|---:|---|---|
| 1 | Admin создаёт invite; member/moderator/inactive admin пробуют то же | Только active admin получает токен; в БД/аудите только hash |
| 2 | Отзыв, истечение, intended user и лимит | Невалидные коды не создают member/redemption/state |
| 3 | Два пользователя одновременно используют последнее место | Успешен ровно один; `uses_count` не превышает лимит |
| 4 | Один пользователь одновременно отправляет два разных `/start` и повторяет тот же update | Identity gate создаёт один member/redemption; exact receipt возвращает сохранённый шаг/outcome |
| 5 | Прохождение всех полей с ошибками на границах | Невалидный ввод не двигает шаг; валидный сохраняется |
| 5a | Два разных update отвечают на один `expected_step`, второй запаздывает | Первый двигает FSM один раз; второй получает `stale_step`, payload следующего шага не загрязнён |
| 6 | Dispose/new Database в середине регистрации | Шаг и payload восстановлены полностью |
| 6a | `/cancel`, запоздавший текст/callback и следующий `/start` | Диалог приостановлен без потери черновика; данные не меняются до явного возобновления |
| 7 | Изменение Telegram username | Обновляется тот же member UUID, дубль не появляется |
| 8 | Отправка заявки и права pending | Заявка `submitted`; active-права и профильное меню недоступны |
| 9 | Unauthorized/fake moderation callback | Нет status/grant/audit/receipt эффекта |
| 10 | Одобрение moderator и administrator через `prepare_batch` | Locked authorization происходит до ledger effect; затем `active`, `approved_at`, один audit и `starting_grant +5/+0` |
| 11 | Два конкурентных одобрения и retry после restart | Один grant, один переход заявки, сохранённый approved outcome |
| 12 | Fault после ledger/member flush до commit | Все эффекты откатились; retry применяет полный результат один раз |
| 13 | Reject → исправление → повторная отправка → approve | До approve нет grant; после approve один grant |
| 14 | `/profile` и редактирование каждого поля владельцем | Карточка отражает committed значения, баланс/уровень читаются из services |
| 15 | Попытка чужого/неактивного редактирования | Серверный отказ без изменения данных |
| 16 | Полный synthetic Telegram smoke | invite → onboarding → moderation → profile проходит без сети |
| 17 | Migration cycle | `0003→0004→0003→0004` проходит на пустой тестовой БД |
| 18 | Контроль качества изменённого контура | targeted pytest, Ruff, ty и diff-check дают exit 0 |

## Соответствие критериям Jira

- приглашения: 1–3;
- повторный `/start`, `/cancel`, restart и один member: 4–7;
- pending без active-прав: 8–9;
- единственный грант `+5/+0`: 10–13;
- username identity: 7;
- собственный профиль: 14–15;
- полный приёмочный сценарий: 16.

## Ограничение проверки

Полный `uv run pytest` всего продукта не является барьером CB-8 и выполняется в
CB-16. Если изменение заденет общий контракт, запускаются только напрямую
связанные существующие тесты member foundation/economy.
