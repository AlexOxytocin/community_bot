# CB-5 — план проверки решений

## Область

Проверяется непротиворечивость документации и полнота будущего проверяемого
контракта. Runtime и БД в этой задаче не меняются; полный pytest не запускается.

## Сценарии

| № | Проверка | Ожидаемый результат |
|---:|---|---|
| 1 | Поиск заголовков Q-005/Q-006/Q-011 среди открытых вопросов | Заголовков нет; есть датированные принятые решения |
| 2 | Member A пытается оценить себя | Серверный отказ без karma revision и aggregate effect |
| 3 | A и B не имеют оплаченного terminal assignment | Оценка и изменение оценки запрещены |
| 4 | Между A и B есть full/partial settlement с ненулевой выплатой | Оценка разрешена в обоих направлениях, если оба active |
| 5 | Есть только cancelled/rejected/no-show/unresolved dispute/community-review relation | Eligibility отсутствует |
| 6 | После первой валидной выплаты выполняется correction или reversal экономики | Eligibility остаётся; current vote/history не удаляются; mutation определяется только актуальными статусами обоих участников |
| 7 | Две конкурентные первые оценки или два update одной пары | Одна current vote, последовательные immutable revisions, корректный aggregate |
| 8 | Получатель и любой moderator читают карму | Только aggregate/count; raw fields, timestamp и author отсутствуют независимо от клиентского permission token |
| 9 | Administrator без/с `karma_review` читает raw karma | Без права отказ; с правом данные доступны и создаётся audit event |
| 10 | Автор читает собственную оценку другому | Видит только собственные current value/comment и может изменить при eligibility |
| 11 | Active member открывает каталог и active profile по callback/UUID | Одинаковая safe projection доступна обоими путями |
| 12 | Active member открывает foreign profile каждого статуса `pending`, `paused`, `restricted`, `suspended`, `left`, `banned` | Для каждого одинаковый нераскрывающий отказ; ни один профиль не попадает в каталог |
| 13 | Пользователь каждого статуса открывает свой и чужой profile | `active`/`paused` видят свой; только `active` видит чужой active profile; `pending`/`restricted`/`suspended`/`left`/`banned` не используют обычный профильный интерфейс; karma mutation разрешена только `active` |
| 14 | Administrator без/с `member_read` открывает non-active profile | Без права отказ; с правом только safe/admin projection без экономических и karma raw данных |
| 15 | Поддельный callback, прямой UUID, stale cursor и смена target status между page/read | Ни один путь не обходит актуальную role/status policy и не раскрывает существование скрытой записи |
| 16 | Сверка PRD, domain, flows, interface, security, moderation, implementation plan, test plan и handoff | Нет противоположных TBD, старых продуктовых барьеров или различающихся role matrices |
| 17 | Проверка языка, ссылок, секретов и `git diff --check` | Русский смысловой текст, валидные локальные ссылки, нет секретоподобных значений, diff чист |

## Команды контроля

```powershell
rg -n "Q-005|Q-006|Q-011" docs/mvp
rg -n "karma_review|member_read|approved|partially_approved|active|paused|restricted|suspended|left|banned" docs/mvp tasks/CB-5
git diff --check origin/main...HEAD
git diff --check
```

## Барьер завершения

Упоминание идентификатора решения допустимо в принятом историческом контексте,
но ни один канонический документ не должен называть Q-005/Q-006/Q-011 открытым
или оставлять реализацию права на усмотрение CB-12.
