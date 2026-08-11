# CB-21 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-21` повторно прочитана напрямую через Atlassian Rovo API: bug
  `High`, девять критериев приёмки, parent CB-2 и blocking relation к CB-16.
- С нуля сверены Level 3 package, approved plan review, обновлённый test-plan,
  implementation report, interface/user/runbook documentation и полный staged
  diff exact tree `ce90dd1c83fc83de7143e6f0f32ce0c5ed26611d`.
- Отдельно проверено закрытие M-001/M-002: current-availability cursor predicate,
  existing-unavailable PostgreSQL case, plain-text invitation payload и bot
  username с underscore.
- Повторён targeted navigation gate:
  `uv run pytest -ra tests/integration/test_navigation.py --no-cov` —
  `3 passed`; Ruff и ty для изменённого контура — успешно. Принято прежнее
  evidence общего targeted набора `7 passed`, build/entrypoints и compatibility
  cases. Full regression не запускалась и остаётся CB-16.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- Task cursor теперь выбирается тем же `availability` predicate, что и карточки
  основной страницы: published/live/level/not-self/free-slot/not-assigned.
- Если существующая cursor row уже недоступна, keyset boundary не применяется и
  запрос возвращает актуальную первую страницу.
- PostgreSQL test переводит cursor-task в `cancelled`, затем сравнивает полный
  результат callback-page с новым current first page. Missing UUID restart и
  обычные страницы `10 + 1` сохранены.

### Закрытие M-002

- Invitation response явно использует `parse_mode=None`; dynamic deep link и
  fallback `/start <token>` больше не проходят через legacy Markdown parser.
- Transport test захватывает фактический `SendMessage` payload для
  `humanquest_bot` и подтверждает `parse_mode is None`.
- Invitation creation/replay, deep link и admin gate не менялись.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| `/tasks` и accept без ручного UUID | Пройден | Полная discovery policy, stable 10+1 keyset, missing/existing-unavailable restart и authoritative accept callback |
| `/create` durable flow | Пройден | Catalog callback открывает existing persistent draft, task FSM получает последующий текст |
| `/balance` safe history | Пройден | Только own balance и 10 allowlisted ledger rows без comments/чужих данных |
| `/help` актуален | Пройден | Runtime help, reply keyboard и USER_GUIDE согласованы |
| `/admin` active-only и рабочие действия | Пройден | Exact gate, invite plain-text deep link, registrations/moderation callbacks |
| Legacy commands compatible | Пройден | Exact navigation filters/prefixes и synthetic compatibility evidence |
| Документация/runtime совпадают | Пройден | Interface, USER_GUIDE, runbook, test-plan и report синхронизированы |
| Production Dispatcher E2E без user UUID | Пройден | Main flows, persisted effects, router order, replay и safe SendMessage payload |
| Ruff, ty, targeted tests | Пройден | Navigation `3 passed`, общий targeted `7 passed`, Ruff/ty/build/diff evidence |

Итог: `9/9` критериев пройдены.

## test_matrix_result

| Сценарии | Результат |
|---|---|
| 1: active `/start` | Пройден; полное меню |
| 2: `/tasks`/pagination | Пройден; policy, 10+1, missing и existing-unavailable cursor restart |
| 3: accept/replay | Пройден; один assignment |
| 4: create/template | Пройден; durable draft без user UUID |
| 5–6: balance/help | Пройдены |
| 7: active admin actions | Пройден; safe plain-text invite и обе queues |
| 8: non-admin denial | Пройден для member/moderator/pending/unknown без state leak |
| 9: legacy commands | Пройден compatibility evidence |
| 10: restart/replay | Пройден для draft/assignment/invite |
| 11: callback tampering | Пройден; malformed UUID без effects, stale cursor safe restart |
| 12: docs/runtime | Пройден |

Итог: `12/12` сценариев пройдены.

## security_and_secret_result

- `/tasks` применяет active actor, sanction, active limit, level, deadline,
  free-slot, self/already-assigned filters; callback повторяет authoritative
  acceptance policy.
- `/admin` и каждый callback заново требуют active administrator; denial не
  раскрывает queues.
- Invitation token выдаётся только администратору plain text, persisted only as
  hash; balance/history и admin queue presenters не выводят private comments.
- Staged secret scan/diff-check чисты; реальных Telegram отправок не было.

## workflow_result

- Level 3 package полон; Jira, `Status: approved` plan review, ветка
  `task/CB-21`, test-plan/report/docs и bug-fix scope согласованы.
- Delta закрытия ограничен двумя findings, tests и честной синхронизацией
  report/test-plan; остальные девять AC не регрессировали.
- Exact staged tree после проверки остаётся
  `ce90dd1c83fc83de7143e6f0f32ce0c5ed26611d`.
- Jira, staged index, Git remote и Telegram не изменялись; обновлён только
  существующий unstaged `tasks/CB-21/final-review.md`.

## required_actions

Нет.

## residual_risks

- Read page может устареть после ответа и до accept callback; это допустимый UX
  race, поскольку callback повторяет всю policy под DB gates.
- Fake Bot API подтверждает production method payload/router wiring, но не
  доступность Telegram network; это корректная targeted граница.
- Полная регрессия выполняется один раз в CB-16 после слияния regression fixes.
