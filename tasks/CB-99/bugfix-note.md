# CB-99 — первоначальная compact bugfix note

После независимой проверки задача переведена с уровня `1B` на уровень 2:
периоды меняют каноническое правило лидерборда сквозным, хотя и минимальным,
контрактом. Актуальные артефакты — `plan.md`, `implementation-report.md` и
`final-review.md`.

## Симптом

P01 и P05 используют высокие detail-card, верхняя зона P01 занимает слишком
много места, поиск отклоняет короткие запросы, периоды лидерборда не работают,
а P06 повторно загружает и показывает лидерборд.

## Причина

У списков нет собственных compact row-компонентов. Frontend P05 вызывает только
all-time endpoint, а `ReputationService` и PostgreSQL projection не принимают
период. P06 после загрузки профиля отдельно запрашивает первые три строки
лидерборда.

## Правка

- удалить leaderboard request/render из P06, сохранив profile stats;
- оформить P01 и P05 отдельными компактными строками;
- заменить label и кнопку поиска одним native search input с submit по Enter,
  без минимальной длины непустого запроса;
- провести `week|month|all` через существующий endpoint/service/projection и
  игнорировать устаревшие frontend responses.

## Проверка

- backend test различает 7/30 суток и all-time и проверяет односимвольный и
  пустой поиск;
- authenticated browser test проверяет три query period, возврат с pending на
  cached период, отсутствие секции в P06 и density 4/5 в 375×812 и 430×932;
- Ruff, type check, pytest и независимый review выполняются до PR; CI, merge и
  production smoke остаются delivery gate.

## Риск

Уровень 2: без schema/migration, новой зависимости, изменения ledger или прав
доступа. Остаточный риск — mobile density при длинных публичных строках; он
ограничен ellipsis и проверяется на двух viewport.
