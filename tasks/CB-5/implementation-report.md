# CB-5 — отчёт о реализации

## Результат

Подтверждённые владельцем решения Q-005/Q-006/Q-011 синхронизированы в
канонической документации. Python-код, БД, миграции и Telegram runtime не
изменялись.

## Реализованные решения

- Eligibility кармы возникает после первой ненулевой полной или частичной
  выплаты между парой и сохраняется навсегда как исторический факт.
- Получатель и любой moderator видят только aggregate/count; raw karma доступна
  только active administrator с `karma_review`, с аудитом.
- Active-пользователь видит safe projection всех active-профилей; полный набор
  non-active статусов закрыт одинаковой серверной policy list/get/callback/UUID.
- Собственный профиль доступен при `active` и `paused`; `restricted` не получил
  нового безусловного права.
- D-005 и PRD уточнены permission-gated административным доступом.
- Q-005/Q-006/Q-011 удалены из открытых вопросов, moderation TBD, handoff и
  продуктовых барьеров этапа 7.

## Критерии Jira

| Критерий | Статус | Доказательство |
|---|---|---|
| В журнале нет открытых Q-005/Q-006/Q-011 | пройден | D-020–D-022 добавлены; `OPEN_Q=0`, `STALE_Q=0` |
| Для каждой роли описаны чтения и действия | пройден | Матрицы в `plan.md`, PRD и `07_SECURITY_AND_PRIVACY.md` |
| Требования, интерфейс, безопасность и тест-план согласованы | пройден | Обновлены PRD, domain, flows, interface, security, moderation, implementation plan, test plan и handoff |
| Есть negative callback/visibility scenarios | пройден | Callback, UUID, stale cursor, status race и non-disclosure закреплены в interface/security/test plan |
| Секреты и персональные данные не добавлены | пройден | Secret scan diff — успешно; используются только роли, статусы и технические идентификаторы |

## Проверки test-plan

Все 17 сценариев представлены точными будущими oracle в канонических
документах: eligibility, self-vote, invalid assignment outcomes, необратимость
после correction/reversal, конкурентные revisions, role-gated raw read, полный
набор `MemberStatus`, admin `member_read`, callback/UUID/stale cursor и
нераскрывающий отказ.

## Выполненные проверки

- локальные Markdown-ссылки: `LINKS_OK=20 files`;
- открытые заголовки Q-005/Q-006/Q-011: `OPEN_Q=0`;
- устаревшие формулировки открытого барьера: `STALE_Q=0`;
- старые безусловные admin/moderator raw-karma формулировки: `RAW_POLICY_OK`;
- секретоподобные значения в diff: не найдены;
- `git diff --check`: успешно.

Полный pytest, Ruff и ty намеренно не запускались: runtime, Python и конфигурация
инструментов не менялись. Общая продуктовая регрессия выполняется отдельной
задачей после готовности всего MVP.

## Отклонения от плана

Добавлены `docs/mvp/08_MODERATION_AND_ABUSE.md`,
`docs/mvp/09_IMPLEMENTATION_PLAN.md` и `docs/mvp/HANDOFF.md`, потому что после
закрытия вопросов в них оставались старые TBD, более широкое право raw read и
барьер этапа 7. Это необходимая синхронизация того же решения, без расширения
продуктового поведения.
