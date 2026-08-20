# CB-96 — утверждённый дизайн-пакет концепции 05

Эта папка хранит неизменяемый вход реализации CB-96. Источник — утверждённый
владельцем UI-план CB-93 от 2026-08-19. Production UI обязан следовать
фактическому application/domain contract; при расхождении визуальный макет не
создаёт новое поле или правило.

## Нормативные документы

- `cb93-ui-plan-v5.md` — решения, screen inventory и navigation contract;
- `cb93-contract-coverage-v5.md` — поля движка, 26/26 capability mapping и
  no-UI границы;
- `cb93-complete-screen-board.html` — 103 UI-поверхности и 17 no-UI
  dispositions;
- `cb93-transition-map.html` — карта основных переходов;
- `cb93-contract-coverage-v5.html` — визуальная contract coverage;
- `cb93-mockups.html` — исходник мобильных mockups.
- `capture_complete_plan.py` — воспроизводимая пересборка трёх полных PNG из
  task-local HTML без изменения production UI.

## Скриншоты для Jira и owner review

- `cb93-v5-complete-screen-board.png` — полный screen board;
- `cb93-v5-transition-map.png` — полная карта переходов;
- `cb93-v5-contract-coverage.png` — поля и механизмы движка;
- `cb93-v5-key-screens-board.png` — основные экраны;
- `cb93-v5-navigation.png`, `cb93-v5-components.png`, `cb93-v5-states.png` —
  навигация, компоненты и системные состояния;
- `cb93-v5-catalog.png`, `cb93-v5-assignments.png`, `cb93-v5-profile.png`,
  `cb93-v5-members.png`, `cb93-v5-member-profile.png`,
  `cb93-v5-leaderboard.png`, `cb93-v5-moderation.png` — экранные группы;
- `cb93-v5-creation-1.png` и `cb93-v5-creation-2.png` — полный длинный экран
  создания задания в двух частях;
- `cb93-v5-task-1.png` и `cb93-v5-task-2.png` — полная карточка задания в двух
  частях.

После первого push ссылки на эти файлы добавляются в CB-96. До push локальные
пути не выдаются за доступные Jira-вложения.
