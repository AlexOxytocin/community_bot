# CB-13 — контекст источников плана

## Jira

- История: CB-13 «Реализовать модерацию, споры и защиту от злоупотреблений».
- Статус на старте: `К выполнению`; родитель: CB-2.
- Входящие блокеры CB-11 и CB-12 имеют статус `Готово`.
- CB-13 блокирует CB-15.
- Семь критериев Jira требуют заморозку спорного расчёта, детерминированные
  resolution-коды, конфликт интересов, обратимые санкции, отсутствие
  автоматических наказаний от кармы, воспроизводимую апелляцию и integration
  проверки full/partial/refund/fraud.

## Канонические решения

- `08_MODERATION_AND_ABUSE.md`: лестница санкций, human-in-the-loop, спор,
  конфликт интересов, одна апелляция за семь дней, interaction alerts и karma
  risk signals.
- D-014/D-015: отдельное окно спора после reject, `ceil(50%)` partial payment,
  замороженный reserve/system issuance до финала.
- D-016/D-017: четвёртое interaction за rolling 7 days создаёт alert без
  блокировки; penalty возможен только после `penalty_recommended`, атомарен и не
  затрагивает опыт или резерв.
- D-020/D-021: karma eligibility и raw privacy уже реализованы CB-12; карма сама
  не является санкцией.
- CB-11 уже хранит assignment disputes, result versions, reliability history и
  ledger correlation; CB-12 добавила permission foundation и raw karma history.

## Границы

В CB-13 входят dispute resolution/appeal, санкции и их отмена, interaction
alerts/penalties, karma/assignment risk signals, Telegram moderation queue,
миграция, targeted PostgreSQL tests и документация. Фоновая доставка/expiry
scheduler остаётся CB-15, полная регрессия готового MVP — CB-16.

Структура остаётся внутри ADR-0005/0006 и модульного монолита. Новый ADR не
нужен. Три продуктовые политики из `needs-info.md` подтверждены владельцем
11 августа 2026 года и зафиксированы принятой D-023.
