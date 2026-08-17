# ADR-0012 — Python-скрипты эксплуатации и деплой из GitHub ref

**Статус:** Частично заменено ADR-0016; Python backup/restore contract сохранён

**Дата:** 2026-08-14

**Уточнено:** 2026-08-14. Python остаётся стандартом для backup, restore drill и
ручного Git-ref deploy. Узкая root-owned граница автоматического release использует
два shell-скрипта, а штатный production deploy выполняется по immutable GHCR digest
согласно ADR-0011.

## Контекст

ADR-0009 закрепил self-hosted runtime через Docker Compose и image-backed
процессы `bot`, `worker` и `migrate`. Практический deploy из Windows PowerShell
показал повторяющуюся операционную проблему: remote shell-команды чувствительны
к quoting и интерполяции `$...`, а локальный archive/image путь создаёт лишнюю
ручную поверхность.

## Решение

1. Эксплуатационные и вспомогательные операции backup, restore drill и ручного
   deploy реализуются на Python.
2. Резервный ручной deploy пилота может выполняться на сервере через
   `python3 ops/deploy_from_git.py REPOSITORY REF`. Скрипт получает GitHub ref,
   копирует в staging только production-пути, исключает `.env`, `.git`, `tests`,
   `config/testing`, cache и bytecode, собирает локальный `linux/arm64` Docker
   image и запускает `python3 ops/deploy_self_hosted.py sha256:...`.
3. Низкоуровневый `deploy_self_hosted.py IMAGE_REFERENCE` сохраняет прежний
   контракт Compose: PostgreSQL, migration gate, product config bootstrap,
   worker readiness, bot readiness и запись `current-image`/`previous-image`.
4. Backup и restore drill выполняются Python-скриптами
   `backup_postgres.py` и `restore_drill.py`; systemd вызывает Python напрямую.
5. Исключение составляют `github_deploy_entrypoint.sh` и `deploy_self_hosted.sh`:
   это минимальная root-owned граница защищённого GitHub release, зафиксированная
   ADR-0011 и проверяемая отдельными parser/sequence/runtime тестами.

## Последствия

- Windows PowerShell больше не участвует в построении remote shell-скриптов для
  обычного deploy.
- Runtime остаётся image-backed: простое копирование файлов на сервер не меняет
  работающий бот до сборки нового image и перезапуска Compose.
- GHCR release artifact остаётся допустимым источником immutable image для
  rollback или отдельного CI-релиза, но быстрый pilot deploy идёт из GitHub ref
  на сервере.
- Операционные тесты проверяют Python entrypoints, узкий список допустимых shell
  wrappers и сохранение порядка `migration → worker → bot`.

## Связанные материалы

- [ADR-0009](0009-self-hosted-pilot-runtime.md)
- [ADR-0011](0011-protected-single-ci-release.md)
- [Заменяющее решение ADR-0016](0016-mini-app-only-runtime.md)
- [Технологический стек](../mvp/TECH_STACK.md)
