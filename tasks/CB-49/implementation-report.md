# CB-49 — отчёт о реализации

## Результат

Архитектурный и продуктовый контракт Release 2 зафиксирован без изменения
runtime. Telegram Mini App определён как первый визуальный клиент общей
платформы, Telegram-бот — как регистрация, вход, уведомления и fallback, а
будущий browser mode — как новый auth/platform adapter к тем же API и
application services.

После независимого повторного review плана со статусом `approved` владелец
2026-08-16 явно принял точную редакцию ADR-0014. В Jira CB-49 принятие
зафиксировано комментарием `10160`.

## Выполненные изменения

- создан и принят
  [ADR-0014](../../docs/adr/0014-multi-interface-release-2.md);
- создан
  [capability-контракт Release 2](../../docs/release-2/README.md) с разделами
  `CAPABILITY`, `CONSTRAINTS`, `IMPLEMENTATION CONTRACT`, `NON-GOALS`,
  `OPEN QUESTIONS` и `HANDOFF`;
- создана
  [матрица функционального паритета](../../docs/release-2/PARITY_MATRIX.md),
  покрывающая вход, участников, экономику, задания, карму, споры,
  администрирование, уведомления и эксплуатационные gates;
- добавлено решение D-033 и обновлены индекс ADR, карта MVP, технологический
  стек и handoff;
- сохранён визуальный референс владельца в source context; окончательная
  дизайн-система и палитра оставлены задаче CB-58;
- runtime-код, schema, dependencies, configuration и deployment не изменялись.

## Проверка критериев приёмки

| Критерий | Доказательство | Результат |
|---|---|---|
| Одна доменная модель для bot, Mini App и browser readiness | ADR-0014, раздел «Решение», пункты 1–2 и 8 | Пройдено |
| Transport-neutral identity | Capability, `ActorContext`: internal `member_id`, provider/session только audit metadata | Пройдено |
| Актуальная authorization | Role/status/permissions/ownership читаются из PostgreSQL каждым защищённым use case | Пройдено |
| Auth adapter и внутренняя session | Telegram `initData` проверяется adapter; browser auth оставлен отдельным решением | Пройдено |
| Идемпотентность разных transport | Scope `(transport_namespace, actor_id, external_key)`, command, fingerprint и outcome | Пройдено |
| Replay/conflict semantics | Exact replay возвращает outcome; другой command/payload отклоняется без эффекта | Пройдено |
| Platform isolation | `PlatformBridge`, capability detection, события и `supported|unsupported` | Пройдено |
| Безопасная навигация | `start_param` и прямой URL определены только как недоверенные hints | Пройдено |
| Rollout | Server-side fail-closed flags; invalid/missing config означает disabled | Пройдено |
| Release strategy | `v1.0.0`, выпускаемый `main`, без постоянной `release/2` | Пройдено |
| Browser readiness и стоимость | Границы `10–15%` сейчас и `20–35%` позднее записаны без обещания browser product | Пройдено |
| Функциональный паритет | Матрица покрывает обязательные R1-поверхности и владельцев CB-50 — CB-57 | Пройдено |
| Паритет кармы | Одна текущая оценка на `автор → получатель`; eligibility после первой ненулевой выплаты между парой и сохраняется исторически | Пройдено |
| Privacy-safe HTTP errors | Внутренняя классификация не меняет одинаковый внешний отказ для скрытого/отсутствующего/недоступного ресурса | Пройдено |
| Дизайн | Dark neon референс отделён от рабочей композиции; решение делегировано CB-58 | Пройдено |
| Русский язык смысловых артефактов | Ручная проверка изменённых документов | Пройдено |

## Выполненные проверки

| Проверка | Результат |
|---|---|
| Внутренние Markdown links по 13 файлам | `PASS` |
| Обязательные capability sections | `PASS`, 6 из 6 |
| Семантические assertions ADR/auth/idempotency/bridge/rollout/browser/parity/privacy | `PASS`, 18 из 18 |
| YAML gate | `NOT_APPLICABLE`, изменённых или новых `.yml`/`.yaml` нет |
| `git diff --check` | `PASS` |
| `uv run ruff format --check .` | `PASS`, 472 files already formatted |
| `uv run ruff check .` | `PASS` |
| Secret-like signature scan по добавленным и изменённым материалам | `PASS` |
| Audit ложных runtime-утверждений | `PASS`: capability готов к реализации, API/frontend не объявлены реализованными |

## Осознанно не выполнялось

- `test-plan.md` и live Telegram gate не нужны: пользовательское/runtime
  поведение не изменялось;
- Git tag `v1.0.0` и GitHub Release не создавались: это область CB-50;
- API, frontend, auth/session, schema и server deployment не реализовывались:
  это CB-51 — CB-57;
- окончательные tokens, typography и component preview не принимались: это
  CB-58.

## Исправления после первого final review

Первый независимый final review вернул `Status: changes_requested` с двумя
смысловыми замечаниями. Они закрыты одним циклом:

1. parity-контракт кармы исправлен с ошибочного «один rating на interaction» на
   каноническое правило одной текущей оценки для направленной пары
   `автор → получатель`; также явно записаны точное условие eligibility и его
   сохранение как исторического факта;
2. HTTP-контракт разделил внутреннюю классификацию ошибок для безопасной
   наблюдаемости и одинаковый внешний отказ для скрытого, отсутствующего и
   недоступного privacy-sensitive ресурса.

После исправлений повторены Markdown link check, семантические assertions,
`git diff --check`, Ruff и secret-like scan. Пакет передан на одну повторную
независимую финальную проверку.

## Остаточные вопросы и handoff

Открытые вопросы имеют явных владельцев и не блокируют принятие capability:
session/CSRF/revocation — CB-52; design system — CB-58; HTTPS edge, domain,
feature flags и rollback — CB-56; browser auth — отдельная будущая задача.

Рекомендуемая последовательность реализации: CB-50 → CB-51 → CB-52 → CB-58 →
CB-53 → CB-54/CB-55 → CB-56 → CB-57.
