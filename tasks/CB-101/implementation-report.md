# CB-101 — отчёт реализации

## Результат

- Server/cookie lifetime теперь задаётся одной
  `_SESSION_LIFETIME_SECONDS = 2_592_000` и составляет bounded 30 дней.
- Существующие cookie flags не изменены: `__Host-community_session`, HttpOnly,
  Secure, SameSite=Strict, Path=/, no Domain.
- DB owner, strict expiry predicate, digest-only storage, logout/revocation и
  `Max-Age=0` не изменены.
- Existing bootstrap уже выполняет один Telegram re-auth после initial `401` и
  повторяет исходный GET flow один раз; новый refresh layer не добавлен.

## Матрица приёмки

| Критерий | Доказательство | Статус |
|---|---|---|
| Cookie 30 дней | unit exact `Max-Age=2592000` | green |
| DB 30 дней | captured и persisted `expires_at-authenticated_at == 30 days` | green |
| Strict expiry | controlled `now`: before → valid, at/after → invalid | green |
| Token privacy/rotation | две auth создают разные cookie/digests; raw bytes отсутствуют в response | green |
| Logout/revocation | concurrent logout 204, `Max-Age=0`, revoked session → 401 | green |
| Invalid cookie | malformed/unresolved cookie → 401 | green |
| Transparent bootstrap | browser: `/me` 401 → auth count 1 → `/me` success; invalid proof no loop | green |
| Без architecture expansion | frontend/schema/migration/dependency/repository не изменены | green |

## Проверки

- focused unit/integration/browser — 3 passed;
- полный `test_web_auth.py` + `test_web_api.py` + auth browser oracle — 35 passed;
- Ruff lint/format, `ty`, node syntax и `git diff --check` — green.

## Security review checklist

- hardcoded secrets/token logging/DOM storage — отсутствуют;
- raw token хранится только в HttpOnly cookie, в БД остаётся SHA-256 digest;
- SameSite/Origin/HTTPS boundary и generic auth errors не изменены;
- expired/revoked/invalid session fail closed;
- unload/pagehide revoke, infinite lifetime и refresh credential не добавлены.

## Ограничение

Сервер не может надёжно определить ручное закрытие WebView. Bounded 30-day
cookie и existing Telegram re-auth дают требуемый UX без infinite credential и
без ненадёжного client-side revoke.

## Delivery state

Independent security review, PR/CI/merge, immutable release, production
activation и public/Telegram smoke остаются обязательными следующими gates.
