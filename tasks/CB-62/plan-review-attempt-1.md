# CB-62 — ревью плана перехода к Mini App-only

Schema: `community_bot.plan_review.verdict.v1`

Status: changes_requested

## Проверенные источники

- Jira snapshot из `plan-source-context.md`, `inventory.md`, `plan.md` и
  `test-plan.md` прочитаны полностью.
- Проверены proposed ADR-0016, принятый ADR-0014 и заменяемые runtime/process
  части ADR-0008, ADR-0009, ADR-0011, ADR-0012 и ADR-0013. ADR-0016 остаётся в
  статусе `Предложено`; принять его может только владелец после успешного plan
  review.
- Сверены `TECH_STACK.md`, журнал решений, ADR index, канонические правила,
  staged diff и фактическое дерево на `21a4b4c`.
- Прослежены импорты и зависимости `transport/telegram`, bot bootstrap,
  `worker/entrypoint.py`, `infrastructure/outbox/{telegram,postgres}.py`,
  application services, PostgreSQL stores/models, Alembic revisions и
  смешанные integration tests.
- Staged diff содержит только пять плановых/ADR-файлов; `git diff --cached
  --check` проходит. Текущие import-boundary и notification tests независимо
  проходят: `19 passed`.

## Замечания по области

1. **High — подтверждено: keep|replace|delete inventory недостаточно точен для
   безопасного исполнения и собственного allowlist gate.** `inventory.md`
   одновременно сохраняет основной `application/` и `infrastructure/db/`, но
   удаляет неопределённые `pilot/test-run services`; `plan.md` также удаляет
   `presentation tests` без списка исключений. Для фактических путей это не
   даёт однозначного решения:

   - `application/conversations.py` и `application/navigation.py` являются
     Telegram chat orchestration, хотя находятся внутри сохраняемого слоя;
   - `infrastructure/db/conversations.py`, `infrastructure/db/test_runs.py` и
     соответствующие методы общего `Database` смешаны с сохраняемым UoW;
   - модели legacy conversation/test-run и их поля нужны для соответствия уже
     применённой schema, даже если исполняемые services удаляются;
   - integration-файлы с import `aiogram` содержат одновременно transport
     сценарии и критические проверки общего ядра.

   Поэтому заявленное сравнение tracked paths с `inventory.md` сейчас нельзя
   реализовать детерминированно: исполнитель должен сам решать, удалять,
   сохранять или расщеплять эти файлы. Для destructive Level 3 задачи это риск
   необоснованного удаления общей логики и контрактное нарушение плана.

## Замечания по дизайну

1. **High — подтверждено: удаление test-run hooks не задаёт безопасное
   поведение для сохранённых исторических строк.** План запрещает destructive
   migration и сохраняет `test_run` tables/columns, но предлагает механически
   удалить test-run services/hooks и все их tests. Сейчас эти hooks являются
   не только pilot UI:

   - `infrastructure/db/tasks.py` скрывает `TaskModel.test_run_id != NULL` из
     обычных pending/owned/available выборок и повторно проверяет scope при
     прямом доступе;
   - `infrastructure/db/assignments.py` и `task_cancellations.py` применяют тот
     же барьер к assignments и cancellation cards;
   - `infrastructure/outbox/postgres.py` ограничивает адресатов test
     publications участниками run и исключает active test members из обычной
     широкой рассылки.

   Если удалить `active_scope`, `participant_ids` и связанные predicates,
   сохранив строки, старые test cards могут стать видимыми обычному Mini App
   actor, а pending outbox/notifications — получить более широкую доставку.
   ADR-0013 прямо обещает обратное даже после завершения run: карточки исчезают
   из рабочих представлений, а audit/ledger остаются. Proposed ADR-0016 снимает
   live-test runtime, но не обосновывает отмену этой data-isolation
   постусловия.

2. **Medium — подтверждено: удаление общего `ops/` не разделяет снятую R1
   topology и PostgreSQL data-safety capabilities.** Deploy wrappers и
   `smoke_production.py` действительно bot-specific, однако
   `backup_postgres.py` и `restore_drill.py` проверяют logical backup,
   migration revision и ledger reconciliation. Они привязаны к старому
   Compose helper, но защищают сохраняемую PostgreSQL, а не Telegram UI.
   План должен явно выбрать: адаптировать/сохранить эти capabilities, назначить
   их replacement в CB-56 с честным временным recovery gap либо получить
   отдельное принятие потери текущего backup/restore gate. Категория «удалить
   весь `ops/`» этого решения не содержит.

Положительно подтверждено: прямые скрытые зависимости worker/outbound adapter
от удаляемого UI найдены самим планом. `worker/entrypoint.py` импортирует
`main_menu_markup`, а `infrastructure/outbox/telegram.py` — callback builder и
inline keyboard; замена на allowlisted plain delivery находится в области
CB-62 и не реализует преждевременно CB-51–CB-56. Domain/application не
импортируют `aiogram`; общий ledger, audit, outbox и worker архитектурно можно
сохранить.

## Замечания по проверкам

1. **High — подтверждено: категория «Telegram presentation tests» может удалить
   единственное доказательство общих транзакционных инвариантов.** Например,
   `tests/integration/test_task_creation.py`, `test_assignments.py`,
   `test_registration.py` и `test_moderation.py` импортируют aiogram/routers на
   уровне файла, но большинство их сценариев вызывают application services и
   PostgreSQL напрямую. В этих же файлах находятся atomic/exactly-once,
   rollback-after-ledger/outbox, concurrency, audit и migration tests. Простое
   удаление файла как presentation suite оставит зелёный уменьшенный pytest,
   но потеряет защиту сохраняемого ядра. Coverage `>=80%` это не обнаружит.

2. **Medium — подтверждено: migration gate проверяет присутствие revisions, но
   не их неизменность.** Изменённая historical revision может пройти
   upgrade/downgrade/upgrade и проверку «ни один файл не удалён». План заявляет,
   что revisions остаются неизменными, поэтому test plan должен сравнивать
   exact path/content manifest или требовать пустой diff для уже существующих
   `migrations/versions/*` относительно base `21a4b4c`.

3. Для безопасного удаления test-run runtime отсутствует обязательный
   PostgreSQL regression: seed legacy active/completed test run, test task,
   assignment и pending outbox/notification, затем доказать, что обычный actor
   не видит эти записи и worker не расширяет их адресатов после удаления
   управляющего CLI.

## Обязательные исправления

1. Сделать `inventory.md` исполняемым manifest: задать точные paths/globs и
   исключения `keep|replace|delete` для всех runtime, test, ops, docs/config и
   package files. Отдельно классифицировать conversations/navigation,
   pilot/test-run application и DB modules, ORM models/UoW methods, mixed
   integration suites и оба Compose-файла.
2. Зафиксировать post-removal quarantine для исторических `test_run_id` rows.
   При запрете destructive migration сохранить fail-closed `IS NULL` barriers
   и безопасное подавление/адресацию legacy outbox/notifications без зависимости
   от удалённого управляющего runtime. Добавить описанный PostgreSQL regression.
3. До удаления mixed Telegram integration files выделить или переписать все
   сохраняемые application/PostgreSQL assertions; gate должен сравнивать
   обязательный список инвариантов, а не только итоговый процент coverage.
4. Усилить migration gate точной неизменностью всех существующих revisions.
5. Разделить bot-specific deploy/smoke operations и общую backup/restore
   способность, явно зафиксировав её keep, replacement или принятый временный
   gap.
6. После одного консолидированного исправления полного пакета передать его на
   одну повторную независимую проверку до принятия ADR и начала удаления.

## Остаточные риски

- Временное отсутствие пользовательского runtime после merge является явным
  решением владельца и корректно отражено в ADR; это не finding.
- Telegram-shaped application signatures остаются до CB-51. Они допустимы как
  переходный долг, пока CB-62 не удаляет содержащие бизнес-правила services.
- Старые task artifacts можно удалить из текущего дерева при сохранении Git/Jira
  истории и исправлении всех внутренних ссылок; это намеренная cleanup-область,
  а не причина текущего verdict.
