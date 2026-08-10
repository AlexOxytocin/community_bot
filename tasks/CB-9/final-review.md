# CB-9 — повторное независимое финальное ревью

`community_bot.final_review.verdict.v1`

Status: approved

## Проверенная область

- Свежая Jira `CB-9` прочитана через Atlassian Rovo API без внешних изменений: статус `На проверке`, parent `CB-2`, завершённые блокеры `CB-4`/`CB-6`, исходящая блокировка `CB-10` и шесть критериев приёмки.
- Повторно проверены канонические документы, Level 3 пакет, `plan-review.md` с точным `Status: approved`, `test-plan.md`, обновлённый `implementation-report.md` и полный staged diff.
- Ветка `task/CB-9` основана на `origin/main=e9adcfe526c9a15960d007ed5ac6ab340bcbdc1a`. Проверенный staged tree: `8fc05540b85cccbd5fabd5ff4005e3b15a5e0417`.
- Jira, Git remote, код и Telegram во время ревью не изменялись. Перезаписан только настоящий локальный артефакт.

## Результат повторного ревью

### M-001 — закрыто

Категория стала частью неизменяемой логической идентичности `template.code` на обоих обязательных слоях:

- `CatalogService.publish_version` после блокировки всех версий code отклоняет draft с другим `category_code` до вставки, аудита, receipt и commit;
- PostgreSQL trigger `trg_task_templates_category_identity` отклоняет прямой INSERT следующей версии того же code с другим `category_id`;
- миграционный downgrade удаляет добавленную trigger function;
- документация фиксирует тот же контракт.

Прежний reproducer повторён на новой изолированной PostgreSQL 18 БД: первая страница и cursor получены, затем выполнена попытка выпустить уже показанный `repository_first_impression` в категории `career`, после чего запрошена следующая страница.

```text
CROSS_CATEGORY_REJECTED=True
DUPLICATED_SHOWN_CODE=False
```

Targeted integration test отдельно подтверждает отказ PostgreSQL при прямом обходе application service.

### M-002 — закрыто

Добавлены и независимо прошли прямые доказательства всех ранее отсутствовавших границ:

- manifest содержит точные восемь UUID и code категорий, точные восемь UUID и code шаблонов, обе Draft 2020-12 schema и обязательный safety copy;
- member, moderator и paused administrator получают отказ без новых receipt и audit;
- input с неверным type отклоняется до downstream spy;
- result проходит проверку по точной исторической v1 после публикации v2, неизвестное поле отклоняется;
- synthetic Telegram проверяет unauthorized admin command, invalid arguments, успешную команду и exact replay; остаются ровно одна новая версия, один receipt и один audit.

Независимая проверка manifest дополнительно подтвердила точные списки code/UUID, ровно `standard_input` и `standard_result`, а также safety copy про запрет требовать публичный сигнал, защиту персональных данных и отсутствие медицинских обещаний.

## Критерии Jira

| Критерий | Результат | Доказательство |
|---|---|---|
| Видны только active и доступные шаблоны | Пройден | active category/template filters и актуальный `LevelResolver` при stale cache |
| Пагинация без пропусков и дублей | Пройден | стабильный logical key, новая reward-version между страницами и запрет смены категории на application/DB слоях |
| Изменение стоимости создаёт новую версию и не меняет историю | Пройден | последовательные v2/v3, неизменная v1, historical read и active unique |
| Неактивная категория скрывает новые публикации без удаления истории | Пройден | toggle, повторное включение и PostgreSQL immutability barriers |
| Невалидные обязательные поля отклоняются до доменной команды | Пройден | closed JSON Schema, wrong-type input до downstream spy и historical result validation |
| Seed и миграции воспроизводимы на пустой базе | Пройден | точный manifest `8 + 8`, upgrade и цикл `0004→0005→0004→0005` |

## Независимо выполненные проверки

```text
Targeted pytest из implementation report             37 passed, exit 0
                                                      0 skipped/deselected
Прямой PostgreSQL reproducer прежнего duplicate       rejected=True, duplicate=False
uv run ruff format --check .                          exit 0, 165 files
uv run ruff check .                                   exit 0
uv run ty check                                       exit 0
git diff --cached --check; git diff --check           exit 0
Проверенный staged tree                               8fc05540b85cccbd5fabd5ff4005e3b15a5e0417
Staged secret-like scan                               0 совпадений
Runtime Jira-key scan                                 0 совпадений
Локальные Markdown-ссылки                             0 битых ссылок
```

Полная регрессия MVP намеренно не запускалась: по принятому процессу она относится к `CB-16`.

## Секреты, безопасность и процесс

- Секретов, сессий и реальных Telegram-данных в staged diff не найдено.
- Synthetic Telegram использует fake session без сетевого Bot API.
- Admin mutations сохраняют порядок `update gate → exact receipt → catalog gate → actor/version locks → audit/receipt → commit`; unauthorized, invalid и replay пути не создают частичных эффектов.
- Несвязанных изменений и Jira-ключей в исполняемых именах нет; смысловые артефакты написаны по-русски.

## Итог

Критических, существенных и обязательных незначительных замечаний не осталось. M-001 и M-002 закрыты, все шесть Jira AC имеют воспроизводимые доказательства, staged snapshot готов к дальнейшему процессу слияния.

Остаточный риск полной совместимости собранного MVP остаётся в CB-16 и не блокирует CB-9.
