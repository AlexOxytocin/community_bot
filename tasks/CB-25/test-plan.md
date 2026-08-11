# CB-25 — план проверки

1. `/profile` active administrator показывает полную собственную карточку и все
   восемь callback `profile:edit:*`.
2. `Моя карточка` active member показывает тот же presentation и те же действия.
3. После callback редактирования города следующий текст меняет только город.
4. Exact `/profile` не обрабатывается reputation router второй раз.
5. `/profile <member_uuid>` сохраняет privacy-safe просмотр доступной чужой
   карточки.
6. Pending/inactive пользователь не может открыть или изменить карточку.
7. Targeted pytest не содержит skip/deselect; Ruff и ty успешны.
