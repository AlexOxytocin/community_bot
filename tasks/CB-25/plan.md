# CB-25 — план восстановления редактирования карточки

## Цель

Сделать редактирование собственной карточки достижимым из `/profile` и кнопки
`Моя карточка`, не ломая просмотр доступного чужого профиля по UUID.

## Изменения

1. Вынести presentation собственной карточки и восемь edit actions в один
   transport-модуль без сервисной логики.
2. Использовать этот presentation в registration handler `/profile` и в
   navigation handler кнопки `Моя карточка`.
3. Ограничить reputation route формой `/profile <member_uuid>`; exact `/profile`
   должен обслуживаться только registration router.
4. Сохранить существующий `profile:edit:<field>` flow: callback выбирает поле,
   следующий текст сохраняет только его.
5. Добавить production-composed Dispatcher test для active administrator и
   active member, включая восемь кнопок и фактическое изменение одного поля.

## Не входит

- изменение таблиц, прав, профиля чужого участника или registration flow;
- новый дизайн карточки;
- полная регрессия MVP.

## Проверка

- targeted profile/navigation/registration tests;
- Ruff format/check и ty;
- независимый final review после полного готового diff.
