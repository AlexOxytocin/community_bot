# Community Mini App

Продукт закрытого сообщества взаимной помощи: участники создают и выполняют задания, рассчитываются внутренними кредитами, получают опыт и формируют репутацию. Единственный пользовательский интерфейс нового направления — Telegram Mini App.

## Текущее состояние

Сохранён и покрыт тестами backend модульного монолита:

- роли, статусы, регистрация и серверная авторизация;
- каталог и жизненный цикл заданий;
- назначения, результаты, споры и модерация;
- append-only ledger кредитов и опыта;
- карма, надёжность и административный аудит;
- PostgreSQL-дедупликация, transactional outbox и worker;
- Alembic-миграции, backup и restore drill.

Старый Telegram chat UI, long-polling runtime и pilot/release-контур удалены. Telegram используется для запуска Mini App, проверки auth proof и исходящих уведомлений. Минимальный opt-in webhook добавляет `/start`, общее меню подписок и публикации настроенной темы; управление заданиями остаётся в Mini App. Настройка ingress и правила выпуска описаны в [ADR 0022](docs/adr/0022-minimal-telegram-ingress.md).

## Окружение

Требуются uv 0.12.3, Python 3.13 и Docker Compose с PostgreSQL 18.

```powershell
uv python install 3.13
uv sync --locked --all-groups
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run pytest
```

Обычный локальный цикл собран в одну команду:

```powershell
.\scripts\dev.ps1
```

Описание режимов проверки находится в [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md),
актуальный индекс документации — в [docs/README.md](docs/README.md).

Безопасная проверка worker не обращается к Telegram:

```powershell
uv run community-worker --check
```

Для реальной отправки уведомлений worker требует `BOT_TOKEN`, актуальную PostgreSQL-схему и остальные значения из `.env.example`. Секреты не хранятся в Git, Jira или логах.

## Проверки

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests ops
uv run pytest
```

Integration-тесты используют реальный PostgreSQL: заданный `DATABASE_URL` либо Testcontainers.

Для узкой проверки можно использовать `scripts/check.ps1` с путями pytest;
полный gate запускается флагом `-Full` только когда этого требует риск.

## Архитектура

- `domain` — бизнес-инварианты без framework-зависимостей;
- `application` — use cases, права, идемпотентность и транзакционные границы;
- `infrastructure` — PostgreSQL, outbox, observability и Telegram sender;
- `worker` — дедлайны и доставка уведомлений;
- будущий HTTP transport вызывает те же application use cases.

Каноническое направление зафиксировано в [ADR-0016](docs/adr/0016-mini-app-only-runtime.md). Требования находятся в [docs/mvp](docs/mvp/README.md), границы Release 2 — в [docs/release-2](docs/release-2/README.md).
