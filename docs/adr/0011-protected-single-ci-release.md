# ADR-0011 - Защищенный release после одного полного CI

**Статус:** Принято

**Дата:** 2026-08-14

## Контекст

Каждый merge сейчас запускает полный набор тестов дважды: на pull request и на `main`.
Только после второго прогона отдельный workflow собирает image, после чего deployment
запускается вручную. Для малого багфикса ожидание этой цепочки дороже реализации.

Удалить CI на `main` без компенсирующих гарантий нельзя: непроверенный push смог бы стать
release, а synthetic merge PR может отличаться от фактического merge commit. Передача
существующего пользовательского SSH key в GitHub Actions также недопустима.

## Решение

1. Полный CI выполняется только на `pull_request`.
2. После двух полных jobs итоговый `Verified merge tree` сохраняет repository, PR number,
   base/head SHA, synthetic merge SHA/tree SHA и identity CI workflow/run.
3. `main` требует pull request, актуальную базу и checks `Quality`,
   `PostgreSQL and Alembic`, `Verified merge tree`, привязанные к GitHub Actions App.
   Правила применяются к администраторам; bypass, force push и deletion запрещены.
   Разрешен только merge-commit способ слияния.
4. Release на `push main` требует ровно один merged PR с exact merge SHA и ровно один
   непросроченный provenance artifact успешного CI run этого PR/head SHA. Сохраненные
   base/head SHA должны совпасть с parents actual merge commit, а tree SHA - с его tree.
   Отсутствие, неоднозначность или любое несовпадение запрещает build.
5. После доказательства происхождения release собирает linux/arm64 image actual merge
   commit и публикует immutable digest.
6. Перед deploy workflow подтверждает, что commit все еще является текущим `main`, и
   передает отдельному job только `run_number`, `run_attempt`, `commit_sha` и image.
   Job использует защищенное GitHub Environment `production`; ручное подтверждение
   владельца является независимой границей для изменяемых PR workflow и release-кода.
7. GitHub Actions подключается пользователем `root` отдельным deploy key с
   `StrictHostKeyChecking=yes` и заранее доверенным pinned host key. Public key находится
   только в `/root/.ssh/authorized_keys` и ограничен
   `restrict,command="/opt/community-bot/shared/bin/github_deploy_entrypoint.sh"`.
8. Server-owned entrypoint имеет владельца `root:root`, mode `0700`, фиксированный PATH,
   не использует `eval` и принимает только точную команду
   `deploy <run_number> <run_attempt> <commit_sha> <expected_repository@sha256:digest>`.
9. Entrypoint использует `flock` и marker последней успешной пары
   `(GITHUB_RUN_NUMBER, GITHUB_RUN_ATTEMPT)` неизменяемого release workflow. Меньшая или
   равная пара не может заменить новый deployment.
10. Runtime identity строится как `<digest>.run<run_number>.<run_attempt>`. Deploy
    принудительно пересоздает worker и bot и фиксирует наносекундный post-recreate порог
    каждого процесса. Readiness принимает только heartbeat с этой identity и временем не
    старше порога, поэтому старый процесс или предыдущий запуск digest не закрывает gate.
11. Существующий deploy script сохраняет migration, product config, worker/bot readiness,
    current/previous image и ручной rollback.

## Постоянное намерение владельца

Прямое поручение исправить баг или реализовать задачу разрешает стандартную
недеструктивную цепочку Jira -> branch -> PR -> merge после зеленых обязательных checks
-> release -> deploy. Агент останавливается при неуспешном gate, конфликте состояния,
повышении риска, необходимости разрушительного действия или прямой команде владельца.

Это разрешение не позволяет обходить проверки, объявлять production gate закрытым без
фактического deploy и требуемой живой проверки, читать произвольные чаты, отправлять
несогласованные сообщения или автоматически переводить задачу в финальный `Done`.

## Последствия

- Полная регрессия выполняется один раз вместо двух последовательных прогонов.
- Image соответствует проверенному дереву и фактическому commit защищенного `main`.
- Рутинный release не требует ручного SSH-сеанса.
- Компрометация deploy key не дает произвольную shell-команду. Повторный deploy ограничен
  ожидаемым repository и монотонной парой GitHub run number/attempt.
- Изменение deployment package остается отдельным ручным операционным событием.

## Альтернативы

### Оставить повторный CI на `main`

Безопасно, но сохраняет основную задержку каждого release.

### Использовать существующий root SSH key

Проще, но дает CI избыточный доступ и связывает персональный ключ с automation.

### Деплоить PR image до merge

Быстрее, но production перестает однозначно соответствовать commit в `main`.

## Связанные материалы

- [ADR-0009 - Самостоятельное размещение пилота](0009-self-hosted-pilot-runtime.md)
- [ADR-0010 - Быстрый путь малых багфиксов](0010-small-bugfix-fast-lane.md)
- [Runbook пилота](../operations/PILOT_RUNBOOK.md)
- [CB-38](../../tasks/CB-38/plan.md)
