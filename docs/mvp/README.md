# Community Mini App — продуктовый контракт

Этот каталог описывает сохраняемую бизнес-модель сообщества. Интерфейсный контракт старого Telegram-бота удалён; текущий UI строится как Mini App.

## Цикл продукта

```text
регистрация → создание задания → принятие → выполнение → подтверждение
→ начисление кредитов и опыта → карма/надёжность → повторное участие
```

## Канонические документы

- [01_PRODUCT_REQUIREMENTS.md](01_PRODUCT_REQUIREMENTS.md) — продукт и границы.
- [02_DOMAIN_RULES.md](02_DOMAIN_RULES.md) — кредиты, опыт, уровни, карма и надёжность.
- [03_USER_FLOWS.md](03_USER_FLOWS.md) — UI-независимые пользовательские сценарии.
- [04_TASK_CATALOG.md](04_TASK_CATALOG.md) — категории и шаблоны заданий.
- [06_DATA_MODEL.md](06_DATA_MODEL.md) — PostgreSQL-модель и транзакции.
- [07_SECURITY_AND_PRIVACY.md](07_SECURITY_AND_PRIVACY.md) — безопасность и приватность.
- [08_MODERATION_AND_ABUSE.md](08_MODERATION_AND_ABUSE.md) — споры, санкции и аудит.
- [11_DECISIONS_AND_OPEN_QUESTIONS.md](11_DECISIONS_AND_OPEN_QUESTIONS.md) — журнал решений; R1 transport/release части заменены ADR-0016.
- [TECH_STACK.md](TECH_STACK.md) — текущий backend и целевая web-граница.

При противоречии приоритет имеют принятые ADR, затем журнал решений, требования и доменные правила.
