# CB-58 — финальное ревью компактной редакции

Schema: `community_bot.final_review.verdict.v1`

Status: changes_requested

## Проверенная область

Независимо проверено итоговое состояние ветки `task/CB-58` относительно
`origin/main` с учётом двух коммитов старой реализации и незакоммичённого
упрощения. `merge-base HEAD origin/main` равен
`de9779922a92243974a37c8663e1154e94a57052`, ветка опережает базу на два
коммита и не отстаёт от неё.

Прочитаны текущие `plan-source-context.md`, `plan.md`, `plan-review.md` со
`Status: approved`, `test-plan.md`, `implementation-report.md`, решение
владельца после terminal review, обе цепочки escalation/review и исторический
результат до упрощения. Проверены итоговые `DESIGN.md`,
`design-tokens.json`, `design-preview.html`, font/license bundle и contract
tests. Изменений runtime, API, БД, migrations, Telegram transport или
deployment нет.

Уровень процесса — 3: задача насыщена источниками, имеет ручной browser gate и
обязательные plan/final reviews. Нужные артефакты уровня 3 присутствуют, а
плановый gate после разрешённого владельцем terminal remediation одобрен.

## Критические замечания

Нет.

## Существенные замечания

1. **Обязательные static/whitespace gates фактически не закрыты, поэтому PR CI
   сейчас гарантированно не пройдёт.**

   - Точная команда CI из `.github/workflows/ci.yml:26`,
     `ruff format --check .`, завершается с exit code `1`:
     `tests/documentation/test_release2_design_system.py` требует
     форматирования provider cases на строках 166–183 и выражения
     `validated_pairs` на строках 265–268. При этом `ruff check .` и
     `ty check src tests ops/verify_release_provenance.py` проходят.
   - `docs/release-2/design/assets/Manrope-OFL.txt:21` содержит trailing space.
     `git diff --no-index --check -- NUL
     docs/release-2/design/assets/Manrope-OFL.txt` завершается с exit code `3`.
     Ранее заявленный `git diff --check` не видел дефект, потому что font/license
     bundle всё ещё untracked.
   - Утверждения `Ruff: passed` и `git diff --check: passed` в
     `implementation-report.md:43-53`, а также evidence в
     `test-plan.md:13-21,62` поэтому неполны: lint действительно прошёл, но
     обязательный formatter gate не запускался, а whitespace check не охватил
     весь фактический результат.

   Это не замечание о вкусе форматирования: текущая ветка нарушает реальный CI
   contract и запланированный delivery gate. `Status: approved` при таком
   результате запрещён.

## Незначительные замечания

Нет.

## Результат матрицы приёмки

| Критерий CB-58 | Результат | Независимое доказательство |
| --- | --- | --- |
| Semantic dark/light roles | Пройден | Exact themes и parity JSON ↔ CSS проверены targeted suite |
| Cyan/violet не обозначают success/error | Пройден | Brand и status roles разделены в tokens, DESIGN и preview |
| WCAG AA и targets от 44px | Пройден в области preview | 19 policy pairs проверены для обеих themes; минимальная base ratio `4.592746`; size tokens и DOM contract проходят |
| Один набор tokens для Telegram/browser | Пройден как design contract | Mapping и atomic base-theme fallback находятся в одном JSON contract |
| Telegram SDK изолирован | Пройден | В diff нет runtime-кода; `Telegram.WebApp` отсутствует в preview, boundary описана через `PlatformBridge` |
| Manrope для рабочего UI | Пройден | Font `165420` bytes, SHA-256 `d0639be45d0af36e798172419d7bd173c4bd4f29e2b76cbb69db1d11bf8b0a40`; Chrome сообщает loaded `Manrope` 200–800 |
| Glow/motion функциональны | Пройден | Gradient ограничен brand/route, reduced-motion rule присутствует |
| Mobile и desktop previews | Пройден | Chrome `1440×1000` и `375×812`: overflow отсутствует, responsive navigation переключается |

Функциональных дефектов design contract не воспроизведено. Они не отменяют
непройденный delivery gate выше.

## Результат матрицы тестов

- Targeted pytest:
  `5 passed in 0.23s`.
- `ruff check --no-cache .`: passed.
- `ty check src tests ops/verify_release_provenance.py`: passed.
- `ruff format --check --no-cache .`: **failed**, один новый test file требует
  форматирования.
- Полный pytest без активированного `PATH`: `605 passed, 1 skipped`, пять
  ожидаемых entrypoint failures из-за отсутствия console scripts в `PATH`.
  Контрольный повтор `tests/smoke/test_entrypoints.py` с `.venv\Scripts` в
  `PATH`: `5 passed`. Новых product failures не обнаружено.
- Contrast audit: все 19 base pairs проходят. Terminal candidates воспроизведены
  без округления и отклоняются: dark `background=#454545` — `4.462083`, light
  `background=#A9A9A9` — `2.077682`, dark `accent=#777777` — `4.277436`.
- Read-only Chrome audit через `file://`: Manrope loaded; console/page errors
  `0`; dark/light overlays различаются; primary/secondary/danger hover и
  pressed computed backgrounds различаются; dialog открывается с focus внутри,
  закрывается по `Escape` и возвращает focus; mobile body `375` при viewport
  `375`.
- `git diff --check origin/main`: проходит только для tracked diff;
  no-index check обязательного untracked license asset выявляет trailing
  whitespace.
- Pixel baseline отсутствует, поэтому visual regression остаётся
  `inconclusive`, как и заявлено в test plan.

## Безопасность и секреты

Secret-like scan 23 изменённых и untracked paths не нашёл credentials, Bot API
tokens, session strings, private keys или cookies. Binary font отдельно
проверен по pinned hash. Приватные Telegram данные отсутствуют; Telegram/live
операции не выполнялись. Изменения ограничены documentation/design/task
artifacts и `tests/documentation/`.

## Процесс и ветка

Ветка и база соответствуют правилу `task/CB-58`. Текущий `plan-review.md` имеет
точный `Status: approved`; исторические approved verdicts корректно отделены от
нового gate. Owner decision разрешил один post-terminal remediation и прямо
требует снова остановить задачу, если следующая независимая проверка не даст
`Status: approved`. Поэтому автоматический fix/review cycle продолжать нельзя.

## Обязательные действия

1. Остановить CB-58 и получить новое явное решение владельца о дополнительном
   узком remediation.
2. Если remediation разрешён, применить formatter к
   `tests/documentation/test_release2_design_system.py` без изменения смысла и
   удалить trailing whitespace из `Manrope-OFL.txt:21`, сохранив текст OFL.
3. Повторить точные CI static gates и whitespace check, охватывающий font/license
   bundle, затем обновить `implementation-report.md` фактическими командами и
   результатами.
4. После любого изменения итогового diff выполнить новую независимую проверку;
   commit, push, PR и merge до `Status: approved` запрещены.

## Остаточные риски и неопределённость

- Static preview не доказывает parity будущих React components и реального
  Telegram WebView; этот runtime gate принадлежит CB-53/release acceptance.
- Автоматический equality gate связывает объявленный live contrast inventory с
  policy, но не выводит пары из произвольного CSS. Для текущего preview полнота
  независимо сверена; будущие CSS-изменения требуют повторной ручной проверки.
- Screen-reader и pixel-baseline проверки отсутствуют; browser audit закрывает
  только заявленные keyboard/focus/responsive сценарии.
- Финальный verdict терминален для разрешённого owner decision review cycle:
  обязательные исправления известны, но их выполнение требует нового решения
  владельца.
