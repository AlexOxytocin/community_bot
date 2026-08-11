# CB-13 — эскалация двух непройденных plan review

Режим: `review_cycle`, фаза `plan`.

## Проблема

После принятия продуктовых политик и первого консолидированного исправления
остались три сквозных разрыва: post-payment fraud не имел достижимого case-open
пути, expiry санкции был определён только для mutations, а source context всё
ещё называл принятое решение открытым.

## Воспроизведение

- `reviews/plan/attempt-01.md` — `Status: blocked`;
- `reviews/plan/attempt-02.md` — `Status: changes_requested`;
- paid `approved|partially_approved` assignment не мог попасть в fraud
  resolution через публичный application/Telegram command;
- истёкший `suspended` продолжал выглядеть suspended для status-dependent read
  без worker CB-15.

## Три попытки решения

| Итерация | Действие | Результат | Вывод |
|---|---|---|---|
| 1 | Исходный полный план | `blocked` | Нужны решение владельца и единая state machine |
| 2 | D-023 и консолидированная matrix/expiry/concurrency правка | `changes_requested` | Остались три достижимых boundary |
| 3 | Финальное исправление ниже | ожидает контроль | После него допустим один полный review |

## Вероятная причина

Первый план смотрел на dispute, sanction и signals как на административный UI,
но не довёл два редких перехода до общей application boundary: расследование
после выплаты и чтение статуса после истечения санкции.

## Варианты решения

- Добавлять debt model и отдельный moderation service — чрезмерно для MVP.
- Требовать scheduler для каждого expiry — создаёт скрытый блокер CB-15.
- Использовать один admin fraud-case command и один effective-status resolver —
  минимальный вариант внутри текущего модульного монолита.

## Рекомендация

Одним исправлением добавить `OpenFraudCaseCommand`, общий case gate/replay,
атомарный отказ при недостаточном reversible balance; распространить единый
effective-status resolver на все status-dependent reads/mutations; синхронизировать
source context и два существующих тестовых сценария.

## Требуемое решение

Решение владельца D-023 уже получено. После этого исправления выполняется одна
эскалационная контрольная проверка полного плана. Если она не `approved`, работа
останавливается для решения владельца.
