# CB-52 — сохранённая попытка plan review 01

Schema: `community_bot.plan_review.attempt.v1`

Status: changes_requested

## Контекст

Независимый security/architecture reviewer проверил первый полный план CB-52
на baseline `c61b0afd7cb5fa6bef315e235ba867c2959e242c`. Runtime и внешнее состояние
не изменялись.

## Обязательные замечания

1. Зафиксировать точный wire contract Telegram proof: raw `initData`, strict
   parse, canonical data-check string, HMAC и независимые frozen vectors.
2. Вместо неявной сериализации задать закрытые DTO allowlists и точный contract
   pagination/cursor.
3. Зафиксировать session DDL, cookie headers, TTL/revoke/restart и `no-store`.
4. Сделать Mini App origin fail-fast только для web factory, не ломая worker.
5. Не добавлять Uvicorn до появления executable deployment consumer в CB-56.

## Результат попытки

Все пять замечаний были внесены в `plan.md`; scope остался узким:
auth/session/logout и существующие read projections без domain mutation,
generic framework или полного API CB-53—CB-55.
