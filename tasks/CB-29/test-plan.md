# CB-29 — тест-план полной цепочки MVP

## Правило доказательства

Для UI-сценария сохраняются: вход, безопасный фрагмент ответа, видимый следующий
элемент и результат. Внутренний UUID/callback не считается доказательством, если
его не вернул предыдущий Bot response.

## Матрица

### A. Production readiness

1. Immutable image, Alembic head, bot/worker/database healthy.
2. Ровно одна активная product config, 10 уровней, assignment/alert policy.
3. Catalog seed доступен; активные категории/шаблоны есть.
4. Active users имеют разрешимую level config version.
5. Ledger sum равен caches; orphan/FK count равен нулю.

### B. Регистрация

6. Admin создаёт одноразовое приглашение из видимого меню.
7. Новый actor проходит consent и все поля из последовательных prompt.
8. Город однозначно определяет timezone; ambiguity просит ближайший город.
9. Restart/resume продолжает exact step; stale answer не загрязняет следующий.
10. Submit достижим из preview; заявка появляется в admin queue.
11. Approve берётся из карточки заявки; replay/concurrency дают один grant.
12. Reject → edit → resubmit → approve использует тот же member.

### C. Профили и навигация

13. Все кнопки главного меню дают содержательный результат/пустое состояние.
14. Own profile active/paused и edit всех полей.
15. Members catalog показывает active profiles и скрывает non-active.
16. Profile callback/pagination/direct access используют одну policy.
17. Balance/history/statistics/leaderboard работают без знания UUID.
18. Admin menu доступно только active administrator.

### D. Каталог и создание задания

19. Browse/filter/pagination и stale cursor.
20. Create flow выбирает template из Bot response.
21. Draft переживает restart; preview не резервирует.
22. Publish резервирует один раз; replay не создаёт task/ledger duplicate.
23. Insufficient balance и invalid payload не оставляют эффектов.
24. Cancel unaccepted task возвращает полный резерв без опыта.

### E. Назначение и результат

25. Accept берётся из карточки; self/level/status/limit/last-slot checks.
26. My assignments достигается без UUID; cancel освобождает unpaid slot.
27. Result draft/version/preview/submit переживают restart.
28. Full settlement: reserve → performer credits/experience exactly once.
29. Partial matrix `2/3/4/5/11 → 1/2/2/3/6`: credits и experience равны
    фактической выплате; member-origin возвращает остаток и исчерпывает резерв,
    community-origin выпускает только фактическую `community_task_reward`;
    replay не создаёт второй ledger/outbox/receipt effect.
30. Только reject открывает полуинтервал dispute `[rejected_at, rejected_at+24h)`;
    full/partial применяются немедленно и поздний dispute не открывают;
    finalizer без dispute ровно один раз возвращает member reserve либо закрывает
    community slot без выпуска.
31. Deadline/no-show и race с submission дают один исход.

### F. Спор и модерация

32. Dispute создаётся из доступного assignment action и виден в admin queue.
33. Moderator preview/confirm берутся из ответов; party conflict запрещён.
34. Full/partial/refund/no-fault/no-show/creator-abuse/fraud матрица.
35. Appeal доступна один раз в полуинтервале `[resolved_at, resolved_at+7d)` и
    решается другим active administrator
    без конфликта; exact reversal каждого прежнего эффекта и новый outcome
    атомарны. `insufficient_reversible_balance` откатывает case, ledger, audit,
    outbox и receipt целиком; оплаченный slot после appeal остаётся занят.
36. Sanction/revoke/expiry и action-specific restriction.
37. Private comments отсутствуют в user notifications/logs.

### G. Карма и участники

38. Eligibility только после member-origin nonzero payout и в обе стороны;
    после любой correction/reversal она сохраняется навсегда, хотя новая mutation
    всё ещё требует актуального `active` у обоих участников.
39. Profile → visible karma action → value → comment → confirm.
40. Изменение оценки обновляет одну current row и append-only history.
41. Recipient/moderator видят только aggregate/count.
42. Active admin с `karma_review` видит raw/history с audit; остальные нет.

### H. Community/alerts/notifications

43. Community task имеет независимого reviewer и системную reward ветку.
44. Conflict-of-interest и reviewer replacement.
45. Четвёртое взаимодействие пары создаёт один non-blocking alert.
46. Alert outcome/penalty bounded, manual и idempotent.
47. Notification materialize/deliver retry/dedup/timezone/deadline reminders.

### I. Сквозные приёмочные истории

48. A — два участника: регистрация → task → full payment → leaderboard.
49. B — publish → unaccepted cancel → exact refund.
50. C — reject/dispute → moderator partial resolution → ledger/status/audit.
51. D — paid interaction → karma `+1` → `-1` → anonymous aggregate/raw history.

## Команды gate

```text
docker compose up -d postgres
uv run pytest -ra
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv build
uv run community-bot --check
uv run community-worker --check
```

Migration, reconciliation, real Telegram и production readiness выполняются
именованными сценариями из `journey-matrix.md`; их результат не заменяется
общим числом passed tests.

## Безопасная production-граница

- Без отдельного нового поручения: только `/start`, help/menu, read-only profile,
  balance, statistics, leaderboard, members, catalog и admin queues.
- Real Telegram smoke останавливается до первого durable-write действия: не нажимает
  `Создать приглашение` (оно пишет сразу, без confirm) и не выбирает task template
  (выбор создаёт durable draft); чужие approval/reject, settlement, dispute, karma
  и moderation не выполняются.
- Собственная mutation требует заранее названную disposable entity и только
  штатный `revoke`/`cancel`; после него проверяются ledger/domain эффекты.
- Нет product cleanup — smoke останавливается до первого durable-write действия.
  SQL cleanup и удаление audit/receipts запрещены.

## Jira reconciliation

Финальный отчёт выполняет JQL
`project = CB AND labels = cb16-regression ORDER BY key` и сопоставляет каждый
`defect` из journey matrix с Bug/duplicate. Open critical/high отсутствуют;
каждый open medium/low имеет явное решение владельца `accepted|deferred`.
