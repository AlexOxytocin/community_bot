# CB-82 — план ручной проверки

Ручная проверка выполняется только после merge, green main CI, нового exact
immutable release и production activation. Секреты, session cookie, Telegram
proof, member UUID, комментарий и raw karma в evidence не записываются.

| № | Сценарий | Ожидаемый результат | Статус |
|---:|---|---|---|
| 1 | Открыть public Mini App по принятому launch path и получить fresh Web session | `/mini-app`, assets и authenticated API доступны; landing `/` не изменён | Не выполнялось |
| 2 | Открыть строку доступного участника в leaderboard | Показан только safe profile; private/raw fields отсутствуют | Не выполнялось |
| 3 | Для server-eligible пары пройти `begin → value → comment → confirm` | Confirm успешен; отдельный safe-profile GET перечитал карточку; aggregate изменён ровно один раз | Не выполнялось |
| 4 | Повторить тот же confirm после имитации потерянного ответа | Возвращён тот же safe outcome; второй vote revision/audit/signal не создан | Не выполнялось |
| 5 | Отправить stale revision и затем перечитать карточку | Generic conflict без утечки comment/target existence; authoritative profile GET остаётся доступен | Не выполнялось |
| 6 | Проверить keyboard/focus/status на узком viewport | Все controls имеют labels; focus предсказуем; status объявляется через `aria-live` | Не выполнялось |
| 7 | Проверить public responses и operator logs | Нет raw author/comment/history, private fields, cookie/proof или secret-like values | Не выполнялось |
| 8 | Сверить privacy-safe release evidence | Записаны exact merge/run/artifact/manifest/image/head и green smoke без персональных данных | Не выполнялось |

Live-проверка не читает Telegram chats и не отправляет сообщения. Если
eligibility test pair в production отсутствует, это реальный public-smoke
blocker: новую domain eligibility, seed или обход прав создавать нельзя.
