# CB-26 — план проверки

1. `Москва` → `Europe/Moscow`, следующий шаг `short_bio`.
2. `Буэнос-Айрес` и `Buenos Aires` →
   `America/Argentina/Buenos_Aires`, следующий шаг `short_bio`.
3. Существующий draft на `timezone` принимает `Buenos Aires`.
4. Exact `Europe/Moscow` продолжает приниматься.
5. Неизвестный город остаётся на ручном timezone step с понятным prompt.
6. Неоднозначные timezone aliases не выбираются молча даже при одинаковых
   offsets на контрольных датах (`Eastern`); разные offsets также дают fallback.
7. Exact replay не применяет автозаполнение дважды; stale answer не загрязняет
   следующий шаг.
8. Production-composed Telegram E2E завершает регистрацию без технического
   timezone identifier.
9. Targeted pytest без skip/deselect, Ruff, ty и diff-check успешны.
