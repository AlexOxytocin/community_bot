# CB-101 — план уровня 2

## Подтверждённая причина

`src/community_bot/transport/web.py` использует `_SESSION_SECONDS = 900` и для
DB `expires_at`, и для cookie `Max-Age`. Поэтому одна и та же server/cookie
session прекращает действовать через 15 минут.

Existing owners уже закрывают остальной контракт:

- `Database.web_session_member_id` принимает controlled `now` и допускает
  session только при `expires_at > now` и `revoked_at IS NULL`;
- logout ревокает digest и удаляет cookie через `Max-Age=0`;
- bootstrap выполняет bounded sequence `GET /me 401 → один Telegram auth →
  повтор bootstrap`, а второй failure завершает flow без цикла;
- raw token создаётся случайно, в БД хранится только SHA-256 digest, cookie
  остаётся `__Host-`, HttpOnly, Secure, SameSite=Strict, Path=/, без Domain.

## Минимальная реализация Ponytail full

1. Переименовать constant в `_SESSION_LIFETIME_SECONDS` и установить
   `2_592_000` секунд.
2. Переиспользовать эту одну constant для DB expiry и cookie `Max-Age`.
3. Не менять frontend/runtime flow: existing one-retry bootstrap уже выполняет
   требование; защитить его exact browser oracle.
4. Не добавлять refresh token, unload handler, endpoint, schema, migration,
   dependency, scheduler или session framework.

## Проверка

- unit: exact cookie flags и `Max-Age=2592000`; captured DB timestamps дают
  exact 30-day lifetime; повторная auth выдаёт новый raw token;
- integration: session разрешена непосредственно до expiry и запрещена в exact
  expiry и после; logout/revocation/invalid cookie остаются fail-closed;
- browser: initial `401 → один auth → повтор original GET success`, second 401
  не создаёт loop, mutation не повторяется;
- Ruff/format, `ty`, targeted auth/API/browser regression, secret scan;
- независимый security review с `Status: approved`, затем PR/CI/merge и
  immutable production delivery.

## Security boundaries

- 30 дней — bounded lifetime, не infinite credential;
- ручное закрытие WebView сервер надёжно определить не может, поэтому revoke на
  `unload/pagehide` не добавляется;
- token/digest/cookie values не попадают в DOM, логи, Jira или task artifacts;
- explicit logout остаётся единственным немедленным client-driven revoke.
