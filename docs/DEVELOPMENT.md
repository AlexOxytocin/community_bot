# Локальная разработка

## Первый запуск

Требуются uv 0.12.3, Python 3.13 и Docker Compose.

```powershell
.\scripts\dev.ps1
```

Скрипт синхронизирует зависимости, запускает PostgreSQL, применяет Alembic и
запускает `community-web` на `http://localhost:8000`. Повторный запуск можно
ускорить флагом `-SkipSync`.

## Проверка

Для обычной правки передаются конкретные pytest-файлы:

```powershell
.\scripts\check.ps1 tests/unit/test_web_auth.py
```

Без аргументов выполняются быстрые unit и smoke tests. Полный локальный gate
запускается только по необходимости:

```powershell
.\scripts\check.ps1 -Full
```

Browser и PostgreSQL integration tests добавляются, когда изменение затрагивает
соответствующую границу. Coverage-порог применяется только при явном полном
coverage-прогоне.

## База данных

- Новая schema-правка получает новую Alembic-миграцию; историю не переписывать.
- На локальной базе допустим обычный `alembic upgrade head`.
- Миграция реальных данных всегда относится к уровню `release` и требует backup
  и rollback-плана.

## Граница с MySite

Bot backend, Mini App frontend и миграции развиваются в этом репозитории как
один продукт. `MySite` остаётся отдельным публичным/маркетинговым сайтом и может
содержать ссылку или маршрутизацию `app.godmodetools.com`, но его тяжёлый
визуальный и release-контур не является gate локальной разработки Mini App.
