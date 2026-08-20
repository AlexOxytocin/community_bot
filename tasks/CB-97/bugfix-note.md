# CB-97 — compact visual bugfix note

**Симптом:** После bootstrap реальные connected roots показывали legacy hero и сырые карточки, а не утверждённый compact UI.

**Причина:** Presentation renderer и production renderer были двумя разными UI-путями; review проверил первый, но Mini App после API-загрузки использовал второй.

**Правка:** Удалён общий hero и параллельный presentation renderer. Все connected экраны T/P/M/S переведены на единый compact shell Concept 05 с существующими API-проекциями и context-навигацией. Для администратора сохранены пять root tabs: Каталог, Мои, Участники, Профиль, Модерация.

**Проверка:** Settled authenticated browser DOM и 72 screenshots для 36 reachable ID в `375×812` и `430×932`; payloads проходят `MeDto`/`TaskDto`/`MemberDto`; browser `15 passed`; полный suite `595 passed`, coverage `82.33%`; Node, Ruff, Ty и deterministic absence gates green.

**Риск:** Только frontend-разметка и стили. API, домен, данные, права и мутации не меняются.
