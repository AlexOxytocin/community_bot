# CB-106 — план удаления legacy-полей из активного профиля Mini App

Уровень: fast lane `1B` с дополнительной owner-requested независимой проверкой плана.

## Граница задачи

Из активного профиля Mini App удаляются только `availability`, пользовательский
`timezone`, `current_goal` и `help_categories`. Это означает отсутствие полей в
own/public web DTO, editable PUT allowlist, клиентском состоянии и всех
достижимых profile/member render branches.

Существующее поле `skill_tags` и весь его API/UI/storage contract сохраняются
без изменений. `help_categories_json` не переименовывается и не
переосмысливается как skills. Исторические колонки остаются без migration.

`MemberModel.timezone`, registration city inference и notification delivery
остаются внутренними владельцами timezone: `PostgresNotificationQueue`
передаёт это значение в `DeliveryWindow.schedule(timezone_name=...)`.

## Минимальная реализация после отдельного owner freeze

1. В `src/community_bot/transport/static/app.js` удалить четыре legacy rows из
   own-profile renderer, `help_categories`/прочие legacy values из public member
   detail и fallback `member.availability` из participant metadata. Сохранить
   существующую строку/редактор/рендереры «Навыки» без redesign.
2. В `src/community_bot/transport/web.py` удалить legacy keys из `MeDto`,
   `MemberDto` и их mappers. Сузить только web request model поля `field` до
   закрытого allowlist `display_name | city | short_bio | skill_tags`, затем
   преобразовать принятое значение в существующий `ProfileField` перед вызовом
   `RegistrationService.update_own_profile_field`. Это даёт 422 для legacy PUT,
   не меняя registration/domain enum.
3. Сохранить внутреннюю registration projection `ProfileData`/`ProfileSnapshot`
   без изменений: она остаётся доказательством чтения historical registration
   values и не сериализуется в активный web DTO после шага 2.
4. В `src/community_bot/application/reputation.py` и
   `src/community_bot/infrastructure/db/reputation.py` убрать
   `availability/current_goal/help_categories` из public `SafeProfile` и mapper.
   `timezone` уже не входит в public `SafeProfile`; `skill_tags` остаётся.
5. Не изменять модели, migrations, notification/outbox, registration flow,
   `ProfileField`, `skill_tags` normalization/storage, CSS/layout и зависимости.

## Проверка

- Расширить существующий API-сценарий в
  `tests/integration/test_web_api.py`: `GET /api/v1/me` и member DTO не имеют
  legacy keys; PUT каждого из четырёх legacy fields возвращает 422; PUT
  поддерживаемого соседнего поля остаётся успешным; persisted internal timezone
  не меняется. Существующие skills assertions не переписывать и не расширять.
- Обновить существующий profile oracle в `tests/browser/test_mini_app.py`:
  fixture намеренно содержит legacy keys, но labels/values/edit controls не
  появляются в DOM/a11y/focus; существующие assertions остальных полей, включая
  «Навыки», сохраняются без новой skills-функциональности. Не добавлять test
  file и не расширять geometry/UI scope.
- Обновить только механически затронутые DTO fixtures в существующих tests.
- Выполнить bounded source/static oracle: в reachable profile/member branches
  `app.js` нет `help_categories`, `current_goal`, `availability`, пользовательской
  строки «Часовой пояс» и legacy editor entries; в web DTO/request serialization
  нет четырёх legacy contract keys. Internal timezone consumers не входят в
  этот zero-occurrence oracle.
- После реализации: targeted API/browser, Ruff, ty, diff/secret checks,
  Ponytail deletion/reuse audit и короткий независимый diff verdict. Full local
  regression не запускать.

## API-совместимость

Изменение намеренно breaking для удаляемой legacy surface:

- `GET /api/v1/me` перестаёт возвращать четыре keys;
- `GET /api/v1/members` и `GET /api/v1/members/{id}` перестают возвращать
  `availability`, `current_goal`, `help_categories` (`timezone` там и сейчас не
  публикуется);
- `PUT /api/v1/me/profile` для четырёх legacy field names вместо прежнего
  принятия возвращает fail-closed 422.

Persisted data не удаляются. Старый frontend bundle при попытке legacy PUT
получит 422 до reload; immutable release связывает актуальные client/server
assets. `skill_tags` response/update contract не меняется. Notification delivery
не меняется, потому что читает `MemberModel.timezone` напрямую.

## Предложенный runtime diff

- `src/community_bot/transport/static/app.js`
- `src/community_bot/transport/web.py`
- `src/community_bot/application/reputation.py`
- `src/community_bot/infrastructure/db/reputation.py`

Новые runtime files, abstractions, dependencies, schemas и migrations: `0`.
