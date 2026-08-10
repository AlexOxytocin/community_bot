# CB-8 — отчёт о реализации

## Результат

Реализован цельный сценарий MVP: администратор создаёт и отзывает приглашение,
приглашённый участник проходит возобновляемую регистрацию, модератор или
администратор рассматривает заявку, а при первом одобрении участник атомарно
получает активный статус и единственный стартовый грант `+5` кредитов и `+0`
опыта. Активный участник может открыть и изменить только собственный профиль.

## Выполненные критерии Jira

| Критерий | Реализация | Воспроизводимое доказательство |
|---|---|---|
| Регистрация доступна только по приглашению | Токен создаёт только активный администратор; в БД и аудите хранится только необратимый hash; поддержаны срок, лимит, intended Telegram ID и отзыв | `test_invitation_is_hashed_and_concurrent_last_use_is_atomic`, `test_invitation_replay_revoke_and_pending_access_rules` |
| Повторный `/start` продолжает регистрацию | Состояние и payload FSM хранятся в PostgreSQL; update gate дополнен identity gate и `expected_step`; `/cancel` приостанавливает диалог без удаления черновика | `test_different_concurrent_starts_for_same_identity_create_one_member`, `test_restart_resumes_step_and_username_change_keeps_member_identity`, `test_stale_expected_step_does_not_pollute_next_answer`, `test_complete_synthetic_telegram_registration_and_profile_smoke` |
| До одобрения нет прав активного участника | Созданный участник имеет статус `pending`; просмотр профильного меню и активные права серверно запрещены | `test_invitation_replay_revoke_and_pending_access_rules` |
| Заявку рассматривает moderator/admin | Разделены права управления приглашениями и модерации; поддельное или неавторизованное действие не создаёт эффектов | `test_invitation_and_moderation_authorization_are_distinct`, `test_concurrent_moderation_creates_one_grant_and_active_profile` |
| Первое одобрение выдаёт ровно один стартовый грант | Публичный `prepare_batch` удерживает economy gates и полный набор member-locks до авторизации; статус, аудит, receipt и ledger фиксируются одним commit | `test_concurrent_moderation_creates_one_grant_and_active_profile`, `test_fault_after_grant_flush_rolls_back_full_approval`, `test_reject_resubmit_approve_and_edit_own_profile` |
| Смена Telegram username не создаёт новый аккаунт | Идентичность основана на полном `telegram_user_id`; username обновляется у существующего UUID | `test_restart_resumes_step_and_username_change_keeps_member_identity` |
| Участник видит и редактирует собственный профиль | Реализованы `/profile`, callback редактирования всех полей и серверная проверка владельца/active-статуса; чужие профили не открыты до решения Q-011 | `test_reject_resubmit_approve_and_edit_own_profile`, `test_complete_synthetic_telegram_registration_and_profile_smoke` |

## Данные и интерфейс

- миграция `0004` добавляет invitations, redemptions, registration applications,
  conversation states и недостающие поля профиля;
- категории помощи и теги навыков временно сохраняются нормализованными JSON-
  снимками до реализации управляемого каталога в CB-9;
- Telegram router покрывает `/start`, управление приглашениями, очередь
  модерации, отклонение, одобрение и собственный профиль;
- для IANA timezone добавлен воспроизводимый пакет `tzdata`; секрет подписи
  invite поступает только через `INVITE_TOKEN_SECRET` и не имеет значения по
  умолчанию.

## Проверки готового кода

Выполнен единый целевой контур CB-8 и непосредственно затронутых общих
контрактов:

```text
uv run pytest -q --no-cov \
  tests/unit/test_registration_domain.py \
  tests/unit/test_member_domain.py \
  tests/unit/test_economy_domain.py \
  tests/integration/test_member_foundation.py \
  tests/integration/test_economy.py \
  tests/integration/test_economy_extended.py \
  tests/integration/test_registration.py \
  tests/architecture/test_import_boundaries.py \
  tests/unit/test_settings.py \
  tests/unit/test_member_transport.py

204 passed, 0 skipped, 0 deselected
```

Дополнительно успешно выполнены:

- `uv run ruff format --check .` — 152 файла без изменений;
- `uv run ruff check .`;
- `uv run ty check`;
- миграционный цикл `0003 → 0004 → 0003 → 0004` внутри PostgreSQL integration;
- полный synthetic aiogram smoke без сетевого Bot API;
- `git diff --check`.

Полная регрессия продукта намеренно не дублируется в CB-8: по принятому
процессу она выполняется отдельной задачей CB-16 после завершения функционала
MVP. Дефекты, найденные в ходе реализации и целевого прогона, исправлены в этой
же ветке.
