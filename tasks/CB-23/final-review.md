# CB-23 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-23` повторно прочитана напрямую через Atlassian Rovo API: Bug с
  severity `High`, шесть критериев приёмки, labels `cb16-regression` и
  `severity-high`, status `В работе`, `Relates` и blocking-связь с `CB-16`.
- С нуля сверены полный Level 3 package `tasks/CB-23`, CB-16 plan/test/final
  review, migrations `0009`/`0010`, обновлённый implementation report и весь
  staged diff.
- Проверен frozen staged tree
  `1b0ca6dd83fa9843a4518cd133f58cb646aa65e8` на ветке `task/CB-23`, база
  `9f6f197ea26f069401911d3067622374a6d0f203` после merge approved CB-22.
- Особо проверено закрытие единственного M-001 первого review: transaction
  UUID/payload hash/timestamp и все явно заданные task payload/timestamps теперь
  находятся в manifest и exact SQL oracle.
- Независимо повторён targeted gate:
  `uv run pytest -ra tests/integration/test_pilot_readiness.py::test_supported_schema_upgrade_preserves_outbox_semantics --no-cov` —
  `1 passed`; Ruff format/check, ty и staged diff-check — успешно. Full
  regression CB-16 не запускалась.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- UUID обоих grants, reserve и reward создаются до insert и сохраняются в
  `LegacySnapshot`.
- Transaction oracle сравнивает `id`, `idempotency_key`, member/FK, deltas,
  type, `payload_hash`, task/assignment FK и `created_at` для всех четырёх rows.
- Task manifest/oracle сравнивает exact identity/template/creator/category,
  author/title/description/criteria, materials/input/safety JSON, reward/slots/
  reserve/estimate/level/format/status, publish command и все заданные
  deadline/published/created/updated timestamps.
- Implementation report больше не обещает неопределённое «каждое поле каждой
  строки»: он точно говорит о полях, явно включённых в manifest.
- Полный oracle выполняется после первого и повторного `upgrade head`, поэтому
  исправление доказывает и preservation, и idempotent re-upgrade.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Fixture `0009` содержит representative chain | Пройден | 2 members, 4 ledger rows, task/assignment/result, karma current+2 history, moderation case+resolution |
| Counts, values, identities и значимые FK сохранены после `0010` | Пройден | Exact counts, manifest rows и шесть zero-orphan FK joins; M-001 закрыт полным transaction/task oracle |
| Legacy outbox сохраняется и получает correct statuses | Пройден | Published=`materialized`, unpublished=`pending`, identity/payload/timestamps сохранены |
| Guards/indexes и повтор `upgrade head` | Пройден | Constraints/indexes и три invalid outbox states проверены; второй upgrade повторяет полный oracle |
| Отдельная временная PostgreSQL DB и независимость порядка | Пройден | UUID database, `0009` создаётся внутри test, cleanup через `finally` |
| Targeted gate и independent final review зелёные | Пройден | Независимо повторены pytest/Ruff/ty/diff; этот verdict `approved` |

Итог: `6/6` критериев пройдены.

## test_matrix_result

| Сценарий test-plan | Результат |
|---|---|
| 1. Separate DB + upgrade `0009` | Пройден |
| 2. Insert representative chain | Пройден; schema `0009` принимает fixture и constraints |
| 3. Upgrade `0010` | Пройден; revision exact `0010` |
| 4. Counts и exact values | Пройден; `(2,4,1,1,1,1,2,1,1)` и все manifest rows совпадают |
| 5. FK joins | Пройден; orphan counts `(0,0,0,0,0,0)`, current resolution принадлежит той же case |
| 6. Outbox backfill | Пройден без потери identity/payload/timestamps |
| 7. Operational guards | Пройден; required constraints/indexes и invalid states |
| 8. Повтор `upgrade head` | Пройден; полный oracle повторён без изменений |
| 9. Изоляция/cleanup | Пройден; отдельная DB удаляется в `finally` |

Итог: `9/9` сценариев пройдены.

## security_and_secret_result

- Изменены только synthetic migration fixture/oracle и русские артефакты;
  production migration, runtime, schema и Telegram flows не менялись.
- Fixture использует только зарезервированные test IDs/UUID и фиксированные
  несекретные hashes/payload; реальные participant data отсутствуют.
- Secret-like scan staged diff не выявил credentials, Bot API tokens,
  connection strings или private keys; реальных Telegram-отправок не было.

## workflow_result

- Level 3 package полон: Jira, source context, plan, test-plan, точный
  `Status: approved` в plan review и честный implementation report согласованы.
- Ветка `task/CB-23` корректно отделена от frozen `task/CB-16` после merge
  approved CB-22; scope ограничен migration fixture/oracle.
- Full regression обоснованно не дублировалась: authoritative CB-16 gate уже
  выполнен, CB-23 изменяет только integration test и task artifacts.
- Frozen index tree после проверки остаётся
  `1b0ca6dd83fa9843a4518cd133f58cb646aa65e8`; Jira, index, Git remote и внешнее
  состояние не менялись. Approved `final-review.md` оставлен unstaged поверх
  frozen snapshot.

## required_actions

Нет.

## residual_risks

- Fixture намеренно привязан к supported revision `0009`; при смене исходной
  поддерживаемой схемы manifest/oracle потребуется явное обновление.
- Representative preservation test не заменяет доменную регрессию, но для
  дефекта CB-23 это правильная и достаточная targeted граница.
- Родительская CB-16 требует combined повторного final review после интеграции
  approved CB-23; этот verdict не выдаёт такой merge за уже выполненный.
