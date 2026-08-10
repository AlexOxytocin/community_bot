# CB-7 — план проверки журнала экономики и уровней

`community_bot.developer.test_plan.v1`

## Предусловия

- ветка `task/CB-7` основана на актуальном `origin/main`;
- `uv sync --locked --all-groups` завершён;
- Docker/Compose доступны, `postgres:18` healthy;
- `DATABASE_URL` указывает на локальный Compose PostgreSQL для полного прогона;
- Testcontainers fallback отдельно запускается без `DATABASE_URL`;
- каждый integration test использует отдельную временную database и применяет
  Alembic `head`; row-level cleanup не выполняется;
- реальные Telegram token, Bot API и пользовательские данные не используются.

## Тестовые данные

- active member A с нулевыми кэшами;
- active member B с балансом `10` и опытом на границах уровней;
- active administrator C и active moderator D;
- inactive administrator E для отрицательных authorization cases;
- candidate v1 из `config/product-config.v1.json` с порогами
  `0/10/25/50/100/180/300/450/650/1000` и interaction policy `3/7`;
- candidate с тем же product snapshot и другим `config_version`;
- валидная candidate v2 с изменённым уровнем и policy, поэтому с другим
  `content_hash`;
- искусственные одинаковые timestamps для проверки курсора истории;
- большие idempotency keys и UUID, не зависящие от Jira key.

## Сценарии

| № | Сценарий | Шаги | Ожидаемый результат | Доказательство |
|---:|---|---|---|---|
| 1 | Migration и числовые типы | Upgrade чистой базы; на `0002` проверить member с cache `0/level 1`, затем отдельно ненулевой cache/level; проверить `BIGINT` значением выше int32; downgrade пустой и непустой `0003` | Zero legacy upgrade успешен и кэши становятся `BIGINT`; недостоверный legacy upgrade атомарно отклонён; большое значение сохраняет SUM=cache; пустой downgrade обратим, непустой отказывается терять историю | migration/integration tests + Alembic cycle |
| 2 | Append-only ledger/config | Через SQL выполнить `UPDATE`/`DELETE` transaction, config version, level, activation, completed backfill run; удалить/сменить key singleton pointer | Все history rows защищены; pointer нельзя удалить/переименовать, только валидно переключить | PostgreSQL integration test |
| 3 | Матрица операций | Выполнить grant, reserve, earned, refund, partial, community reward, penalty, credit-only и experience-only adjustments | Типы/дельты валидны, кэши равны SUM; earned/partial/community дают равный XP; ordinary spend/refund/grant XP `0`; adjustment явно корректирует XP | unit + integration parameterization |
| 4 | Canonical payload/idempotency | Same typed command представить с иным JSON whitespace/key order; затем при том же key по одному изменить type, member, credit, experience, actor, trimmed reason/comment, reversal source | Незначащее представление даёт stored result; изменение каждого значащего поля даёт conflict без ledger/cache/audit effect | unit + integration |
| 5 | Starting grant once | Два конкурентных вызова для одного member, повтор после нового Database instance и попытка передать caller key | Ровно одна `starting_grant:{member_id}`, `+5/+0`; caller не может изменить identity | concurrent PostgreSQL test |
| 6 | Конкурентный reserve | При balance `10` одновременно резервировать `7` и `6`; повторить с несколькими малыми суммами | Успевает только допустимый набор; committed cache и SUM неотрицательны и равны; XP не меняется | concurrent PostgreSQL test |
| 7 | DB validation | Прямым SQL вставить неизвестный type, нулевую/неверную дельту, XP на refund/reserve/penalty, earned с неравными дельтами, второй grant | Каждая строка отклонена constraint/unique index | PostgreSQL integration test |
| 8 | Exact reversal на уровне DB | Через service аннулировать earning и retry; прямым SQL проверить missing source, wrong member, wrong credit/experience delta, source=reversal и второй reversal | Только одна точная inverse row проходит; cache/level пересчитаны; все поддельные/chained варианты отклонены trigger/unique | unit + PostgreSQL integration |
| 9 | Reconciliation | На согласованной базе запустить сверку; затем прямым SQL испортить credit cache, experience cache и оба | Сначала mismatch отсутствует; затем точные expected/actual; ledger не меняется и repair не выполняется | PostgreSQL integration test |
| 10 | Авторизация истории/сверки | A читает себя/B; D себя/B; C читает B и сверяет; inactive E пробует оба query | A/D только self; C любой target и reconciliation; остальные получают server-side deny | application unit + integration |
| 11 | Property sequence | Hypothesis генерирует допустимые/отклонённые grant/reserve/refund/reward/penalty/adjustment/reversal | После каждого commit SUM=cache, balance/experience >=0; ordinary XP invariants сохранены; reject ничего не меняет | stateful/property tests |
| 12 | Admin correction опыта | Active admin добавляет и уменьшает только XP/credits с reason; member/moderator/inactive admin пробуют то же; проверить отрицательную границу и retry | Только active admin успешен; audit, payload hash, cache и level атомарны; пустая причина/отрицательный итог отклонены | unit + integration |
| 13 | Fault rollback ledger | Fault после SQL flush ledger и после cache update до audit/commit | Нет transaction/cache/audit; retry того же key применяет один эффект | PostgreSQL integration test |
| 14 | Candidate schema/content hash | Переставить JSON keys/levels и whitespace; сменить только config version; затем по одному level/policy field; проверить invalid levels, threshold/window и unknown fields | Одна product projection независимо от version/формата имеет тот же content hash; любое product изменение меняет hash; invalid отклонён до DB | unit/Pydantic tests |
| 15 | Ingest sequential/concurrent | Retry v1; same version/different hash и same content/new version последовательно и конкурентно; member/moderator/inactive admin пробуют ingest; затем active admin создаёт монотонную v2 | Один детерминированный outcome без сырого IntegrityError; collisions/unauthorized отклонены без rows/audit, v2 сохранена с actor и одним audit | concurrent PostgreSQL test |
| 16 | Activation/retry/no-op/rollback | A→v1, retry, A→v2 conflict; B→already-active v1; C→v2; D→v1 rollback, retry | Stored retry, changed target conflict; no-op имеет activation/audit без backfill; switch/rollback по одному backfill | integration test |
| 17 | Concurrent first activation | На пустом pointer одновременно разные commands/targets; отдельно concurrent retry одной command | Fixed gate создаёт один pointer и последовательную history; каждый command имеет детерминированный stored outcome, без IntegrityError | concurrent PostgreSQL test |
| 18 | Activation authorization/invalid | Member, moderator, inactive admin и active admin с неизвестной version | Все invalid/unauthorized случаи без activation/audit/pointer/cache mutation | unit + integration |
| 19 | Bootstrap coordinator | Existing active без candidate; invalid candidate при active; first bootstrap без candidate; valid candidate с active admin; valid candidate без/с inactive/non-admin actor; retry stable command ID | Ровно четыре контрактных исхода; нет hidden role grant/auto-generated retry ID; unauthorized/invalid ничего не записывают | application + PostgreSQL integration |
| 20 | Единый config/member lock order | Concurrent bootstrap coordinator против standalone ingest/activation с тем же actor; отдельно activation/backfill против economy batch на участниках с обратным входным UUID-порядком | Ingest берёт `product_config_mutation → actor`; activation/bootstrap берут `product_config_mutation → all members by UUID` и проверяют actor из набора; economy берёт members by UUID. Все завершаются без deadlock/сырого IntegrityError, history/pointer/SUM/cache согласованы | concurrent PostgreSQL test с timeout |
| 21 | Level boundaries | Для каждого порога `threshold-1/threshold`, отдельно `0`, `1001`, большое `BIGINT` | Соседние уровни корректны; выше 1000 level 10 | parameterized unit/property test |
| 22 | Stale cache и atomic scale | Cache v1, activation v2; параллельно resolver read и earning на members по обе стороны actor UUID | Query видит целиком v1 или v2; stale cache не определяет result; commit ставит active version; UUID lock order не даёт deadlock | concurrent PostgreSQL integration с timeout |
| 23 | Backfill/no ledger/fault/immutability | Activate v2 на members, retry/no-op, fault после pointer switch; затем SQL mutate run | Один completed run на switch, нет ledger/notifications; fault откатывает pointer/cache/run/audit; history immutable | PostgreSQL integration test |
| 24 | История и cursor | Создать > page size rows с одинаковым timestamp; пройти pages | Стабильный `(created_at DESC,id DESC)`, без пропусков/дублей, только target | integration test |
| 25 | Публичная batch composition | Test-only `TaskLikeUnitOfWork` публично предоставляет `save_marker`, `economy.apply_batch`, один `commit`; проверить marker + несколько entries rollback/commit, all-stored retry и mixed stored/new reject; затем два concurrent batch получают одинаковые author/performer entries в обратном input order | Test не читает `_session`; nested commit отсутствует; общий prelock сортирует все gates/member UUID до append; оба workflow завершаются без deadlock, SUM=cache, mixed/fault/retry не оставляет части | concurrent integration через application/UoW API с timeout |
| 26 | Restart persistence | Создать ledger/config, dispose Database, новый instance, прочитать cache/history/active и retry | Committed state/outcomes сохранены, дублей нет | integration test |
| 27 | Baseline-дефект CB-17 | Уточнить callback до `Connection`; запустить ty и реальный Alembic async migration | `ty` exit 0, runtime migration не изменилась | type check + migration tests |
| 28 | Полный Compose regression | Весь `uv run pytest` с Compose `DATABASE_URL` | Все passed, `0 skipped/deselected`, coverage >=80% | implementation report |
| 29 | Testcontainers fallback | Без `DATABASE_URL` запустить три economy integration-файла с `--no-cov`; coverage отдельно обязан пройти на полном Compose regression | PostgreSQL 18 стартует, targeted functional run завершается exit `0`, все passed, `0 skipped/deselected`; общий coverage не маскируется узким subset | implementation report |
| 30 | Quality/build/runtime | Ruff format/check, ty, build, bot/worker `--check`, architecture boundaries | Все exit 0; package/entrypoints работают | command logs |
| 31 | Docs/diff/secrets | Markdown links, full/staged diff-check, secret scan, русский язык | Нет broken links, whitespace, credentials или непереведённого текста | scripts/rg + review evidence |

## Матрица критериев Jira

| Критерий | Основные сценарии | Обязательное утверждение |
|---|---|---|
| Ledger sum = cache | 1, 3, 6, 8, 9, 11–13 | проверка после каждого committed operation и при fault |
| Idempotency retry | 4, 5, 8, 12, 15–17, 25, 26 | same key/same payload один effect; changed payload conflict |
| Grant/refund no XP | 3, 5, 7, 11 | journal и cache experience неизменны |
| Spend no XP decrease | 3, 6, 7, 11, 12 | reserve/penalty имеют XP `0`; admin experience correction отдельно авторизована и аудируется |
| Concurrent reserve no negative | 6 | row lock + post-lock balance check |
| Reconciliation detects mismatch | 9 | exact structured mismatch, no silent repair |
| Unit/property/PostgreSQL pass | 1–31 | полный Compose и Testcontainers без skip/deselect |

## Контрольные команды

```powershell
docker compose up -d postgres
docker compose ps
$env:DATABASE_URL='postgresql+asyncpg://community_bot:community_bot@localhost:5432/community_bot'
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv build
uv run community-bot --check
uv run community-worker --check
Remove-Item Env:DATABASE_URL
uv run pytest -ra --no-cov tests/integration/test_economy.py tests/integration/test_economy_extended.py tests/integration/test_economy_property.py
```

Последняя команда обязана реально поднять PostgreSQL 18 через Testcontainers и
завершиться exit `0`. `--no-cov` отключает только нерепрезентативный глобальный
coverage для targeted subset; обязательный порог `80%` проверяется предыдущим
полным Compose-прогоном. Если Docker недоступен, проверка падает; пропуск не
разрешён.

## Очистка тестовых данных

- Integration fixture закрывает engine/connections и удаляет созданную для
  теста временную database через maintenance connection с
  `DROP DATABASE ... WITH (FORCE)`.
- Append-only rows не удаляются по одной и triggers не отключаются.
- Compose database после ручного migration cycle остаётся на `head`.
- Compose container остаётся поднятым как постоянная локальная тестовая среда;
  volume автоматически не удаляется.
- Candidate config является версионируемым fixture продукта, а не секретом или
  временным файлом.

## Ограничения

- CB-7 не проверяет Telegram registration/task flows end-to-end, потому что их
  владельцы CB-5 и CB-9–CB-11; проверяются прикладные команды и transaction
  composition, которые эти flows будут вызывать.
- Поля и физические FK к tasks/assignments/alerts появятся только вместе с
  соответствующими таблицами; CB-7 не хранит непроверяемые correlation UUID.
- Производительность массового backfill измеряется только функционально на
  pilot-scale данных; нагрузочное пороговое значение не принято продуктом.
- Никаких реальных Telegram, Jira или иных внешних mutations тесты не выполняют.
