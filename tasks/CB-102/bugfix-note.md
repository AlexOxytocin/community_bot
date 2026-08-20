# CB-102 — compact bugfix note

## Симптом

Catalog открывал существующие фильтры только через обычный текст количества, а
видимый H1/count row и detail-like task cards оставляли в мобильном viewport
только одну крупную карточку.

## Причина

`showCatalog()` использовал count как button trigger и помещал create action в
отдельный header. Общие card padding/gaps и неограниченные list-copy строки не
были адаптированы для компактного Catalog list.

## Правка

Существующие `catalogFilters` и `showCatalogFilters()` переиспользованы без
backend/API изменений. Catalog теперь начинается с одной row «Фильтры»/«+ Создать»;
filter button имеет локальный sliders SVG и badge числа активных criteria. H1 и
total count сохранены только для accessibility. Scoped CSS уплотняет cards,
ограничивает title/description двумя строками и оставляет chips/metadata одной
строкой. Старый count-trigger и его CSS удалены.

## Проверка

- focused authenticated browser oracle: Filters/Create видимы, drawer и active
  badge работают, detail/Back сохраняет отфильтрованный Catalog state;
- exact density: 4 полные cards в 375×812, 5 в 430×932, horizontal overflow 0;
- видимые H1/count отсутствуют; полный browser suite до последнего narrowing —
  18 passed; финальный focused browser и static gates выполняются перед review;
- screenshots обоих viewport визуально сопоставлены с owner references.

## Риск

Низкий, ADR-0010 fast lane 1B: production diff ограничен существующими
`app.js`/`styles.css`; filter engine, API, domain, create/detail/history owners и
legacy Telegram UI не меняются. Ponytail: `Lean already. Ship.`
