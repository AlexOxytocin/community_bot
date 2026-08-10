# CB-4 — план проверки продуктовых решений

## Предусловие

Проверки выполняются после явного подтверждения владельца и синхронизации
документов. Это документационная задача: новое доменное поведение, Python-код и
миграции не реализуются, Telegram Bot API не вызывается. Для защиты от регрессий
дополнительно выполняются существующие Ruff, ty, миграционный цикл, полный
Compose-backed pytest без пропусков, сборка и безопасные проверки точек входа.

## Сценарии

| № | Проверка | Ожидаемый результат |
|---:|---|---|
| 1 | Найти заголовки `Q-002`, `Q-003`, `Q-004`, `Q-007`, `Q-008`, `Q-009`, `Q-010`, `Q-012` в разделе открытых вопросов | Ни одного; вместо них есть датированные принятые решения с причиной и отклонёнными вариантами |
| 2 | Проверить source of truth, ingest/activation retry и rollback | Same candidate version+hash создаёт одну immutable version; conflicting version/hash и duplicate payload/new version отклоняются. Same activation command+target после timeout даёт один pointer/audit/backfill; same command+other target rejected. New command v2→v1 выполняет rollback, повтор rollback no-op; already-active target не запускает backfill. Invalid activation/startup сохраняет active version; первый bootstrap без valid candidate запрещён |
| 3 | Проверить границы, cache versions и backfill | Для каждого порога `10/25/50/100/180/300/450/650/1000` значения `threshold-1`/`threshold` дают предыдущий/новый уровень; опыт выше 1 000 остаётся level 10. Stale cache каждой старой version не влияет на profile, `minimum_level`, acceptance, leaderboard или notification; повторный/прерванный backfill идемпотентен и не меняет ledger; concurrent activation/read не видит смешанные пороги |
| 4 | Проверить стартовый грант | Ровно 5 кредитов после первого одобрения; 0 опыта; два конкурентных approval/update с разными transport update и одним участником создают одну `starting_grant`; повтор после restart возвращает сохранённый результат без второго гранта |
| 5 | Проверить варианты истечения и гонку | Для многоместного task независимо разрешаются unfilled/no-submission/submitted slots; агрегат остаётся `settling`, затем становится `expired`, `partially_completed` или `completed`. Concurrent first submission/expiration сериализуются: member-task получает один refund либо сохраняет reserve для review; community-task получает отсутствие issuance либо сохраняет право review, без одновременного `no_show` с принятым result |
| 6 | Проверить позднюю коррекцию `no_show` | Модераторское подтверждение вины автора/системы добавляет корректирующее событие и меняет reliability denominator, не удаляя assignment/audit и не создавая скрытую выплату |
| 7 | Проверить review и отдельную reject/dispute ветку | В обычном review за 1 микросекунду до deadline manual/dispute допустимы, на границе — autoconfirm. Reject до границы отменяет autoconfirm и создаёт собственные 24h: dispute допустим до reject deadline даже за original deadline, на reject boundary finalizer делает один refund/no-issuance. Другие review actions после reject запрещены; concurrent dispute/finalizer и dispute/autoconfirm дают один outcome |
| 8 | Проверить версии и напоминания | Первая result version за 1 микросекунду до task deadline допустима, на границе запрещена; append-only дополнение в нерешённом review допустимо и не сдвигает 72 часа; после решения/спора обычная версия запрещена; решения до 24/48 часов подавляют напоминания; повтор worker не отправляет дубликат |
| 9 | Проверить partial одного места и произвольную награду | Награда 1: partial запрещён; 2/3/4/5/11 дают 1/2/2/3/6. Member-task исчерпывает reserve slice выплатой+refund; community-task не имеет member reserve и выпускает только фактическую выплату; другие места не меняются; concurrent duplicate создаёт один эффект |
| 10 | Проверить отсутствие жёсткого лимита | Любое число валидных assignments пары можно принять и оплатить; частота сама по себе не вызывает отказ, rollback выплаты или автоматический penalty |
| 11 | Проверить окно admin alert | При стартовом threshold `3` первые три оплаченных full/partial assignments не создают alert, четвёртый в окне `(T-7 суток, T]` создаёт один; событие ровно на нижней границе исключено; направление, категория и template version не разделяют пару; community-task не считается |
| 12 | Проверить alert crossing, policy switch и re-alert | Pair lock сериализует выплаты: crossing не теряется. Open old-policy alert → activation new policy → new-policy crossing обновляет тот же alert с обеими policy versions, не создавая второй. Close disarms по current policy; выше threshold re-alert нет, после decay до `<= threshold` crossing создаёт следующий episode. Duplicate callback не дублирует; threshold 0 отключает новые alerts; config activation сама не создаёт alerts |
| 13 | Проверить privacy и outcomes alert | Только active administrator с `interaction_review` читает/закрывает alert и private meeting comment; member/moderator получают отказ. Все три outcomes требуют комментарий; `legitimate`/`monitor` не создают ledger; пользовательские логи/уведомления не раскрывают объяснения |
| 14 | Проверить точный penalty | Только `penalty_recommended` атомарно создаёт outcome и до одного penalty на каждого участника. Business key `interaction_alert:{alert_id}:member:{member_id}:penalty` делает retry безопасным; можно оштрафовать одного или обоих, но не одного дважды. Invalid/over-balance penalty откатывает весь outcome; reserve/experience/negative balance не затрагиваются |
| 15 | Проверить community create/catalog safety | Member/moderator не создают community-task. Active admin создаёт immutable card с origin, reviewer, estimated minutes, minimum level, verifiable criterion, bounded scope и reward; card видна как `Сообщество`. Missing/unbounded/non-verifiable card, >120 minutes, mandatory like/subscribe/positive review/endorsement или platform violation отклоняются. Reward >4 без justification+second confirmation отклоняется; valid override журналируется; published snapshot не переписывается |
| 16 | Проверить community cancel matrix | До acceptance authorized admin отменяет без issuance; после acceptance до submission отмена допустима только по community/system fault с reason/audit/notification и appeal без performer `no_show`; после submission, в review/dispute и terminal обычная cancel запрещена |
| 17 | Проверить independent reviewer, replacement window и autoconfirm | Reviewer→performer acceptance и performer→reviewer reassignment запрещены без independent replacement; admin-performer не review. Потеря reviewer даёт `reviewer_required`, zero issuance и alert. Replacement сразу разрешает manual review, создаёт новое 72h window с dedup reminders 24/48 и autoconfirm at 72; voluntary valid-reviewer replacement сохраняет original deadline. Dispute и concurrent review/autoconfirm сериализуются |
| 18 | Проверить community ledger lifecycle | Full/partial/retry создают один `community_task_reward` и равный опыт; reject/cancel/expire не выпускают кредиты; dispute блокирует issuance; resolution создаёт один допустимый эффект; свободного `community_bonus` и личного admin reserve нет |
| 19 | Согласовать D-007/D-008 и весь docs-impact | Журнал датированно сохраняет template-only для member-task и добавляет ограниченный community origin; D-008 перечисляет `community_task_reward`/`penalty`. PRD, domain, flows, catalog, interface, data model, moderation, implementation/test plans содержат community create/cancel/review и alert/meeting/penalty без старых противоположных гипотез |
| 20 | Проверить миграционные последствия и будущие тесты | Для каждого Q указаны schema/config/index/transaction последствия; есть config failure/backfill, origin lifecycle, deadline/review, alert crossing/re-alert/privacy и penalty concurrency/idempotency проверки |
| 21 | Проверить локальные Markdown-ссылки изменённых файлов | Каждая относительная ссылка разрешается в существующий файл |
| 22 | Выполнить `git diff --check origin/main...HEAD` и `git diff --cached --check` перед коммитом | Обе команды завершаются с кодом 0 |
| 23 | Проверить язык и секреты | Смысловой текст на русском; нет токенов, учётных данных, приватных идентификаторов и секретоподобных значений |

## Команды контроля

```powershell
rg -n "Q-(002|003|004|007|008|009|010|012)|TBD|50%|30 дней|стартов" docs/mvp
rg -n "0, 10, 25, 50, 100, 180, 300, 450, 650|72|24|48|ceil|community_bonus" docs/mvp tasks/CB-4
git diff --check origin/main...HEAD
git diff --cached --check
```

Локальные Markdown-ссылки проверяются скриптом чтения всех изменённых `.md`: внешние URL пропускаются, относительные пути разрешаются от каталога исходного файла, отсутствующий target завершает проверку ошибкой.

## Барьер завершения

Нельзя отмечать сценарий пройденным только по наличию числа в одном файле. Доказательством является одновременное совпадение журнала решений, всех связанных документов, матрицы миграционных последствий и будущих тестов.
