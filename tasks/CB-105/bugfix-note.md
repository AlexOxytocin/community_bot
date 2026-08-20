# CB-105 — пакет багфиксов новой волны

## Блок 1 — материалы формы задания

**Симптом:** отдельное поле «Ссылка» дублирует «Материалы», а пустые материалы
отклоняются общим domain validator до preview.

**Причина:** web-форма сериализует два UI-поля в `materials`, а
`validate_freeform_materials()` делегирует пустой объект валидатору обязательных
template materials.

**Правка:** удалить `material_url` из формы и payload; принимать `{}` только в
free-form owner; сохранить чтение legacy `text|url`; синхронизировать `*` и
native `required` с фактическими обязательными полями.

**Проверка:** `3 passed` в combined domain/browser/API run: native required
boundary, отсутствие URL-control, пустой `materials`, legacy URL read и
save → preview → publish. `Ruff`, `ruff format`, `ty`, `node --check` и
`git diff --check` прошли. Profile/API/CSS delta относительно `origin/main`
отсутствует.

**Риск:** template materials и проверка URL остаются без изменений. Новые
schema, dependency, framework, service или state owner не добавлены.
