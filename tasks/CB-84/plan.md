# CB-84 — план реализации

## Уровень и цель

Уровень 2: небольшая продуктовая правка существующего Mini App mutation path без
изменения схемы, экономики или доменных правил. Цель — дать исполнителю на
текущей карточке `accepted` assignment возможность отказаться с причиной через
существующий `AssignmentService.cancel`.

## Изменения

1. В `src/community_bot/application/assignments.py` добавить к существующему
   `cancel` минимальную actor-native ветку: свежий active actor по `member_id`,
   ownership/status остаются у сервиса, Web receipt хранит actor, assignment и
   fingerprint нормализованной причины для exact replay/conflict.
2. В `src/community_bot/transport/web.py` добавить закрытый POST resource
   `/api/v1/assignments/{assignment_id}/cancellation`: session actor, exact UUID,
   same-origin, обязательный idempotency key, bounded JSON и allowlisted error.
3. В `src/community_bot/transport/static/app.js` добавить одну форму на уже
   существующую карточку `accepted` assignment. После успеха вызвать текущий
   `loadAssignments(false)`; retryable failure сохраняет operation key.
4. Обновить one-line route allowlist в `tests/unit/test_web_auth.py`, один
   API/domain oracle в `tests/integration/test_web_api.py` и один browser happy
   path в `tests/browser/test_mini_app.py`.

## Контракт и проверки

- Request: `{ "reason": <trimmed non-empty bounded string> }`; identities и
  status из клиента не принимаются.
- Success: `204`, assignment становится `cancelled`, повтор той же команды не
  создаёт второй effect; несовпадающий payload/actor/assignment закрывается.
- Denial: invalid input `422`; чужой, stale или недоступный assignment `409`;
  invalid/expired session и origin обрабатываются существующей общей границей.
- Targeted: Ruff/ty изменённых модулей, route unit, один integration oracle,
  один Playwright happy path, затем один релевантный combined gate и secret diff scan.

## Ceiling и вне области

Production: только три существующих файла, без dependencies, migration, model,
repository, service, generic UI abstraction или второго экрана; ориентир всей
правки — не более 250 net additions. Не входят creator/group cancellation,
templates/community publication, CB-76—CB-80, appeals, sanctions, alerts,
pagination и косметика.

## Риски

- Replay не должен принять ту же operation identity с другой причиной: в receipt
  сравнивается fingerprint нормализованного payload.
- Отмена может закрыть уже закрытое групповое задание и вернуть остаток: это
  существующее поведение `AssignmentService.cancel`, Web его не копирует.
- Если actor-native reuse потребует нового правила или persistence owner,
  реализация останавливается до runtime diff.
