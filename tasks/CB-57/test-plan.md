# CB-57 — план ручного тестирования deployment

## Предусловия

- Plan review `Status: approved`; владелец принял ADR-0019 и все шесть go-live
  решений из `plan-source-context.md`.
- Task runtime/process diff merged с green CI; selected runtime release относится
  к новому CB-57 artifact, не release 71, и записана exact.
- Доступ root выполняющего оператора и server secrets остаются вне артефактов.
- Mutation freeze объявлена; stop/rollback commands подготовлены до mutation.
- Fresh-session oracle следует primary Telegram Mini Apps contract: official
  bridge находится в `<head>` до app scripts, а `initData` принимается только
  после server-side validation
  (https://core.telegram.org/bots/webapps#initializing-mini-apps).

## Тестовые данные

- Fresh root-only custom-format production backup mode `0600`; encryption не
  предполагается без отдельного доказанного механизма, path/content не публикуются.
- Existing safe pilot/test account только при отдельном разрешении live action.
- Для HTTP-negative checks — синтетические invalid/absent auth значения; raw
  Telegram `initData` не сохраняется.

## Сценарии

| № | Сценарий | Шаги | Ожидаемый результат | Фактический результат |
|---|---|---|---|---|
| 1 | Exact release preflight | Сверить run/artifact/manifest/image/OCI/head; выполнить pure verify | Все identities exact; mismatch останавливает работу | Не выполнялось |
| 1a | Fresh-session handshake oracle | Перехватить official script URL локальным synthetic bridge без сети; fresh context получает `/me=401`; проверить auth POST и retry; отдельно missing/invalid/existing-session paths | Raw unchanged proof body, exact content type, same-origin credentials/origin; `204`→cookie→один retry→catalog; no proof в URL/storage/console/evidence; closed paths без loop | Green: `uv run pytest tests/browser/test_mini_app.py --no-cov -q`, 4 passed; fresh/existing/missing paths проверены без внешней сети |
| 2 | Direct-activate guard | До cutover подтвердить distinct Compose projects и ожидаемый same-head/project stop без `pending` | Empty/wrong DB не активируется; runtime не меняется | Не выполнялось |
| 3 | Freeze и fresh backup | Остановить old bot/worker; сверить PG tool compatibility; restrictive umask → temp `pg_dump` → mode/size/checksum → atomic rename | Root-only regular `0600` backup green; old DB head `0020`; split-brain отсутствует | Не выполнялось |
| 4 | Restore в new volume | Поднять только new PostgreSQL; `pg_restore --no-owner --no-privileges`; сверить head, ledger и named counts | New DB эквивалентна current data на `0020`; nonzero exit blocks; old volume untouched | Не выполнялось |
| 5 | Migration `0021` | Exact image выполняет upgrade; сверить singleton head, tables/counts и `web_sessions` | Head `0021`; только новая пустая table; old data сохранены | Не выполнялось |
| 5a | Worker quiescence preflight | На весь smoke window проверить due finalizers/reminders и pending/retry/leased outbox; снять business-state fingerprint | Workload zero; иначе stop без activation | Не выполнялось |
| 6 | Manual activation readiness | Запустить activator; до stop worker проверить Compose health, `/healthz`, `/readyz`, heartbeat и no-secret response | Exact tuple ready; worker/web healthy; health/readiness 200 | Не выполнялось |
| 6a | Quiescent smoke window | Сразу остановить new worker; повторить fingerprint/outbound checks; web/PostgreSQL оставить | Только expected heartbeat изменён; business/outbox/delivery state неизменен | Не выполнялось |
| 7 | Quiescent service checks | Проверять web `/healthz`, PostgreSQL и path routing отдельно; не требовать `/readyz=200` после heartbeat TTL | Web/db/path доступны; ожидаемый stale `/readyz=503` не маскирует иной failure | Не выполнялось |
| 8 | Edge config safety | Backup config; доказать unique target `web` endpoint по Compose labels/network и internal health; подключить nginx; `nginx -t`; применить | Upstream exact/unique; только nginx изменён; unrelated services healthy | Не выполнялось |
| 9 | Landing preservation | Сравнить status/content fingerprint `/` до и после | Existing landing page не изменена | Не выполнялось |
| 10 | Path routing | Без session проверить `/mini-app`, JS/CSS/font под `/mini-assets/`, closed API under `/api/v1/` | HTTPS 200/expected 401; нет mixed content/404 routing defect | Не выполнялось |
| 10a | Runtime+edge rollback rehearsal | До auth POST закрыть edge и проверить old PostgreSQL snapshot без writers; затем stop old DB; exact staged Compose force-recreate/wait new worker/web (не same-digest activate), stop worker; повторить upstream/network/edge apply | Edge закрыт до switch; new state и path edge восстановлены exact; landing сохранён; no split brain | Не выполнялось |
| 11 | Fresh auth и read-only member slice | После rehearsal: bridge handshake → catalog → detail → assignments list/detail | Auth raw body/header/origin/credentials exact; session создана; read-only slice работает | Не выполнялось |
| 12 | Moderation boundary | Active authorized role видит read-only queue; ordinary role получает closed denial | No mutation controls/effects; permissions server-side | Не выполнялось |
| 13 | Auth/privacy negative | Без session, expired/tampered proof и direct API URL | Closed `401/403`; нет secrets/raw proof в body/log/evidence | Не выполнялось |
| 14 | Mutating accept — последний gate | После read-only checks отправить accept; old rollback закрыть при dispatch; при ambiguous outcome повторять только exact same operation key до deterministic replay/conflict | Один assignment/effect; no new key/duplicate; failure только fix-forward | Не выполнялось |
| 15 | Worker resume owner gate | После green smoke и zero-backlog применить уже выданное conditional разрешение: снять freeze, включить worker/outbound и повторить readiness без нового вопроса владельцу | Worker healthy; delivery разрешена владельцем; no unexpected backlog | Не выполнялось |
| 16 | Jira/process evidence | Записать classification/supersession, exact tuple, backup/restore/migration/readiness/smoke/rollback boundary | Доказательства полны и не содержат sensitive values | Не выполнялось |

## Stop conditions

Остановиться без продолжения при identity mismatch, backup/restore failure,
неожиданном data/count drift, нескольких Alembic heads, `pending`, unhealthy web,
необъявленном worker failure, изменении landing page, nginx config failure,
затрагивании unrelated services или утечке sensitive data. Только в объявленном
time-bounded quiescent window worker stopped и stale `/readyz=503` ожидаемы;
проверяются web/db/path отдельно. Final success и `Done` требуют gate 15:
worker resume, zero-backlog recheck, Compose green и `/readyz=200`. После новой
production mutation old `0020` snapshot больше не считать допустимым rollback.

Release 71 не разворачивать как user-testable при любых остальных green gates.
Missing bridge, более одного auth POST/retry или client-side storage/logging raw
`initData` являются blocking failure.

Old rollback запрещён с отправки первого auth POST, accept request, любого
другого mutating request, обнаруженной worker mutation или outbound attempt.
Task accept всегда последний functional gate. Edge config rollback остаётся
допустимым и обязательным при route/landing failure независимо от DB boundary.

## Очистка тестовых данных

- Не удалять old project/volume в CB-57; после green smoke снять freeze только по
  зафиксированному owner go-live outcome.
- Синтетические sessions истекают штатно; production records не удалять ради
  теста. Если accept был разрешён, его assignment является реальным effect и
  фиксируется без персональных данных.
- Temporary transferred bundle/config backups остаются root-only либо удаляются
  оператором после evidence согласно существующей retention policy.
- Initial DB dump сохраняется root-only до принятого smoke/rollback boundary,
  затем удаляется или передаётся в canonical retention только явным operator
  action; checksum/path/content в Jira не публикуются.

## Ограничения

- Full backend parity, mobile-client matrix и все будущие screens не проверяются.
- Telegram launch/click/message actions не выполняются без отдельного явного
  поручения. Public HTTP/browser smoke не даёт такое разрешение.
- Фактические результаты заполняются только после выполнения; план не является
  deployment evidence.
