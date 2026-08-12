# CB-30 — архив plan-review attempt 02

Status: changes_requested

## Закрыто

P-001–P-003 из attempt 01 подтверждены закрытыми без регрессии пяти Jira AC.

## Остаточное обязательное замечание

План смешивал два разных права: request appeal фактически разрешён active case
party, а resolve appealed case — другому independent active administrator.
Administrator-only bullet и сценарий 9 могли ошибочно запретить участнику запрос.

## Результат исправления

Permission matrix и сценарий 9 разделены на party request и independent admin
resolution, включая запрет outsider и conflicted original resolver.
