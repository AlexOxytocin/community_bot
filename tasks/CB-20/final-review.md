# CB-20 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-20` повторно прочитана напрямую через Atlassian Rovo API: bug
  `High`, семь критериев приёмки, parent CB-2 и блокировка общей регрессии CB-16
  подтверждены.
- С нуля сверены обязательные документы и полный Level 3 пакет `tasks/CB-20`,
  включая точный `Status: approved` plan review, test-plan и обновлённый
  implementation report.
- Проверен exact staged tree
  `8ed2cb3fc2f44acab927fa17ed8b19af89771a5b`, полный CB-20 scope и точный delta
  закрытия M-001: application guard, mixed-state PostgreSQL negative test и
  синхронизация report.
- Повторён полный targeted gate CB-20:
  `uv run pytest -ra tests/unit/test_initial_admin.py tests/integration/test_initial_admin.py --no-cov`
  — `13 passed`, без skip/deselect; Ruff и ty для исправленного контура —
  успешно. Приняты подтверждённые build/entrypoint/diff gates. Полная регрессия
  не запускалась и остаётся CB-16.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- Idempotent outcome теперь рассматривается только при
  `len(active_administrators) == 1`.
- Единственный administrator должен одновременно совпадать с target Telegram ID
  и иметь exact bootstrap provenance; иначе дальнейшая проверка даёт conflict.
- Новый PostgreSQL test создаёт bootstrap-admin с provenance и второго active
  administrator, повторяет bootstrap первого ID, получает
  `InitialAdministratorConflictError` и подтверждает неизменные counts:
  `2 members / 1 audit`.
- Изменение не расширяет роль bootstrap CLI и не затрагивает обычное управление
  администраторами.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| CLI с обязательным Telegram ID | Пройден | Entry point, safe parser, help smoke и реальный CLI main в E2E |
| Только без active admin; idempotency/conflict | Пройден | Exact single-admin provenance guard, same/different concurrency и mixed multi-admin negative test |
| Audit и безопасная причина | Пройден | Allowlisted reason, system actor, safe after projection; ID/token/argv/private payload исключены |
| Dispatcher invite и регистрация | Пройден | Production `_dispatcher`, limited hashed invite, `/start`, pending member и durable receipts |
| Точный runbook | Пройден | Immutable current-image, env/project context, initial/clean recovery и exit codes |
| PostgreSQL E2E с пустой схемы | Пройден | CLI→Dispatcher→invite→registration на migrated PostgreSQL |
| Targeted quality gates | Пройден | `13 passed`, Ruff, ty, build/entrypoint и staged diff evidence |

Итог: `7/7` критериев пройдены.

## test_matrix_result

| Сценарии | Результат |
|---|---|
| 1–2: first bootstrap / exact retry | Пройдены; одна member/audit pair, повтор без записи |
| 3–4: active admin/target conflicts | Пройдены, включая mixed state с bootstrap provenance и вторым active admin |
| 5–6: concurrent different/same IDs | Пройдены под advisory xact lock без deadlock |
| 7: invalid ID/reason | Пройден; отклонение до транзакции и generic safe error |
| 8: fault rollback/retry | Пройден; обе записи откатываются, безопасный retry побеждает |
| 9–10: CLI→Dispatcher invite→`/start` | Пройдены одним PostgreSQL E2E, Bot API transport только подменён |
| 11: audit/privacy/member state | Пройден; exact deterministic state и отсутствие private/grant данных |
| 12: CLI smoke | Пройден |

Итог: `12/12` сценариев пройдены; дополнительные conflict permutations дают
общий targeted результат `13 passed`.

## security_and_secret_result

- Bootstrap atomic и сериализован transaction-scoped advisory lock; fault path
  откатывает member и audit.
- CLI не отражает raw invalid argv и логирует unexpected DB failure без
  traceback/SQL parameters.
- Audit содержит только внутренний UUID, allowlisted reason, роль, статус и
  permissions. Invitation хранит hash; реальные Telegram credentials и
  отправки в тесте отсутствуют.
- Staged secret scan и diff-check ранее подтверждены чистыми; новый delta не
  добавляет credentials.

## workflow_result

- Level 3 package полон, plan review одобрен, ветка `task/CB-20` и scope
  корректны; новый ADR не нужен, поскольку используются существующие
  PostgreSQL/member/audit/Dispatcher contracts.
- Implementation report честно синхронизирован с mixed-state guard и
  `13 passed`.
- Exact staged tree после проверки остаётся
  `8ed2cb3fc2f44acab927fa17ed8b19af89771a5b`.
- Jira, staged index, Git remote, production server и Telegram не изменялись;
  обновлён только существующий unstaged `tasks/CB-20/final-review.md`.

## required_actions

Нет.

## residual_risks

- Оператор с production DB credentials остаётся доверенной стороной; доступ
  регулируется root-only operational contract ADR-0009.
- Fake Bot API подтверждает production Dispatcher wiring, но не сетевую
  доступность Telegram; это корректная граница targeted bootstrap E2E.
- Полная продуктовая регрессия выполняется один раз в CB-16 после слияния
  regression fixes.
