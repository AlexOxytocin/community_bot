# CB-101 — независимая security review

Status: approved

Критичных, high/medium/low findings нет.

## Проверено

- bounded 30-day TTL задан одной constant и одинаково применяется к DB expiry и
  cookie;
- cookie сохраняет `__Host-`, HttpOnly, Secure, SameSite=Strict, Path=/ и no
  Domain;
- `expires_at > now`, exact expiry и revoke остаются fail-closed;
- raw token создаётся заново, в БД передаётся только SHA-256 digest, response и
  DOM credential не раскрывают;
- logout немедленно ревокает digest и очищает cookie через `Max-Age=0`;
- existing bootstrap ограничен одним Telegram auth attempt, повторяет GET `/me`,
  не повторяет product mutation и не образует цикл;
- frontend, schema, migration, dependencies, refresh token и unload/pagehide
  logic не добавлены.

## Validation evidence

- focused oracles — 3 passed;
- полный auth/API набор — 35 passed;
- Ruff check/format, `ty`, node syntax и `git diff --check` — green;
- secret/log/storage scan — новых утечек и unload handlers нет.

## Security verdict

Увеличенное окно риска украденной cookie является осознанным bounded tradeoff
владельца. Secure/HttpOnly/SameSite=Strict, digest-only storage и explicit revoke
сохранены.

## Ponytail verdict

`Lean already. Ship.`

## Remaining uncertainty

Реальное истечение через 30 дней не ожидалось wall-clock; контракт доказан
controlled clock и exact persisted timestamps. Production delivery этим review
не подтверждается.
