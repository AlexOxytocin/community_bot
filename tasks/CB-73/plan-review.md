# CB-73 — независимая проверка плана

Schema: `community_bot.plan_review.verdict.v1`

Status: approved

## Итог канонического recheck

Первый `changes_requested` закрыт полностью. Исправленный план больше не
считает широкий `list_review_cards` готовой authorization boundary: для list и
detail закреплён один member-owned predicate
`TaskModel.creator_id == actor.member_id` с assignment `submitted`, active
actor и тем же active test-run scope. Прямая публикация community-review rows
запрещена без нового слоя или repository.

Negative HTTP oracle теперь отдельно закрывает community-task creator с
назначенным другим reviewer, foreign/inactive actor и чужой test-run; ни list,
ни прямой detail не должны выдавать literal result или private fields.
Authoritative decision projection явно проверяет отсутствие `PARTIAL` при
reward `1` и наличие при reward `>=2` через существующий `partial_reward`, без
вычисления правила в UI.

Исправленный `REJECT` oracle соответствует live Jira: результат переходит в
`rejected_pending_dispute`, получает exact 24-hour deadline, payout/refund
остаются нулевыми, same-key replay возвращает прежний outcome, conflict и
конкурентный loser не создают повторных ledger/reliability/receipt/outbox
эффектов. Новое audit behavior план больше не обещает и не вводит.

## Проверенные gates

- `FULL / PARTIAL / REJECT` остаются существующими domain/application
  решениями; «Отклонить» не обещает доработку или resubmission.
- Literal free-form `result` проецируется без raw payload и внутренних полей;
  template/unsupported result закрывается fail-closed.
- Actor, assignment, command и canonical decision fingerprint входят в exact
  replay/conflict contract; transport не копирует ownership, reward, status
  или deadline rules.
- Diff ceiling остаётся `<=6` implementation/test файлов, `<=450` добавленных
  и `<=60` удалённых строк, с нулём schema/dependency/domain-rule изменений.
- Reuse/delete-first и stop gates требуют повторного remap после CB-70 и
  запрещают новые tables, migrations, models, services, repositories,
  frameworks и dependencies.
- Planned checks покрывают format/lint/type, PostgreSQL/API targeted coverage,
  browser journey, diff integrity, secret-like scan, независимый final review,
  PR/CI/merge и post-merge delivery/public smoke по ADR-0019.

Ponytail verdict: `Lean already. Ship.` после снятия dependency gate; лишних
абстракций в плане нет.

## Dependency gate и валидация

CB-70 всё ещё отсутствует в текущем `origin/main`: HEAD и `origin/main` равны
`b5a5648e0d26a262b4ff8c49b930df2c21530a1d`. Поэтому `Status: approved`
одобряет только план. Runtime/test changes, branch, commit, push, PR, merge,
release и deployment остаются запрещены до подтверждённого merge CB-70,
повторного rebase/remap актуального `origin/main` и снятия gate Оркестратором.

По условиям blocked phase тесты не запускались; выполнялась только read-only
проверка источников и этого plan artifact.

## Остаточная неопределённость

Фактические shared web/static owners после merge CB-70, формат actor-native
receipt outcome, конкурентная PostgreSQL сериализация и соблюдение diff ceiling
должны быть подтверждены remap, targeted tests, implementation report и
независимым final review.
