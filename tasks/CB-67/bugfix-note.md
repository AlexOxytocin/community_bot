# CB-67 — Telegram launcher Mini App

## Симптом

`@humanquest_bot` существует и его токен действителен, но default menu button
имеет тип `commands`, список команд пуст, а inbound runtime намеренно удалён.
Пользователь не получает рабочую точку запуска Mini App.

## Причина

CB-57 развернула web release, но не настроила отдельное persistent Bot API
состояние бота. Старый long-polling runtime был корректно удалён ADR-0016 и не
должен восстанавливаться ради launcher.

## Правка

Однократно и идемпотентно назначить default `MenuButtonWebApp` через
`setChatMenuButton`:

- text: `Открыть приложение`;
- url: `https://allo.godmodetools.com/mini-app`.

Не добавлять `/start`, webhook, polling, bot-process, callback UI, зависимости
или новый production release. Существующие pending updates не читать и не
удалять.

## Проверка

Выполнено без вывода токена и чтения Telegram-сообщений:

- Bot API preflight: username `humanquest_bot`, menu button `commands`, commands
  пусты, webhook отсутствует, pending updates — `4`;
- exact `setChatMenuButton` через установленный production aiogram выполнен
  дважды; оба readback вернули один и тот же `MenuButtonWebApp` с утверждённым
  текстом и URL;
- итоговый readback: commands пусты, webhook отсутствует, pending updates
  остались `4` и не читались/не удалялись;
- public smoke: `/` — `200`, `/mini-app` — `200`, `/readyz` — `200`,
  `/api/v1/me` без Telegram session — `401`.

Остаётся ручной live gate: открыть menu button в `@humanquest_bot` на
собственном Telegram-профиле и подтвердить server-side auth handshake без
чтения сообщений.

## Риск

Bot API menu button является внешней конфигурацией и не версионируется вместе с
image. Для текущего одного pilot это осознанно проще нового deploy/config
framework; повторная настройка нужна только при смене bot token или Mini App URL.
