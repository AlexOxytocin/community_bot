# CB-28 — целевая проверка

1. Active administrator получает главное меню с кнопкой `Администрирование`.
2. Нажатие текста этой кнопки возвращает inline-пункт `Заявки`.
3. Нажатие callback из ответа возвращает submitted-карточку с callback
   `registration:approve:<member_id>`.
4. Нажатие полученного callback и exact replay дают одного active member, один
   starting grant и один outcome.
5. Member/moderator не могут выполнить административные действия.
6. `tests/integration/test_navigation.py`, Ruff и ty проходят без skip.
