# CB-53 — отчёт о реализации

## Результат

Локально реализован approved path:
`CB-52 session → catalog → in-memory detail → accept → authoritative confirmed state`.
До delivery остаются independent final review, commit/push/PR/CI/merge; публичный
deployment этой задачей не заявлен. Jira находится в `На проверке`.

## Реализованный scope

- Existing `GET /api/v1/tasks` обогащён пятью allowlisted fields.
- `public_input` fail closed при missing/malformed/non-string persisted
  allowlist; raw payload не сериализуется.
- Добавлен один `POST /api/v1/tasks/{task_id}/assignments`.
- Gate order: exact single Origin → CB-52 session → canonical single
  `Idempotency-Key` → canonical UUID/empty body → existing owner.
- Web `update_id`: length-prefixed `accept/member/task/key`, stdlib SHA-256,
  positive 63-bit.
- Existing receipt replay проверяет exact assignment actor/task до response.
- Для web new/different key active `(task_id, performer_id)` — natural
  resource; terminal/cancelled не реанимируется. Legacy Telegram duplicate
  semantics сохранены.
- Первый accept атомарно пишет assignment, accepted reliability, allowlisted
  audit, outbox и existing receipt. Replay/natural return не дублируют effects.
- Native HTML/CSS/ES modules UI использует CB-58 tokens и byte-identical local
  Manrope; detail живёт только в client state.
- Dynamic catalog data рендерится только `createElement`/`textContent`;
  materials URL/text не становятся links/attributes.
- Playwright используется напрямую как test-only dependency; plugin layer
  удалён после обнаруженной несовместимости с `pytest-asyncio`.

## Классификация production diff

| Файл | Категория | Причина |
|---|---|---|
| `src/community_bot/transport/web.py` | 1 — web/auth/session/DTO glue | DTO, gates, derivation, route/static delivery |
| `src/community_bot/infrastructure/db/tasks.py` | 1 — DTO/privacy glue | fail-closed saved public allowlist |
| `src/community_bot/application/assignments.py` | 2 — mechanical owner adaptation | trusted member input, replay identity, natural resource, existing audit primitive |
| `src/community_bot/transport/static/index.html` | 1 | native shell |
| `src/community_bot/transport/static/styles.css` | 1 | CB-58 semantic presentation |
| `src/community_bot/transport/static/platform.js` | 1 | atomic Telegram theme adapter |
| `src/community_bot/transport/static/app.js` | 1 | catalog/detail/accept/confirmed UI |
| `src/community_bot/domain/**` | 3 — business/domain logic | **zero diff** |

Hard gate: Category 3 = **`0 files / 0 LOC`**. Migration diff = zero; new
table/repository/service/framework/detail route = zero; CB-54 behavior = zero.

## Acceptance evidence

### Transport/privacy/idempotency

- Unit matrix доказывает Origin → session → key precedence, duplicate headers,
  canonical grammar/range и manual request validation.
- Fixed derivation vectors различают actor/task/key и остаются positive int63.
- PostgreSQL test доказывает receipt-first replay после status change, forced
  actor/task collision rejection, active natural-resource return, cancelled
  rejection и same/different-key maximum-one-effect.
- Real HTTP/PostgreSQL test доказывает one assignment/reliability/audit/outbox/
  receipt, exact replay, new-key existing DTO, generic 409 и no second receipt.
- Missing/dict/mixed-type allowlists fail closed; valid string allowlist
  пересекается с payload; private value отсутствует в HTTP response.

### Browser/XSS/accessibility

- Real Chromium path проходит catalog → detail → accept → confirmed → back.
- Malicious catalog fields видны literal text; не создаются `img`, `a`,
  event handlers, dynamic URL, script execution или navigation.
- Production theme adapter атомарно отклоняет как синтаксически invalid, так и
  low-contrast Telegram palette по фактическим CB-58 foreground/background
  pairs.
- Semantic headings/buttons, `aria-live`, возврат focus в исходную карточку,
  44px controls, safe areas, light/dark и reduced-motion присутствуют.

## Verification

- `uv run ruff format` для затронутых Python-файлов — green.
- `uv run ruff check --output-format=concise .` — green.
- `uv run ty check src tests ops` — green.
- `uv run pytest tests/unit/test_web_auth.py -q --no-cov` — **11 passed**.
- Targeted PostgreSQL pre-commit same/different-key race — **1 passed**.
- `uv run pytest tests/browser -q --no-cov` — **1 passed**; literal XSS,
  пограничный `4.5:1` accent-text fallback и focus restore подтверждены.
- `uv run pytest -m "not browser"` после review fixes — **523 passed,
  1 deselected**, coverage **81.59%** (threshold 80%); это единственный полный
  контрольный non-browser run в consolidated fix-cycle.
- Wheel содержит четыре static text assets и byte-identical Manrope.
- `git diff --check`, targeted secret-pattern scan, domain diff и migration
  diff — green/empty.

## Один soft-budget audit

Факт после consolidated review fix-cycle: 7 production text files,
479 added text lines и один byte-identical font —
ниже targets 8/800. Audit выполнен ровно один раз. Удалён лишний
`pytest-playwright` plugin и четыре transitive packages: direct `playwright`
достаточно и не вмешивается в async suite. Line-golf/refactor не выполнялся:
security branches и risk oracles должны оставаться читаемыми.

## Остаточные риски и rollback

- Live Telegram/public deployment не входит в CB-53 delivery.
- Теоретическая SHA-256 truncation collision fail closed через actor/task replay
  check; forced collision covered.
- Rollback удаляет один POST/static assets/DTO additions и mechanical web owner
  path. Schema/domain/economy history не меняются.
