# CB-96 — полный screen/state/transition inventory

Этот файл детерминированно генерируется из `build_ui_contract.py`.

## Экраны

| ID | Экран | Route pattern | view_state | family | role | action class | data mode | parent |
|---|---|---|---|---|---|---|---|---|
| A01 | Launch / bootstrap | `#/start` | `a01` | `state` | `all` | `ui_local_only` | `existing_http_connected` | — |
| A02 | Недоступная сессия | `#/start` | `a02` | `state` | `all` | `ui_local_only` | `existing_http_connected` | A01 |
| A03 | Приглашение | `#/start` | `a03` | `form` | `guest` | `disabled_unavailable` | `unavailable_without_fixture` | A01 |
| A04 | Правила и consent | `#/start` | `a04` | `detail` | `guest` | `disabled_unavailable` | `unavailable_without_fixture` | A03 |
| A05 | Анкета регистрации | `#/start` | `a05` | `form` | `guest` | `disabled_unavailable` | `unavailable_without_fixture` | A04 |
| A05A | Preview и отправка заявки | `#/start` | `a05a` | `detail` | `guest` | `disabled_unavailable` | `unavailable_without_fixture` | A05 |
| A06 | Ожидает одобрения | `#/start` | `a06` | `state` | `pending` | `ui_local_only` | `unavailable_without_fixture` | A05A |
| A06A | Заявка отклонена | `#/start` | `a06a` | `state` | `pending` | `disabled_unavailable` | `unavailable_without_fixture` | A06 |
| A07 | Ограниченный доступ | `#/start` | `a07` | `state` | `status` | `ui_local_only` | `local_view_state` | A01 |
| T01 | Каталог заданий | `#/catalog` | `t01` | `list` | `member` | `ui_local_only` | `existing_http_connected` | — |
| T02 | Фильтры каталога | `#/catalog` | `t02` | `form` | `member` | `ui_local_only` | `local_view_state` | T01 |
| T03 | Полная карточка задания | `#/tasks/:task_id` | `t03` | `detail` | `member` | `ui_local_only` | `existing_http_connected` | T01 |
| T03A | Подтверждение обязательства | `#/tasks/:task_id` | `t03a` | `dialog` | `member` | `existing_http_connected` | `existing_http_connected` | T03 |
| T04 | Solo / group | `#/compose/tasks/:draft_id?` | `t04` | `form` | `member` | `ui_local_only` | `local_view_state` | T01 |
| T04A | Выбор шаблона | `#/compose/tasks/:draft_id?` | `t04a` | `list` | `member` | `ui_local_only` | `unavailable_without_fixture` | T04 |
| T04B | Черновики заданий | `#/compose/tasks/:draft_id?` | `t04b` | `list` | `owner` | `ui_local_only` | `local_view_state` | T04 |
| T05 | Редактор задания | `#/compose/tasks/:draft_id?` | `t05` | `form` | `owner` | `ui_local_only` | `local_view_state` | T04A |
| T06 | Preview задания | `#/compose/tasks/:draft_id?` | `t06` | `detail` | `owner` | `ui_local_only` | `local_view_state` | T05 |
| T07 | Confirm публикации | `#/compose/tasks/:draft_id?` | `t07` | `dialog` | `owner` | `existing_http_connected` | `existing_http_connected` | T06 |
| T08 | Опубликовано | `#/compose/tasks/:draft_id?` | `t08` | `state` | `owner` | `ui_local_only` | `existing_http_connected` | M10 |
| M01 | Мои задания | `#/work` | `m01` | `tabs` | `member` | `ui_local_only` | `existing_http_connected` | — |
| M02 | Взятые мной | `#/work` | `m02` | `list` | `member` | `ui_local_only` | `local_view_state` | M01 |
| M03 | Назначение | `#/work/:resource_id` | `m03` | `detail` | `performer` | `ui_local_only` | `existing_http_connected` | M02 |
| M04 | Редактор результата | `#/work/:resource_id` | `m04` | `form` | `performer` | `existing_http_connected` | `existing_http_connected` | M03 |
| M04A | Версии результата | `#/work/:resource_id` | `m04a` | `list` | `party/reviewer` | `ui_local_only` | `unavailable_without_fixture` | M04 |
| M05 | Preview результата | `#/work/:resource_id` | `m05` | `detail` | `performer` | `ui_local_only` | `local_view_state` | M04 |
| M06 | Confirm отправки | `#/work/:resource_id` | `m06` | `dialog` | `performer` | `existing_http_connected` | `existing_http_connected` | M05 |
| M07 | Результат отправлен | `#/work/:resource_id` | `m07` | `state` | `performer` | `ui_local_only` | `existing_http_connected` | M03 |
| M08 | Отказ исполнителя | `#/work/:resource_id` | `m08` | `form` | `performer` | `existing_http_connected` | `existing_http_connected` | M03 |
| M09 | Созданные мной | `#/work` | `m09` | `list` | `creator` | `ui_local_only` | `existing_http_connected` | M01 |
| M10 | Созданное задание / слоты | `#/work/:resource_id` | `m10` | `detail` | `creator` | `ui_local_only` | `existing_http_connected` | M09 |
| M11 | Проверка результата | `#/work/:resource_id` | `m11` | `detail` | `creator/reviewer` | `ui_local_only` | `existing_http_connected` | M10 |
| M12 | Решение по результату | `#/work/:resource_id` | `m12` | `form` | `creator/reviewer` | `existing_http_connected` | `existing_http_connected` | M11 |
| M13 | Решение сохранено | `#/work/:resource_id` | `m13` | `state` | `creator/reviewer` | `ui_local_only` | `existing_http_connected` | M10 |
| M14 | Открытие спора | `#/work/:resource_id` | `m14` | `form` | `performer` | `existing_http_connected` | `existing_http_connected` | M03 |
| M14A | Материалы спора | `#/work/:resource_id` | `m14a` | `list` | `party/staff` | `ui_local_only` | `existing_http_connected` | M14 |
| M15 | Статус спора | `#/work/:resource_id` | `m15` | `detail` | `party` | `ui_local_only` | `existing_http_connected` | M14 |
| M16 | Апелляция | `#/work/:resource_id` | `m16` | `form` | `eligible party` | `disabled_unavailable` | `unavailable_without_fixture` | M15 |
| M17 | Закрытие набора / отмена автора | `#/work/:resource_id` | `m17` | `form` | `creator` | `disabled_unavailable` | `unavailable_without_fixture` | M10 |
| M18 | Ответ на запрос отмены | `#/work/:resource_id` | `m18` | `form` | `performer` | `disabled_unavailable` | `unavailable_without_fixture` | M03 |
| M19 | Статус отмены задания | `#/work/:resource_id` | `m19` | `detail` | `creator/performer` | `ui_local_only` | `unavailable_without_fixture` | M17 |
| P01 | Участники | `#/members` | `p01` | `list` | `member` | `ui_local_only` | `existing_http_connected` | — |
| P02 | Карточка участника | `#/members/:member_id` | `p02` | `detail` | `member` | `ui_local_only` | `existing_http_connected` | P01 |
| P03 | Оценка кармы | `#/members/:member_id` | `p03` | `form` | `eligible` | `existing_http_connected` | `existing_http_connected` | P02 |
| P04 | Карма сохранена | `#/members/:member_id` | `p04` | `state` | `eligible` | `ui_local_only` | `existing_http_connected` | P02 |
| P05 | Лидерборд | `#/members` | `p05` | `list` | `member` | `ui_local_only` | `existing_http_connected` | P01 |
| P06 | Собственный профиль | `#/profile` | `p06` | `detail` | `active/paused` | `ui_local_only` | `existing_http_connected` | — |
| P07 | Редактор профиля | `#/profile` | `p07` | `form` | `owner` | `existing_http_connected` | `existing_http_connected` | P06 |
| P08 | Баланс | `#/profile` | `p08` | `detail` | `owner` | `ui_local_only` | `local_view_state` | P06 |
| P09 | История операций | `#/profile` | `p09` | `list` | `owner` | `ui_local_only` | `unavailable_without_fixture` | P08 |
| P10 | Операция | `#/profile` | `p10` | `detail` | `owner` | `ui_local_only` | `unavailable_without_fixture` | P09 |
| S01 | Очередь кейсов | `#/moderation/:case_id?` | `s01` | `list` | `moderator/admin` | `ui_local_only` | `existing_http_connected` | — |
| S02 | Кейс модерации | `#/moderation/:case_id?` | `s02` | `detail` | `conflict-free staff` | `ui_local_only` | `existing_http_connected` | S01 |
| S03 | Preview решения | `#/moderation/:case_id?` | `s03` | `form` | `conflict-free staff` | `existing_http_connected` | `existing_http_connected` | S02 |
| S04 | Решение сохранено | `#/moderation/:case_id?` | `s04` | `state` | `staff` | `ui_local_only` | `existing_http_connected` | S01 |
| S05 | Очередь регистраций | `#/moderation/:case_id?` | `s05` | `list` | `moderator/admin` | `ui_local_only` | `unavailable_without_fixture` | S01 |
| S06 | Заявка участника | `#/moderation/:case_id?` | `s06` | `detail` | `moderator/admin` | `ui_local_only` | `unavailable_without_fixture` | S05 |
| S07 | Решение по регистрации | `#/moderation/:case_id?` | `s07` | `form` | `moderator/admin` | `disabled_unavailable` | `unavailable_without_fixture` | S06 |
| S08 | Новая санкция | `#/moderation/:case_id?` | `s08` | `form` | `permitted staff` | `disabled_unavailable` | `unavailable_without_fixture` | S01 |
| S09 | Активные санкции | `#/moderation/:case_id?` | `s09` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | S01 |
| S10 | Санкция и история | `#/moderation/:case_id?` | `s10` | `detail` | `permitted staff` | `disabled_unavailable` | `unavailable_without_fixture` | S09 |
| S11 | Оплаченные выполнения | `#/moderation/:case_id?` | `s11` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | S01 |
| S12 | Открытие fraud-case | `#/moderation/:case_id?` | `s12` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | S11 |
| G01 | Hub управления | `#/admin/:resource_type?/:resource_id?` | `g01` | `dashboard` | `admin` | `ui_local_only` | `unavailable_without_fixture` | — |
| G02 | Приглашения | `#/admin/:resource_type?/:resource_id?` | `g02` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G03 | Новое приглашение | `#/admin/:resource_type?/:resource_id?` | `g03` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G02 |
| G04 | Приглашение / использования | `#/admin/:resource_type?/:resource_id?` | `g04` | `detail` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G02 |
| G05 | Управление участниками | `#/admin/:resource_type?/:resource_id?` | `g05` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G06 | Админ-карточка участника | `#/admin/:resource_type?/:resource_id?` | `g06` | `detail` | `admin/member_read` | `ui_local_only` | `unavailable_without_fixture` | G05 |
| G07 | Статус / роль | `#/admin/:resource_type?/:resource_id?` | `g07` | `form` | `admin/super` | `disabled_unavailable` | `unavailable_without_fixture` | G06 |
| G08 | Категории / шаблоны | `#/admin/:resource_type?/:resource_id?` | `g08` | `tabs` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G08A | Категория | `#/admin/:resource_type?/:resource_id?` | `g08a` | `detail` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G08 |
| G08B | Шаблон и версии | `#/admin/:resource_type?/:resource_id?` | `g08b` | `detail` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G08 |
| G09 | Редактор версии шаблона | `#/admin/:resource_type?/:resource_id?` | `g09` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G08B |
| G10 | Все задания / выполнения | `#/admin/:resource_type?/:resource_id?` | `g10` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G11 | Корректировка ledger | `#/admin/:resource_type?/:resource_id?` | `g11` | `form` | `permitted admin` | `disabled_unavailable` | `unavailable_without_fixture` | G06 |
| G12 | Confirm корректировки / reversal | `#/admin/:resource_type?/:resource_id?` | `g12` | `dialog` | `permitted admin` | `disabled_unavailable` | `unavailable_without_fixture` | G11 |
| G13 | Raw-карма | `#/admin/:resource_type?/:resource_id?` | `g13` | `list` | `karma_review` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G14 | Vote и история версий | `#/admin/:resource_type?/:resource_id?` | `g14` | `detail` | `karma_review` | `ui_local_only` | `unavailable_without_fixture` | G13 |
| G14C | Exclude / restore версии кармы | `#/admin/:resource_type?/:resource_id?` | `g14c` | `form` | `karma_review` | `disabled_unavailable` | `unavailable_without_fixture` | G14 |
| G14A | История надёжности | `#/admin/:resource_type?/:resource_id?` | `g14a` | `detail` | `permitted admin` | `ui_local_only` | `unavailable_without_fixture` | G06 |
| G14B | Ledger участника | `#/admin/:resource_type?/:resource_id?` | `g14b` | `list` | `permitted admin` | `ui_local_only` | `unavailable_without_fixture` | G06 |
| G15 | Журнал действий | `#/admin/:resource_type?/:resource_id?` | `g15` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G15A | Запись аудита | `#/admin/:resource_type?/:resource_id?` | `g15a` | `detail` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G15 |
| G16 | Версии конфигурации | `#/admin/:resource_type?/:resource_id?` | `g16` | `list` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G16A | Версия конфигурации | `#/admin/:resource_type?/:resource_id?` | `g16a` | `detail` | `admin` | `ui_local_only` | `unavailable_without_fixture` | G16 |
| G17 | Загрузка и проверка config | `#/admin/:resource_type?/:resource_id?` | `g17` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G16 |
| G18 | Активация конфигурации | `#/admin/:resource_type?/:resource_id?` | `g18` | `dialog` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G16A |
| G19 | Задание сообщества | `#/admin/:resource_type?/:resource_id?` | `g19` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G01 |
| G20 | Preview задания сообщества | `#/admin/:resource_type?/:resource_id?` | `g20` | `detail` | `admin/super` | `disabled_unavailable` | `unavailable_without_fixture` | G19 |
| G21 | Очередь публикаций | `#/admin/:resource_type?/:resource_id?` | `g21` | `list` | `super` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G22 | Подтверждение публикации | `#/admin/:resource_type?/:resource_id?` | `g22` | `detail` | `super` | `disabled_unavailable` | `unavailable_without_fixture` | G21 |
| G22A | Очередь community review | `#/admin/:resource_type?/:resource_id?` | `g22a` | `list` | `independent reviewer` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G22B | Community result review | `#/admin/:resource_type?/:resource_id?` | `g22b` | `detail` | `independent reviewer` | `disabled_unavailable` | `unavailable_without_fixture` | G22A |
| G22C | Замена проверяющего | `#/admin/:resource_type?/:resource_id?` | `g22c` | `form` | `admin` | `disabled_unavailable` | `unavailable_without_fixture` | G22B |
| G22D | Отмена community assignment | `#/admin/:resource_type?/:resource_id?` | `g22d` | `form` | `permitted admin` | `disabled_unavailable` | `unavailable_without_fixture` | G22B |
| G23 | Interaction alerts | `#/admin/:resource_type?/:resource_id?` | `g23` | `list` | `interaction_review` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G23A | Risk signals | `#/admin/:resource_type?/:resource_id?` | `g23a` | `list` | `permitted admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G24 | Interaction alert | `#/admin/:resource_type?/:resource_id?` | `g24` | `detail` | `interaction_review` | `disabled_unavailable` | `unavailable_without_fixture` | G23 |
| G25 | Штраф по алерту | `#/admin/:resource_type?/:resource_id?` | `g25` | `form` | `interaction_review` | `disabled_unavailable` | `unavailable_without_fixture` | G24 |
| G26 | Администраторы | `#/admin/:resource_type?/:resource_id?` | `g26` | `list` | `super` | `disabled_unavailable` | `unavailable_without_fixture` | G01 |
| G27 | Апелляции | `#/admin/:resource_type?/:resource_id?` | `g27` | `list` | `conflict-free admin` | `ui_local_only` | `unavailable_without_fixture` | G01 |
| G28 | Решение по апелляции | `#/admin/:resource_type?/:resource_id?` | `g28` | `detail` | `conflict-free admin` | `disabled_unavailable` | `unavailable_without_fixture` | G27 |

## Переходы

| ID | Source | Trigger | Target route/view | State | History | Scope | Guard |
|---|---|---|---|---|---|---|---|
| PE-001 | A01/`a01` | `auth_failure` | A02 `#/start`/`a02` | `error` | `replace` | `production_ui_local` | `auth_state` |
| PE-002 | A01/`a01` | `valid_invitation` | A03 `#/start`/`a03` | `content` | `replace` | `production_ui_local` | `invitation_present` |
| PE-003 | A01/`a01` | `restricted_status` | A07 `#/start`/`a07` | `permission_closed` | `replace` | `production_ui_local` | `status_restricted` |
| PE-004 | A01/`a01` | `active_member` | T01 `#/catalog`/`t01` | `loading` | `replace` | `production_ui_local` | `member_active` |
| PE-005 | A03/`a03` | `continue` | A04 `#/start`/`a04` | `content` | `push` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-006 | A04/`a04` | `accept_consent` | A05 `#/start`/`a05` | `content` | `push` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-007 | A05/`a05` | `preview_application` | A05A `#/start`/`a05a` | `content` | `push` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-008 | A05A/`a05a` | `submit_application` | A06 `#/start`/`a06` | `success` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-009 | A06/`a06` | `registration_approved` | T01 `#/catalog`/`t01` | `loading` | `replace` | `production_ui_local` | `fresh_status` |
| PE-010 | A06/`a06` | `registration_rejected` | A06A `#/start`/`a06a` | `content` | `replace` | `production_ui_local` | `fresh_status` |
| PE-011 | A06A/`a06a` | `reopen_application` | A05 `#/start`/`a05` | `content` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-012 | T01/`t01` | `open_filters` | T02 `#/catalog`/`t02` | `content` | `push` | `production_ui_local` | `local_navigation` |
| PE-013 | T01/`t01` | `open_task` | T03 `#/tasks/:task_id`/`t03` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-014 | T01/`t01` | `create_task` | T04 `#/compose/tasks/:draft_id?`/`t04` | `content` | `push` | `production_ui_local` | `member_active` |
| PE-015 | T03/`t03` | `accept_task` | T03A `#/tasks/:task_id`/`t03a` | `confirm` | `push` | `production_ui_local` | `action_available` |
| PE-016 | T04/`t04` | `choose_template_path` | T04A `#/compose/tasks/:draft_id?`/`t04a` | `content` | `push` | `production_ui_local` | `local_navigation` |
| PE-017 | T04/`t04` | `resume_draft_path` | T04B `#/compose/tasks/:draft_id?`/`t04b` | `content` | `push` | `production_ui_local` | `local_navigation` |
| PE-018 | T04A/`t04a` | `use_template_or_freeform` | T05 `#/compose/tasks/:draft_id?`/`t05` | `content` | `push` | `production_ui_local` | `local_navigation` |
| PE-019 | T04B/`t04b` | `resume_draft` | T05 `#/compose/tasks/:draft_id?`/`t05` | `content` | `push` | `production_ui_local` | `local_navigation` |
| PE-020 | T05/`t05` | `preview_task` | T06 `#/compose/tasks/:draft_id?`/`t06` | `content` | `push` | `production_ui_local` | `valid_local_form` |
| PE-021 | T06/`t06` | `publish_task` | T07 `#/compose/tasks/:draft_id?`/`t07` | `confirm` | `push` | `production_ui_local` | `action_available` |
| PE-022 | T07/`t07` | `authoritative_publish_success` | T08 `#/compose/tasks/:draft_id?`/`t08` | `success` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-023 | T08/`t08` | `open_published_task` | M10 `#/work/:resource_id`/`m10` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-024 | T03A/`t03a` | `authoritative_accept_success` | M03 `#/work/:resource_id`/`m03` | `loading` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-025 | M01/`m01` | `open_accepted_tab` | M02 `#/work`/`m02` | `content` | `stay` | `production_ui_local` | `local_navigation` |
| PE-026 | M01/`m01` | `open_created_tab` | M09 `#/work`/`m09` | `content` | `stay` | `production_ui_local` | `local_navigation` |
| PE-027 | M02/`m02` | `open_assignment` | M03 `#/work/:resource_id`/`m03` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-028 | M03/`m03` | `create_or_extend_submission` | M04 `#/work/:resource_id`/`m04` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-029 | M03/`m03` | `withdraw_assignment` | M08 `#/work/:resource_id`/`m08` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-030 | M04/`m04` | `open_result_versions` | M04A `#/work/:resource_id`/`m04a` | `content` | `push` | `production_existing_api` | `versions_available` |
| PE-031 | M04A/`m04a` | `continue_submission` | M04 `#/work/:resource_id`/`m04` | `content` | `pop` | `production_ui_local` | `local_navigation` |
| PE-032 | M04/`m04` | `preview_result` | M05 `#/work/:resource_id`/`m05` | `content` | `push` | `production_ui_local` | `valid_local_form` |
| PE-033 | M05/`m05` | `submit_result` | M06 `#/work/:resource_id`/`m06` | `confirm` | `push` | `production_ui_local` | `action_available` |
| PE-034 | M06/`m06` | `authoritative_submit_success` | M07 `#/work/:resource_id`/`m07` | `success` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-035 | M07/`m07` | `open_assignment` | M03 `#/work/:resource_id`/`m03` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-036 | M08/`m08` | `withdrawal_outcome` | M02 `#/work`/`m02` | `loading` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-037 | M09/`m09` | `open_created_task` | M10 `#/work/:resource_id`/`m10` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-038 | M10/`m10` | `open_review` | M11 `#/work/:resource_id`/`m11` | `loading` | `push` | `production_ui_local` | `review_available` |
| PE-039 | M11/`m11` | `choose_review_decision` | M12 `#/work/:resource_id`/`m12` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-040 | M12/`m12` | `authoritative_review_success` | M13 `#/work/:resource_id`/`m13` | `success` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-041 | M13/`m13` | `open_created_task` | M10 `#/work/:resource_id`/`m10` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-042 | M13/`m13` | `open_assignment` | M03 `#/work/:resource_id`/`m03` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-043 | M13/`m13` | `open_reject_dispute` | M14 `#/work/:resource_id`/`m14` | `content` | `push` | `production_ui_local` | `rejected_outcome` |
| PE-044 | M14/`m14` | `open_dispute_materials` | M14A `#/work/:resource_id`/`m14a` | `content` | `push` | `production_existing_api` | `resource_available` |
| PE-045 | M14A/`m14a` | `open_dispute_status` | M15 `#/work/:resource_id`/`m15` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-046 | M15/`m15` | `open_appeal` | M16 `#/work/:resource_id`/`m16` | `content` | `push` | `production_ui_local` | `appeal_available` |
| PE-047 | M16/`m16` | `submit_appeal` | G27 `#/admin/:resource_type?/:resource_id?`/`g27` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-048 | G27/`g27` | `open_appeal` | G28 `#/admin/:resource_type?/:resource_id?`/`g28` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-049 | G28/`g28` | `open_dispute_outcome` | M15 `#/work/:resource_id`/`m15` | `loading` | `replace` | `dev_test_fixture_only` | `resource_available` |
| PE-050 | G28/`g28` | `open_assignment_outcome` | M03 `#/work/:resource_id`/`m03` | `loading` | `replace` | `dev_test_fixture_only` | `resource_available` |
| PE-051 | M10/`m10` | `request_group_cancellation` | M17 `#/work/:resource_id`/`m17` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-052 | M17/`m17` | `notify_performer_response` | M18 `#/work/:resource_id`/`m18` | `content` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-053 | M18/`m18` | `save_cancellation_response` | M19 `#/work/:resource_id`/`m19` | `content` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-054 | M19/`m19` | `open_created_task_outcome` | M10 `#/work/:resource_id`/`m10` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-055 | M19/`m19` | `open_assignment_outcome` | M03 `#/work/:resource_id`/`m03` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-056 | P01/`p01` | `open_member` | P02 `#/members/:member_id`/`p02` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-057 | P01/`p01` | `open_leaderboard` | P05 `#/members`/`p05` | `loading` | `stay` | `production_ui_local` | `local_navigation` |
| PE-058 | P02/`p02` | `rate_karma` | P03 `#/members/:member_id`/`p03` | `content` | `push` | `production_ui_local` | `karma_eligible` |
| PE-059 | P03/`p03` | `authoritative_karma_success` | P04 `#/members/:member_id`/`p04` | `success` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-060 | P04/`p04` | `return_to_member` | P02 `#/members/:member_id`/`p02` | `loading` | `replace` | `production_ui_local` | `resource_available` |
| PE-061 | P06/`p06` | `edit_profile` | P07 `#/profile`/`p07` | `content` | `push` | `production_ui_local` | `self` |
| PE-062 | P06/`p06` | `open_balance` | P08 `#/profile`/`p08` | `content` | `push` | `production_ui_local` | `self` |
| PE-063 | P07/`p07` | `authoritative_profile_success` | P06 `#/profile`/`p06` | `loading` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-064 | P08/`p08` | `open_ledger` | P09 `#/profile`/`p09` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-065 | P09/`p09` | `open_operation` | P10 `#/profile`/`p10` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-066 | S01/`s01` | `open_case` | S02 `#/moderation/:case_id?`/`s02` | `loading` | `push` | `production_ui_local` | `case_available` |
| PE-067 | S02/`s02` | `preview_resolution` | S03 `#/moderation/:case_id?`/`s03` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-068 | S03/`s03` | `authoritative_resolution_success` | S04 `#/moderation/:case_id?`/`s04` | `success` | `replace` | `production_existing_api` | `authoritative_outcome` |
| PE-069 | S04/`s04` | `return_to_case_queue` | S01 `#/moderation/:case_id?`/`s01` | `loading` | `replace` | `production_ui_local` | `staff_allowed` |
| PE-070 | S01/`s01` | `open_registration_queue` | S05 `#/moderation/:case_id?`/`s05` | `loading` | `stay` | `production_ui_local` | `staff_allowed` |
| PE-071 | S05/`s05` | `open_application` | S06 `#/moderation/:case_id?`/`s06` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-072 | S06/`s06` | `choose_registration_decision` | S07 `#/moderation/:case_id?`/`s07` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-073 | S07/`s07` | `registration_decision_outcome` | S05 `#/moderation/:case_id?`/`s05` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-074 | S01/`s01` | `open_paid_assignments` | S11 `#/moderation/:case_id?`/`s11` | `loading` | `stay` | `production_ui_local` | `admin_allowed` |
| PE-075 | S11/`s11` | `open_fraud_case` | S12 `#/moderation/:case_id?`/`s12` | `content` | `push` | `production_ui_local` | `resource_available` |
| PE-076 | S12/`s12` | `fraud_case_created` | S02 `#/moderation/:case_id?`/`s02` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-077 | G06/`g06` | `issue_sanction` | S08 `#/moderation/:case_id?`/`s08` | `content` | `push` | `production_ui_local` | `sanction_allowed` |
| PE-078 | S02/`s02` | `issue_case_sanction` | S08 `#/moderation/:case_id?`/`s08` | `content` | `push` | `production_ui_local` | `sanction_allowed` |
| PE-079 | S08/`s08` | `sanction_saved_to_list` | S09 `#/moderation/:case_id?`/`s09` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-080 | S08/`s08` | `sanction_saved_to_detail` | S10 `#/moderation/:case_id?`/`s10` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-081 | S09/`s09` | `open_sanction` | S10 `#/moderation/:case_id?`/`s10` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-082 | G01/`g01` | `open_invitations` | G02 `#/admin/:resource_type?/:resource_id?`/`g02` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-083 | G02/`g02` | `create_invitation` | G03 `#/admin/:resource_type?/:resource_id?`/`g03` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-084 | G02/`g02` | `open_invitation` | G04 `#/admin/:resource_type?/:resource_id?`/`g04` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-085 | G01/`g01` | `open_member_admin` | G05 `#/admin/:resource_type?/:resource_id?`/`g05` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-086 | G05/`g05` | `open_admin_member` | G06 `#/admin/:resource_type?/:resource_id?`/`g06` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-087 | G06/`g06` | `change_role_or_status` | G07 `#/admin/:resource_type?/:resource_id?`/`g07` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-088 | G01/`g01` | `open_catalog_admin` | G08 `#/admin/:resource_type?/:resource_id?`/`g08` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-089 | G08/`g08` | `open_category` | G08A `#/admin/:resource_type?/:resource_id?`/`g08a` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-090 | G08/`g08` | `open_template` | G08B `#/admin/:resource_type?/:resource_id?`/`g08b` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-091 | G08B/`g08b` | `create_template_version` | G09 `#/admin/:resource_type?/:resource_id?`/`g09` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-092 | G01/`g01` | `open_all_tasks` | G10 `#/admin/:resource_type?/:resource_id?`/`g10` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-093 | G06/`g06` | `correct_member_ledger` | G11 `#/admin/:resource_type?/:resource_id?`/`g11` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-094 | G14B/`g14b` | `correct_ledger` | G11 `#/admin/:resource_type?/:resource_id?`/`g11` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-095 | G11/`g11` | `preview_ledger_change` | G12 `#/admin/:resource_type?/:resource_id?`/`g12` | `confirm` | `push` | `production_ui_local` | `valid_local_form` |
| PE-096 | G12/`g12` | `ledger_change_outcome` | G14B `#/admin/:resource_type?/:resource_id?`/`g14b` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-097 | G01/`g01` | `open_raw_karma` | G13 `#/admin/:resource_type?/:resource_id?`/`g13` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-098 | G13/`g13` | `open_karma_vote` | G14 `#/admin/:resource_type?/:resource_id?`/`g14` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-099 | G14/`g14` | `moderate_karma_version` | G14C `#/admin/:resource_type?/:resource_id?`/`g14c` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-100 | G06/`g06` | `open_reliability_history` | G14A `#/admin/:resource_type?/:resource_id?`/`g14a` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-101 | G06/`g06` | `open_member_ledger` | G14B `#/admin/:resource_type?/:resource_id?`/`g14b` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-102 | G01/`g01` | `open_audit` | G15 `#/admin/:resource_type?/:resource_id?`/`g15` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-103 | G15/`g15` | `open_audit_record` | G15A `#/admin/:resource_type?/:resource_id?`/`g15a` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-104 | G01/`g01` | `open_config_versions` | G16 `#/admin/:resource_type?/:resource_id?`/`g16` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-105 | G16/`g16` | `open_config_version` | G16A `#/admin/:resource_type?/:resource_id?`/`g16a` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-106 | G16/`g16` | `upload_config` | G17 `#/admin/:resource_type?/:resource_id?`/`g17` | `content` | `push` | `production_ui_local` | `action_available` |
| PE-107 | G16A/`g16a` | `activate_config` | G18 `#/admin/:resource_type?/:resource_id?`/`g18` | `confirm` | `push` | `production_ui_local` | `action_available` |
| PE-108 | G17/`g17` | `activate_validated_config` | G18 `#/admin/:resource_type?/:resource_id?`/`g18` | `confirm` | `push` | `production_ui_local` | `valid_local_form` |
| PE-109 | G01/`g01` | `create_community_task` | G19 `#/admin/:resource_type?/:resource_id?`/`g19` | `content` | `push` | `production_ui_local` | `capability_visible` |
| PE-110 | G19/`g19` | `preview_community_task` | G20 `#/admin/:resource_type?/:resource_id?`/`g20` | `content` | `push` | `production_ui_local` | `valid_local_form` |
| PE-111 | G20/`g20` | `super_publish_success` | T03 `#/tasks/:task_id`/`t03` | `loading` | `replace` | `dev_test_fixture_only` | `super_allowed` |
| PE-112 | G20/`g20` | `request_super_approval` | G21 `#/admin/:resource_type?/:resource_id?`/`g21` | `loading` | `replace` | `dev_test_fixture_only` | `admin_not_super` |
| PE-113 | G21/`g21` | `open_publication_request` | G22 `#/admin/:resource_type?/:resource_id?`/`g22` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-114 | G22/`g22` | `publication_approved` | T03 `#/tasks/:task_id`/`t03` | `loading` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-115 | G01/`g01` | `open_community_reviews` | G22A `#/admin/:resource_type?/:resource_id?`/`g22a` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-116 | G22A/`g22a` | `open_community_result` | G22B `#/admin/:resource_type?/:resource_id?`/`g22b` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-117 | G22B/`g22b` | `choose_community_decision` | M12 `#/work/:resource_id`/`m12` | `content` | `push` | `dev_test_fixture_only` | `action_available` |
| PE-118 | G22B/`g22b` | `open_community_outcome` | M13 `#/work/:resource_id`/`m13` | `success` | `replace` | `dev_test_fixture_only` | `authoritative_or_fixture_outcome` |
| PE-119 | G22B/`g22b` | `replace_invalid_reviewer` | G22C `#/admin/:resource_type?/:resource_id?`/`g22c` | `content` | `push` | `dev_test_fixture_only` | `reviewer_invalid` |
| PE-120 | G22B/`g22b` | `cancel_community_assignment` | G22D `#/admin/:resource_type?/:resource_id?`/`g22d` | `content` | `push` | `dev_test_fixture_only` | `action_available` |
| PE-121 | G01/`g01` | `open_interaction_alerts` | G23 `#/admin/:resource_type?/:resource_id?`/`g23` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-122 | G01/`g01` | `open_risk_signals` | G23A `#/admin/:resource_type?/:resource_id?`/`g23a` | `loading` | `push` | `production_ui_local` | `capability_visible` |
| PE-123 | G23/`g23` | `open_interaction_alert` | G24 `#/admin/:resource_type?/:resource_id?`/`g24` | `loading` | `push` | `production_ui_local` | `resource_available` |
| PE-124 | G24/`g24` | `save_legitimate_or_monitor_outcome` | G24 `#/admin/:resource_type?/:resource_id?`/`g24` | `content` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-125 | G24/`g24` | `choose_penalty` | G25 `#/admin/:resource_type?/:resource_id?`/`g25` | `content` | `push` | `dev_test_fixture_only` | `penalty_outcome_selected` |
| PE-126 | G25/`g25` | `penalty_outcome_saved` | G24 `#/admin/:resource_type?/:resource_id?`/`g24` | `content` | `replace` | `dev_test_fixture_only` | `fixture_or_connection` |
| PE-127 | G01/`g01` | `open_administrators` | G26 `#/admin/:resource_type?/:resource_id?`/`g26` | `loading` | `push` | `production_ui_local` | `super_allowed` |
| PE-128 | G01/`g01` | `open_appeals` | G27 `#/admin/:resource_type?/:resource_id?`/`g27` | `loading` | `push` | `production_ui_local` | `capability_visible` |

## No-UI

| ID | Механизм | Причина |
|---|---|---|
| N01 | Transactional outbox / worker (`no_ui`) | внутренняя доставка/retry/lease |
| N02 | Idempotency receipts / operations (`no_ui`) | exact replay guarantee |
| N03 | Raw audit/ledger/outbox payload (`no_ui`) | только безопасные проекции в UI |
| N04 | Generic member chat (`no_ui`) | нет product surface |
| N05 | Manual notification composer (`no_ui`) | нет ручной рассылки |
| N06 | Автоматическое наказание (`no_ui`) | требуется human decision |
| N07 | Raw karma for moderator (`no_ui`) | только admin + karma_review |
| N08 | Direct balance/reliability edit (`no_ui`) | только journaled correction/outcome |
| N09 | Public browser registration (`no_ui`) | Telegram invitation/auth only |
| N10 | In-app notification inbox/read state (`no_ui`) | Telegram outbound + target deep link |
| N11 | Initial administrator bootstrap (`no_ui`) | не продуктовый UI |
| N12 | Test-run orchestration (`no_ui`) | в UI только маркер ТЕСТ и scope |
| N13 | Health/heartbeat/reconciliation (`no_ui`) | не пользовательская поверхность |
| N14 | Прямые переводы кредитов (`no_ui`) | нет доменной операции |
| N15 | Автоматическое назначение задач (`no_ui`) | участник принимает добровольно |
| N16 | Публикация user templates (`no_ui`) | шаблоны управляются admin |
| N17 | Raw safety snapshot / private notes (`no_ui`) | только permission-safe projection |
