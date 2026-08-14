# CB-38 - финальная проверка

## Попытка 1

**Status: changes_requested**

Замечания: изменяемый PR workflow не имел независимой privileged boundary; GitHub
protection еще не была включена; runtime identity не отличала повторный запуск digest;
marker/flock проверялись преимущественно статически; provenance verifier не входил в
полный type gate; standing intent сохранял два противоречия.

Отдельное замечание о якобы действующем запрете shell-скриптов отклонено как фактически
неверное: такого правила нет в `AGENTS.md`, канонических guardrails или agent workflow,
а `ops/deploy_self_hosted.sh` является существующим утвержденным эксплуатационным
контрактом. Переписывать рабочий deployment слой без требования и ADR не следует.

## Исправления после попытки 1

- Deploy job привязан к Environment `production`; required reviewer и запрет admin bypass
  настроены вне изменяемого PR workflow. Privileged secrets будут environment-scoped.
- `main` реально защищена strict App-bound checks, обязательным PR, enforce admins,
  conversation resolution и запретом force push/deletion; squash/rebase выключены.
- Runtime identity включает digest и run number/attempt; post-recreate timestamp имеет
  наносекундную точность.
- Linux behavior test подтвердил marker update, разрешение нового attempt и отклонение
  duplicate/stale пар; добавлены newline, `&&` и command-substitution cases.
- `ops/verify_release_provenance.py` типизирован и включен в CI `ty` command.
- Противоречия standing intent в `agents/workflow.yaml` и ADR-0004 устранены; термин
  `run ID` заменен точной парой run number/attempt.

## Итоговый вердикт

## Попытка 2

**Status: changes_requested**

Подтверждены все исправления первой попытки. Найден один production blocker: фактический
`/opt/community-bot/current/ops/deploy_self_hosted.sh` имел mode `0777`, поэтому его
выполнение forced-command процессом от root создавало privilege-escalation boundary.
Также исправлено устаревшее предложение о незакрытой branch protection в отчете.

## Консолидированное исправление после эскалации

- Trusted deploy runner перенесен в `/opt/community-bot/shared/bin/deploy_self_hosted.sh`.
- Entrypoint требует `root:root 0700`, regular/non-symlink для runner и `root:root 0700`
  для `shared`/`shared/bin` перед выполнением.
- Linux behavior test дополнен отказом при mode `0777`.
- Runbook фиксирует установку обоих server-owned scripts и точные права.

Следующая независимая проверка является последней после эскалации. Новый обязательный
finding останавливает реализацию для решения владельца.

## Проверка после эскалации

**Status: approved**

Обязательных дефектов не обнаружено. Подтверждены root-only trusted runner, проверки
ownership/mode/symlink, Linux behavior при штатной и stale/duplicate/`0777` ветках,
исправленный отчет и отсутствие новых регрессий в полном staged diff.

Verdict подтверждает готовность реализации к PR. Production acceptance остается открытой
до PR CI, установки key/scripts/secrets, release, deploy и живой Telegram-проверки.
