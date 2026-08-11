# CB-12 — целевой план проверки

## Контур

PostgreSQL 18, реальные ledger/assignments/reliability events, общий UoW и
synthetic aiogram. Проверки запускаются одним targeted gate после полной
реализации CB-12; full regression остаётся CB-16.

## Сценарии

| № | Сценарий | Обязательный результат |
|---:|---|---|
| 1 | Empty upgrade и `0007→0008→0007→0008` | Таблицы, backfill permission, constraints и triggers воспроизводимы |
| 2 | Self, no paid interaction, community-origin payout, zero/reversed-only fixture | Карма запрещена без vote/history/audit/outbox/receipt; permanent eligibility возникает только от исходной ненулевой member payout |
| 3 | Первая full и partial member payout в обоих направлениях | Оба участника навсегда могут оценивать друг друга |
| 4 | Первая оценка, exact replay и payload conflict | Одна current row и одна history revision; replay стабилен, conflict без эффектов |
| 5 | Последовательные `+1→-1→0` | Одна current row, три revisions; aggregate изменяется на `-2`, затем на `+1` |
| 6 | Два concurrent confirm с разными update IDs на один locked karma state и fault injection | Ровно один commit/revision/receipt; второй видит terminal absence/stale revision без эффектов; rollback не оставляет частичных эффектов |
| 7 | Invalid value/comment, inactive rater/target и stale draft | Отказ без current/history/receipt и без утечки target |
| 8 | Recipient projection через service, Telegram, forged callback, outbox/log capture | Только aggregate score/count; нет rater UUID, comments и history |
| 9 | Moderator, admin без `karma_review`, fake permission token | Одинаковый отказ raw view без audit/data |
| 10 | Permission/status cross-product: active/non-active target, active/inactive admin, `karma_review`/`member_read` | Active target требует `karma_review`; non-active — оба права; остальные варианты не раскрывают target; каждый фактический просмотр имеет audit, replay не дублирует effect |
| 11 | Own profile для active/paused и остальных status | Active/paused видят себя; остальные получают единый unavailable |
| 12 | Active actor читает active target; non-active/unknown/forged/stale cursor | Safe active profile доступен; скрытые варианты неразличимы и без полей/count |
| 13 | Admin `member_read` и без него читает non-active target | Только exact permission открывает safe projection; raw karma всё равно скрыта |
| 14 | Каталог с одинаковыми именами, pagination и сменой status между страницами | Стабильный keyset без duplicate/leak; policy повторно применена |
| 15 | Reliability full/partial/reject/no-show/performer cancel | Numerator `1/0.5/0/0/0`, denominator включает ответственные accepted assignments |
| 16 | `accepted` + terminal + responsibility chain | Creator cancellation/excused исключены; restored снова включён; root outcome не теряется, старая history не изменена |
| 17 | Reliability sample 4/5 и division boundary | До пяти — «Недостаточно данных»; с пяти — точное decimal значение |
| 18 | Личная статистика на multi-slot/member/community fixtures | Точные counts, опыт, recipients, categories, no-show; никаких private fields |
| 19 | Лидерборд меняет credits и karma при постоянном experience | Порядок не меняется |
| 20 | Каждый tie-breaker, zero experience, insufficient sample, stale level cache и final UUID tie | Ledger experience, recipients, sample flag/rate, no-show, reached_at sentinel и UUID применены строго по порядку; level cache version не влияет |
| 21 | Leaderboard pagination, inactive member и полный cursor на NULL/sentinel boundary | Нет inactive/duplicate; serialization round-trip сохраняет строгий total order |
| 22 | Durable karma draft: start→value→restart→comment→preview→confirm | Диалог возобновлён; одна vote/history/receipt; draft удалена после commit |
| 23 | `/cancel`, stale confirm, exact confirm replay, active `profile_edit` flow | Karma cancel безопасен; чужой flow не перезаписан/не удалён; stale/new terminal command без второго effect; exact replay стабилен |
| 24 | Direct SQL и migration permission matrix | Self/duplicate pair/invalid value запрещены; history UPDATE/DELETE запрещены; reliability chain не допускает cycle/cross-assignment/duplicate supersede; permission CHECK и active-admin-only backfill работают, downgrade чист |
| 25 | Итоговый targeted gate | Targeted pytest без skip/deselect, migration cycle, Ruff, ty, build, entrypoints, links/diff/secrets зелёные |

## Матрица Jira AC

- self/ineligible: 2–3, 7;
- repeated vote + history: 4–6, 24;
- `+1→-1 = -2`: 5;
- recipient anonymity: 8, 12–14, 22–23;
- admin audit: 9–10;
- reliability: 15–17;
- experience leaderboard: 19–21;
- unavailable profile and forged callback: 7–8, 11–14, 23.

## Правило дефектов

До завершения CB-12 все найденные дефекты исправляются в этой ветке. После
готовности всего MVP дефекты полной регрессии CB-16 получают отдельные Jira-задачи
и ветки.
