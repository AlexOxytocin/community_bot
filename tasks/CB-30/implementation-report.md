# CB-30 — отчёт о реализации непрерывных Telegram-цепочек

## Результат

Внутренние UUID, revision, JSON и ручные callback-команды убраны из основных
пользовательских цепочек. Задание, результат, проверка, спор, модерация, апелляция,
карма, санкции, алерты и community-задача теперь продолжаются кнопкой либо обычным
текстом из предыдущего ответа бота.

## Что изменено

- `conversation_states` стал единственным долговечным владельцем следующего
  свободного текста для task/result/dispute/karma; регистрация и редактирование
  профиля не вытесняются молча.
- Member- и community-задачи заполняются обычным текстом и ограниченными кнопками.
  Community-задача хранит creator/reviewer provenance, не создаёт личный резерв и
  допускает видимую безопасную замену недоступного reviewer.
- `Мои задания` показывает исполнительские и проверяющие карточки, восстановимые
  после restart. Через них доступны submit, full/partial/reject, dispute и appeal.
- Production `community-worker` перед notification tick выбирает ограниченную пачку
  заданий с наступившим deadline и фактическим `accepted` assignment, затем через
  канонический `AssignmentService` переводит принятые выполнения в no-show. Старые
  `settling`-задания без доступного для финализации assignment не занимают пачку;
  повторный проход безопасен по task gate/status.
- `Участники` отдаёт полноценные карточки, а не список имён: профиль, карма и
  разрешённые администратору действия берутся из самой карточки.
- Административная модерация выдаёт карточки споров, fraud-проверок, санкций и
  interaction-alerts. Active moderator через тот же видимый пункт получает только
  допустимую очередь споров; administrator — полный административный раздел.
- Добавлена миграция `0012_output_driven_telegram_flows`: provenance community-задач,
  ограничения ссылок и контролируемое исключение неизменяемого task snapshot только
  для замены reviewer.
- Каноническая модель данных и пользовательская справка синхронизированы с новым UI.

## Критерии Jira

1. Output-driven UI: покрыт шестью длинными production Dispatcher + PostgreSQL +
   fake Bot API сценариями в `test_output_driven_flows.py` и существующими
   targeted-сценариями navigation/assignments/reputation/moderation.
2. Права: performer/creator/reviewer/moderator/administrator повторно проверяются
   application/storage слоем; перехваченные и устаревшие callback не дают эффекта.
3. E2E не собирает callback вручную: каждый следующий callback берётся из
   захваченного ответа Bot API; карточка участника выбирается по показанному имени,
   а не по UUID из БД.
4. Экономика: full/partial/reject/no-show, community reward, fraud/appeal reversal и
   bounded penalty сохраняют ledger-инварианты; community-задача не имеет member reserve.
5. Идемпотентность: существующие update/entity gates, receipts, audit и outbox не
   дублируются; fault/concurrency/replay тесты затронутых сервисов сохранены.

## Матрица 26 сценариев test plan

- 1–5: `test_member_journey_uses_only_visible_outputs` плюс
  `test_full_exchange_is_atomic_and_exactly_once`, replay/foreign-callback oracles.
- 6–9: partial/reject в assignment suite; member/community reject → private dispute →
  moderator decision в `test_reject_dispute_and_moderator_resolution_use_visible_outputs`;
  appeal и независимое повторное решение — в community journey и moderation suite.
- 10–14: sanction/revoke, interaction alert, fraud, raw-karma exclude и обычная karma
  vote проходят `test_karma_sanction_and_alert_use_only_visible_outputs` и community
  journey; отрицательные role/revision cases остаются в reputation/moderation suite.
- 15–19: member creation, community creation, independent reviewer, forced replacement,
  community reward, reject/dispute и отсутствие member reserve покрыты тремя длинными
  output-driven journeys и assignment settlement tests.
- 20–23: deadline/no-show проходит реальный accept → deadline worker → повторное открытие
  карточки в `test_no_show_is_visible_after_deadline_worker`; отдельный PostgreSQL oracle
  с `batch_size=1` доказывает, что более старое `settling`-задание без `accepted`
  assignment не блокирует следующее действующее задание; `/cancel`, collision одного
  conversation owner, stale/replay/concurrency проверяются assignment/task/reputation suites.
- 24: callback до 64 байт и отсутствие технических значений проверяются длинными E2E,
  navigation и presentation tests.
- 25: `test_community_provenance_survives_exact_migration_cycle` проходит точный цикл
  `0011 → 0012 → 0011 → 0012`, сохраняет community creator/reviewer, assignment и все
  ledger transaction UUID; технический перенос через `safety_snapshot_json` удаляется
  при re-upgrade. Отдельный snapshot guard продолжает запрещать произвольный update/delete.
- 26: targeted PostgreSQL suite, Ruff, ty, build и entrypoint smoke выполнены ниже.

## Проверки

- unit + smoke после финального delta: `235 passed`;
- затронутый PostgreSQL/Dispatcher набор: navigation, task creation, assignments,
  reputation, moderation и output-driven flows — `62 passed`, без skip/deselect;
- worker/output-driven/notification consolidated gate: `28 passed`, включая visible
  partial/no-show, exact migration и production worker composition;
- точечный контроль deadline source и пользовательского no-show: `2 passed`, включая
  продвижение bounded-очереди после недействующего старого `settling`-задания;
- pilot migration/head smoke: `2 passed`;
- `uv run ruff format src tests migrations` — без изменений;
- `uv run ruff check .` — успешно;
- `uv run ty check` — успешно;
- `uv build` — sdist и wheel собраны;
- `uv run community-bot --check`, `uv run community-worker --check` — успешно;
- `uv run community-bootstrap-admin --help` — CLI установлен и разбирает аргументы;
- `git diff --cached --check` — успешно на финальном staged snapshot;
- staged secret scan — Telegram token/private key/assigned secret: `0/0/0`.

Полная регрессия всех модулей и реальный Telegram connector намеренно не дублируются
в этой ветке: по утверждённому CB-29 они запускаются один раз после слияния всех
regression Bugs.
