# CB-28 — повторное финальное ревью

Status: approved

Схема: `community_bot.final_review.verdict.v1`.

## reviewed_scope

- Узко перепроверен exact frozen staged tree `810dcd42985f696ab8cc88840f376f1cc1e7b362` на ветке `task/CB-28`, HEAD `50694d403898ce80eed8006f9417864442113171`.
- Проверено закрытие единственного M-001 первого review и отсутствие иной staged delta: разница между прежним tree `cf3f6426f58fee5622e1e192bccb68984149554f` и новым tree ограничена двумя заменёнными строками в `tests/integration/test_navigation.py`.
- Прежний полный targeted result `15 passed` остаётся валиден; после oracle-only delta принят отдельный successful production navigation test. Полный targeted suite повторно не запускался по согласованной пропорциональной границе.
- Независимо повторены Ruff format/check, targeted ty, staged diff-check и secret scan — успешно.

## critical_findings

Нет.

## major_findings

Нет.

### Закрытие M-001

- После `/start` тест теперь выполняет `admin_button = next(...)` по фактическому `session.reply_buttons` ответа fake Bot API.
- Следующий `message_update` получает именно `admin_button`, а не импортированный `ADMIN_TEXT` как вручную сконструированный payload.
- `registration:list` по-прежнему извлекается из следующего captured inline keyboard, а `registration:approve:<member_id>` — из отправленной submitted-карточки.
- Exact replay использует полученный approval callback; итоговые assertions сохраняют target `active` и ровно один `starting_grant`.
- Таким образом, positive production-composed chain полностью соответствует новому правилу `PROJECT_RULES_AND_GUARDRAILS_RU.md`.

## minor_findings

Нет.

## acceptance_matrix_result

| Критерий Jira | Результат | Доказательство |
|---|---|---|
| Из main menu открывается admin menu без slash-команд | Пройден | Текст кнопки извлекается из captured `/start` reply keyboard и отправляется следующему Dispatcher update |
| `Заявки` показывает submitted card и decision buttons | Пройден | `registration:list` извлекается из admin response; shared registration presenter возвращает approve/reject callbacks |
| `Одобрить` активирует ровно один раз | Пройден | Полученный approval callback и exact replay оставляют target `active`, grant count 1 |
| Неадминистратор получает отказ без effects | Пройден | Member/moderator denial и итоговые effect counts сохранены неизменными |
| Production-composed main → admin → registrations → approve | Пройден | Все три пользовательских перехода последовательно получены из предыдущих fake Bot API responses |
| Ruff, ty, targeted tests, final review | Пройден | `15 passed` до oracle delta, отдельный navigation test после delta, Ruff/ty/diff/secret clean; этот verdict `approved` |
| Deploy/current submitted smoke после green CI | Ожидает внешнего этапа | Корректно остаётся post-merge действием и не заявлен выполненным локально |

## test_matrix_result

| Сценарий test-plan | Результат |
|---|---|
| 1. Active admin получает кнопку | Пройден; кнопка не только проверяется, но и извлекается |
| 2. Captured button text возвращает `Заявки` | Пройден |
| 3. Captured `registration:list` возвращает submitted card | Пройден |
| 4. Captured approval + exact replay | Пройден; active target, one starting grant |
| 5. Member/moderator denial | Пройден без effects |
| 6. Targeted/static gates | Пройден; пропорциональный test evidence и повторные static gates clean |

Итог: `6/6` сценариев пройдены.

## security_and_secret_result

- Server-side active-administrator gate остаётся authoritative на каждом menu/registration действии; UI callback не является разрешением.
- Negative member/moderator paths не создают invitation/grant и не раскрывают submitted cards.
- Approval сохраняет existing receipt/audit/update gate и exactly-once starting grant.
- Staged secret scan чист; synthetic fixtures не содержат production user data, реальных Telegram отправок нет.

## workflow_result

- M-001 закрыт минимальным test-oracle delta без изменения runtime, docs или scope после первого review.
- Implementation report теперь подтверждается непрерывной captured UI-chain и не завышает handler coverage до E2E.
- Полная регрессия обоснованно не дублировалась; до merge остаётся обязательный GitHub CI, после merge — отдельно разрешаемые deploy и production smoke.
- Frozen index после review остаётся `810dcd42985f696ab8cc88840f376f1cc1e7b362`; Jira, code/index, remote, Telegram и server не изменялись. Approved review оставлен unstaged.

## required_actions

Нет.

## residual_risks

- Production deploy и решение фактической submitted-заявки не входят в локальный verdict и должны выполняться только после green CI/merge по отдельному внешнему шагу.
