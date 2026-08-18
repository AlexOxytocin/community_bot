# CB-72 — Compact bugfix note

## Симптом

Публичный `https://allo.godmodetools.com/readyz` возвращает landing HTML, хотя
`/readyz` внутри активного web container возвращает authoritative readiness
JSON со статусом `200`.

## Причина

В production nginx server для `allo.godmodetools.com` отсутствует exact
location `/readyz`. Запрос попадает в общий `location /` с `try_files`.
До изменения live-файл `/opt/app/nginx/conf.d/default.conf` имеет SHA-256
`f8c7de1d057a61756866e689768242d10f98871f2073b241bfe654146ed2847c` и
публикует только `/mini-app`, `/mini-assets/` и `/api/v1/` к существующему
upstream `community-mini-app-core-web-1:8000`.

## Правка

Добавить в существующий server один `location = /readyz`, проксирующий тот же
path к тому же web upstream с уже используемыми proxy headers. DNS, TLS,
Compose, application runtime, deploy framework и остальные routes не менять.

Перед правкой сохранить exact bytes в
`/opt/app/nginx/conf.d/default.conf.cb-72.rollback`. Rollback: атомарно вернуть
эту копию на место, выполнить `docker exec nginx nginx -t` и
`docker exec nginx nginx -s reload`.

## Проверка

- Rollback `/opt/app/nginx/conf.d/default.conf.cb-72.rollback` сохранён с
  исходным SHA-256
  `f8c7de1d057a61756866e689768242d10f98871f2073b241bfe654146ed2847c`.
- Активный config после правки имеет SHA-256
  `1973f2a82bdad21737daff0cfe4ec1eb9bc0857f8bd2272298a829f34521fa8f`.
- `docker exec nginx nginx -t` — successful; reload — successful.
- Public `/readyz` — `200 application/json`, `code=ready`,
  `healthy/database/migration/product_config/heartbeat=true`.
- Regression smoke: `/mini-app` — `200`; versioned
  `/mini-assets/styles.css?release=4af786d…` — `200`; unauthenticated
  `/api/v1/me` — `401`, `code=unauthorized`.
- Short diff review должен подтвердить, что tracked diff содержит только этот
  compact note, а production diff — только exact location.

## Риск

Уровень `1B`. Риск ограничен ошибкой nginx syntax или неверным upstream path;
его снижают exact backup, `nginx -t` до reload, проверка текущего внутреннего
readiness и немедленный public smoke. Если потребуется менять что-либо кроме
одного location, работа останавливается как blocker.

## Отклонение процесса

- **Ошибка:** production nginx был изменён после создания branch и compact
  note, но до обязательных commit, push, PR, CI и merge.
- **Эффект:** production defect исправлен до reviewed merge; поэтому branch/PR
  route нельзя считать полностью соблюдённым, даже при green smoke.
- **Причина:** исполнитель ошибочно отделил host-only config mutation от
  обязательной последовательности task branch и воспринял `nginx -t` как
  достаточный pre-mutation gate.
- **Коррекция:** новые production mutations заморожены. Сначала завершаются
  independent diff review, commit, push, PR, CI и merge; после merge выполняется
  только read-only public re-smoke. Если review или CI не green, применяется
  сохранённый exact rollback и повторяются `nginx -t` и reload.
