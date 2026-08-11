# CB-26 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Jira `CB-26` свежо перечитана напрямую через Atlassian Rovo API: восемь критериев приёмки, status `В работе`, severity-high контекст и blocking-связь с pilot story `CB-24` подтверждены.
- С нуля проверены актуальные `plan.md`, `test-plan.md`, `implementation-report.md`, документационный impact и полный staged diff.
- Ревью выполнено на ветке `task/CB-26`, HEAD `342370f8180f750e2e648a01228850a281eca681`, exact frozen staged tree `a0b72e7154e59fcee3fb93e3bed0600d9ba5cb54`.
- Особо проверено консолидированное закрытие единственного finding M-001 первого review: dynamic collision больше не разрешается offset-эвристикой, а pilot aliases проходят только через явную canonical-карту.
- Независимо повторён targeted gate: `uv run pytest -q --no-cov tests/unit/test_registration_domain.py tests/integration/test_registration.py tests/e2e/test_pilot_scenarios.py::test_full_exchange` — `21 passed`; Ruff format/check, `uv run ty check`, staged diff-check и secret scan — успешно. Полная регрессия MVP не запускалась.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- После explicit pilot map resolver принимает dynamic result только при `len(candidates) == 1`; любые два и более candidates возвращают `None` независимо от совпадения offsets.
- Прямое воспроизведение на frozen snapshot подтвердило: `Eastern`, `West`, `Mountain` и неизвестный город возвращают `None`.
- `Eastern` закрывает исходный same-sampled-offset случай (`Canada/Eastern`, `US/Eastern`), а `West`/`Mountain` покрывают collisions с различными offsets.
- `Москва`, `Буэнос-Айрес`, `Buenos Aires` и совместимая форма `South America/Buenos-Aires` проходят explicit canonical map; exact `Europe/Moscow` остаётся допустимым IANA input.
- Offset sampling, даты-сигнатуры и предположение о динамической alias-equivalence полностью удалены; implementation report и test-plan синхронизированы с фактической политикой.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| `Москва` → `Europe/Moscow`, skip timezone | Пройден | Explicit pilot map; registration integration и full exchange переходят сразу к `short_bio` |
| `Буэнос-Айрес`/`Buenos Aires` → canonical Argentina timezone | Пройден | Resolver unit cases и production-composed Telegram registration |
| Existing timezone draft принимает `Buenos Aires` | Пройден | PostgreSQL + Dispatcher scenario сохраняет `America/Argentina/Buenos_Aires`; exact replay читает тот же результат |
| Unknown/ambiguous city сохраняет city и показывает fallback | Пройден | Unknown integration scenario сохраняет city и выдаёт понятный prompt; `Eastern`/`West`/`Mountain` возвращают `None` |
| Exact IANA identifiers принимаются | Пройден | `Europe/Moscow` проходит exact `ZoneInfo` path и normalization |
| Resolver без API, детерминирован и не угадывает | Пройден | Только stdlib `zoneinfo`, pinned tzdata и explicit pilot map; multiple dynamic candidates всегда дают fallback |
| Replay/stale-step/idempotency не регрессируют | Пройден | Exact replay и stale-step assertions входят в зелёный registration suite; city/timezone сохраняются в одном UoW |
| Production Dispatcher, targeted tests, Ruff, ty, final review | Пройден | `21 passed`, static/diff/secret gates clean; этот verdict `approved` |

Итог: `8/8` критериев пройдены.

## test_matrix_result

| Сценарий test-plan | Результат |
|---|---|
| 1. `Москва` auto-resolve | Пройден |
| 2. `Буэнос-Айрес`/`Buenos Aires` auto-resolve | Пройден |
| 3. Existing timezone draft + `Buenos Aires` | Пройден через production Dispatcher и replay |
| 4. Exact `Europe/Moscow` | Пройден |
| 5. Unknown city + понятный fallback prompt | Пройден |
| 6. Same/different-offset ambiguity не выбирается молча | Пройден: `Eastern`, `West`, `Mountain` → `None` |
| 7. Replay/stale | Пройден |
| 8. Production-composed Telegram E2E | Пройден; регистрация завершается без технического timezone identifier |
| 9. Targeted/static gates | Пройден; `21 passed` без skip/deselect, Ruff/ty/diff clean |

Итог: `9/9` сценариев пройдены.

## security_and_secret_result

- Resolver локальный: city/timezone не передаются внешнему API, сетевых вызовов и новых интеграций нет.
- Ambiguous input больше не раскрывает внутренний произвольный выбор и переводится в одинаковый пользовательский fallback.
- City и inferred timezone сохраняются в одной транзакции до receipt/commit; replay/stale barrier сохранён.
- Staged secret scan чист: credentials, Bot API token, реальные пользовательские identifiers и приватные production payload не добавлены.

## workflow_result

- Scope соответствует отдельному production Bug CB-26: registration domain/application/Telegram transport, targeted tests и два канонических MVP-документа.
- План, test-plan, implementation report и фактический diff согласованы; прежнее завышенное утверждение об ambiguity устранено вместе с M-001.
- Русский язык смысловых артефактов, ветка `task/CB-26`, отсутствие Jira-key в runtime identifiers и отказ от повторной полной регрессии соответствуют процессу.
- Frozen index после ревью остаётся `a0b72e7154e59fcee3fb93e3bed0600d9ba5cb54`; Jira, code/index, Git remote, Telegram и server не изменялись. Approved review оставлен unstaged.

## required_actions

Нет.

## residual_risks

- Resolver сознательно не является мировым geocoder: неизвестные города и любые dynamic collisions уходят в fallback. Расширение pilot map требует явного canonical решения и targeted regression, что соответствует безопасной MVP-границе.
- Полная продуктовая регрессия не повторялась: для исправления одного production registration Bug достаточны unit/domain, PostgreSQL registration, production Dispatcher и full-exchange gates.
