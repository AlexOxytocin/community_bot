# CB-56 — исходный контекст Pareto-плана

## Статус снимка

- Дата проверки: 2026-08-18, часовой пояс `America/Buenos_Aires`.
- Процесс: уровень 3; planning-only, без runtime, ops, Jira writes, SSH,
  deployment, server и Telegram действий.
- Jira прочитана через Atlassian Rovo MCP только для чтения.
- Фактический `origin/main` и detached `HEAD`:
  `7f2d14ef12c569e6e84daab49be2155a43be5657`, merge PR #68 из
  `task/CB-55`.
- Рабочая ветка, commit, push и PR для CB-56 не создавались.

## Jira snapshot

### CB-56

- Статус: `К выполнению`; resolution отсутствует.
- Название: «Развернуть полный Mini App по HTTPS с безопасным cutover».
- Текущая формулировка смешивает четыре независимых результата: HTTPS и
  readiness, immutable image/host package, compact DB import/cutover и
  production/live acceptance.
- Jira REST хранит обе связи в форме `outwardIssue`: при чтении CB-56 это
  `outwardIssue=CB-52`, а при чтении CB-57 — `outwardIssue=CB-56`. Текущая
  задача в обоих случаях находится на inward-стороне с фразой
  `is blocked by`. Поэтому причинная последовательность, согласованная с
  descriptions и roadmap: **CB-52 -> CB-56 -> CB-57**. CB-53, CB-54 и CB-55
  также фактически завершены; последний merge — PR #68.
- Доступные переходы на снимке: `К выполнению`, `В работе`, `На проверке`,
  `Готово`. Переходов не выполнялось.

### Комментарий 10189 — handoff из CB-60

Комментарий находится в CB-56 и фиксирует обнаруженный в CB-60 drift:

- image-only release менял runtime digest, но не синхронизировал
  `/opt/community-bot/current`;
- будущий public Release 2 должен иметь deterministic host-package artifact
  exact merge commit, fail-closed пару commit + image digest + host-package
  digest, pre-mutation проверки ownership/mode/symlink/traversal и согласованный
  image/package rollback;
- расширение forced-command boundary требует отдельного security/ADR review.

Этот handoff обязателен для направления B, но сам по себе не доказывает, что
исторический R1 deploy contract существует в текущем дереве.

### CB-60

- Статус: `Готово`.
- Исправляла ложный readiness и host recovery drift кандидата Release 1.
- Её production contract относится к удалённой R1 topology и не может быть
  автоматически перенесён в Release 2.

### CB-64

- Статус: `Готово`, но результат задачи — принятый ADR-0017, parity map и план
  будущего compact refactor/import, а не реализованная compact schema.
- `tasks/CB-64/plan.md` планировал import внутри CB-51 и compact cutover в
  CB-56, однако фактические CB-51—CB-55 были выполнены поверх сохранённого
  backend без schema consolidation.
- Следовательно, compact migration не является фактическим precondition запуска
  текущего reviewed Mini App. Если её всё-таки выбирать, это отдельный
  destructive/data-sensitive результат с собственной приёмкой.

### CB-57

- Статус: `К выполнению`.
- Область: полная browser/integration/live acceptance уже развёрнутого reviewed
  commit.
- Это направление D; оно зависит от deployment и не входит в planning-only A1.

## Канонические ограничения

- `docs/release-2/README.md`: Release 2 — Mini App поверх существующего
  backend; новый deployment нельзя объявлять готовым без PostgreSQL, migration
  и restore доказательств.
- ADR-0016: R1 bot/release topology удалена; production deployment заново
  определяется в CB-56.
- ADR-0017: compact import безопасен только в отдельную DB после inventory,
  backup/restore и reconciliation; это условие применяется при выборе compact
  migration, а не к любому web deployment существующей schema.
- ADR-0009 и ADR-0012 сохраняют PostgreSQL data-safety и Python backup/restore,
  но их bot/deploy части частично заменены ADR-0016.
- ADR-0011 заменён для Release 2. Его fail-closed reviewed-tree и immutable
  digest свойства остаются полезными требованиями, но старый workflow не
  является текущей реализацией.
- Запрещены Kubernetes, Redis, новый broker/queue, proxy platform, hosted
  service, новая secret mechanism, generic deployment framework и DB
  migration/import без доказанной необходимости выбранного slice.

## Фактическая release topology текущего main

### Что уже существует

- `src/community_bot/transport/web.py::create_web_app` обслуживает `/`,
  `/mini-assets` и `/api/v1`; `MINI_APP_ORIGIN` валидируется как exact HTTPS
  origin, auth proof и authority проверяются server-side.
- `src/community_bot/worker/entrypoint.py` содержит существующий deadline/outbox
  loop; PostgreSQL outbox и worker не требуют Redis или новой очереди.
- `ops/backup_postgres.py`, `ops/restore_drill.py` и `ops/_runtime.py` сохраняют
  digest-only image identity, root-owned env `0600`, custom `pg_dump`, isolated
  restore, exact Alembic head и ledger reconciliation.
- `.github/workflows/ci.yml` выполняет PR quality/browser/PostgreSQL gates и
  сохраняет `verified-merge-tree` artifact с PR/base/head/tree/run identity.

### Чего нет

- В `pyproject.toml` нет `community-web`; image по умолчанию запускает только
  `community-worker`.
- В `compose.production.yaml` есть только `postgres`, `migrate`, `worker`; web
  service и HTTP readiness отсутствуют.
- В текущем `.github/workflows` нет release workflow: image не собирается и не
  публикуется после merge.
- В текущем `ops/` нет deploy scripts, systemd units и двух shell wrappers.
  CB-62 осознанно удалила их как R1 topology.
- `.github/CODEOWNERS` всё ещё ссылается на удалённые privileged paths; это
  stale policy residue, а не работающий deploy contract.

### Исторические два shell wrappers

Из parent commit до CB-62 полностью прочитаны
`ops/github_deploy_entrypoint.sh` и `ops/deploy_self_hosted.sh`, а также старые
`release.yml`, Python deploy и provenance verifier.

- Entrypoint проверял точную forced command, root-owned `0700` directories,
  symlink/mode/owner, `flock` и monotonic run marker.
- Deploy wrapper принимал только digest/image ID, выполнял
  `postgres -> migrate -> config -> worker -> bot`, записывал
  `current-image`/`previous-image`.
- Контракт жёстко содержит legacy owner `alexgoodman53` и bot process, поэтому
  копирование в текущий main запрещено. Текущий владелец GitHub —
  `AlexOxytocin`.

## Конкретный readiness defect текущего main

- Packaged Alembic head после CB-52 — `0021`.
- `community-worker` продолжает писать в heartbeat строку `0020`.
- `readiness_report` читает только heartbeat `observed_at` и `release`, но не
  сравнивает `process_heartbeats.migration_revision` с packaged head.
- Поэтому существующий health contract способен принять worker с неверной
  migration identity. Это causal blocker A1, а не повод добавлять DB import.

## Разделение A/B/C/D

| Направление | Самостоятельный результат | Решение этого плана |
| --- | --- | --- |
| A | Текущий reviewed image способен запустить Mini App web process и пройти честный local/Compose readiness | Выбрать A1 |
| B | Reviewed merge commit, published image digest и root-owned host package образуют fail-closed immutable tuple | Отложить отдельным security/ADR slice |
| C | Legacy DB импортирована в отдельную compact DB с reconciliation и новой rollback boundary | Отложить до отдельного owner решения |
| D | Public HTTPS deployment и live Mini App acceptance на реальном target | Отложить до owner go-live gate |

## Независимые read-only аудиты

### Release topology/evidence map

Аудит подтвердил: единственный минимальный observable gap — отсутствие web
entrypoint/service/readiness при уже реализованном FastAPI/static UI. Старые
release wrappers удалены и не являются текущей основой. Compact import не
причинно связан с запуском существующей schema.

### Security/Ponytail scope challenge

Аудит подтвердил тот же A1 и потребовал не восстанавливать R1 scripts. Backup и
restore остаются future production gate, но их изменение, mutation freeze и
cutover не нужны в diff A1. Ponytail-итог:

`delete:` DB import/cutover, mutation freeze, host-package framework и live
deployment из следующего slice. `replacement:` ничего; добавить только web
runtime/readiness поверх существующих image, Compose, DB и worker contracts.

## Неизвестное внешнее состояние

Без чтения secrets/env/server state невозможно и не нужно определять:

- конкретные DNS/domain и существующий HTTPS edge;
- архитектуру/доступность production host;
- способ публикации нового image и актуальный host-package installation path;
- допустимость изменения forced-command boundary;
- содержимое production DB.

Эти неизвестные не блокируют план A1, но блокируют направления B, C и D до
явного решения владельца и отдельного preflight.

## Contract mismatch текущей Jira

Текущие цель и acceptance CB-56 требуют HTTPS deployment, import, restore и
две rollback drills. Они не соответствуют A1. Поэтому A1 нельзя реализовывать
под существующим Jira contract даже после простого transition.

Рекомендуемое разрешение владельца: явно разрешить Jira write, сузить CB-56 до
A1 и вынести B в отдельную связанную задачу; C оставить отложенным compact-DB
решением, D оставить CB-57. Альтернатива — создать отдельную связанную задачу
A1 и не менять CB-56. До выбора одного из вариантов code/runtime запрещены.
