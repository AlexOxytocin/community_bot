# Отчёт о реализации CB-31

## Результат

Первый bootstrap administrator по-прежнему создаётся с детерминированным
нейтральным профилем. Для повреждённого или нежелательного placeholder добавлен
штатный repair entrypoint:

```text
printf '%s\n%s\n' "$TELEGRAM_ID" "$DISPLAY_NAME" |
  community-repair-bootstrap-admin-profile
```

Repair использует существующий bootstrap advisory gate, разрешён только для
единственного active administrator с append-only bootstrap provenance и меняет
только `display_name`. Имя проходит тот же domain validator, что обычное
редактирование профиля. При точном повторе SQL и audit не дублируются.

Audit содержит только `display_name_repaired=true` и безопасную reason; имя и
Telegram ID не попадают в process argv, Sentry `ArgvIntegration`, payload или
runtime log.

## Критерии Jira

| Критерий | Результат |
|---|---|
| UTF-8-safe имя | Русское имя нормализуется и сохраняется в PostgreSQL без искажения. |
| Детерминированный onboarding | First install сохраняет безопасные `Administrator`, `UTC` и пустые необязательные поля. |
| Идемпотентный repair | Первый вызов меняет имя и пишет один audit; повтор возвращает `already_applied`. |
| User-facing smoke | Production Dispatcher показывает исправленное имя в карточке, участниках и leaderboard. |
| Privacy | CLI output и audit payload не содержат Telegram ID или display name. |

## Проверки

- Targeted: `16 passed` (`11` PostgreSQL + `5` privacy/observability), без
  skip/deselect; дополнительно покрыты conflict, concurrent bootstrap, fault
  rollback и retry.
- Ruff format/check и `ty`: успешно.
- `uv build`: sdist и wheel собраны.
- Bootstrap, repair, bot и worker entrypoints: успешно.
- `git diff --check`: успешно.

Полная регрессия не запускалась: единый повтор всех пользовательских цепочек
выполняется в CB-29 после слияния CB-30…CB-33.
