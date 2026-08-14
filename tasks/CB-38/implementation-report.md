# CB-38 - отчет о реализации

## Статус

Локальная реализация завершена. Branch protection и protected Environment настроены.
Внешние gates PR CI, merge, release, production deploy и живая Telegram-приемка на этом
этапе еще не закрыты.

## Что изменено

- Fast lane `1B` больше не создает отдельные план/отчет/тяжелое review и не останавливает
  реализацию на показе compact bugfix note.
- Прямое поручение на реализацию синхронно закреплено как standing intent для штатной
  цепочки Jira -> branch -> PR -> checked merge -> release -> deploy с fail-closed
  остановками и отдельными Telegram/Done ограничениями.
- Полный CI оставлен на PR; итоговый check публикует PR/base/head/merge/tree provenance.
- Release на `push main` допускает build только при единственном точном provenance match.
- Добавлен SSH deploy с protected Environment approval, pinned host key и отдельным
  forced-command key.
- Forced-command entrypoint ограничивает repository/digest/аргументы, сериализует deploy
  и отклоняет старую или повторную пару workflow run number/attempt. Entrypoint вызывает
  только root-owned `shared/bin/deploy_self_hosted.sh` после точной проверки ownership,
  mode `0700` и отсутствия symlink для всей доверенной цепочки.
- Runtime получает identity `digest + run number/attempt`; worker/bot пересоздаются, а
  readiness требует эту identity и heartbeat после наносекундного post-recreate порога.
- Runbook описывает branch protection, merge-only policy, секреты и server setup.

## Критерии приемки и доказательства

- Один полный CI: workflow `CI` содержит только `pull_request`; production-доказательство
  будет получено на PR.
- Проверенный код равен release: `Verified merge tree` и
  `ops/verify_release_provenance.py` связывают PR/base/head/tree/run; unit-тесты проверяют
  точное и неоднозначное сопоставление.
- Безопасный deploy: parser принимает только exact immutable command; mutable tag, другой
  repository, лишний аргумент, shell-разделитель и malformed run отклоняются.
- Старый runtime не закрывает readiness: PostgreSQL integration test подтвердил коды
  `heartbeat_release_mismatch` и `heartbeat_before_deploy`.
- Migration/product-config/outbox gates и ручной rollback сохранены в существующем
  `deploy_self_hosted.sh` и runbook.
- Два Telegram-профиля доступны по безопасному probe; live-сценарии выполняются только
  после deployment проверенного release.

## Выполненные проверки

- `uv run ruff format --check .` - passed, 423 files.
- `uv run ruff check .` - passed.
- `uv run ty check src tests ops/verify_release_provenance.py` - passed.
- `uv run pytest -m "not integration" --no-cov -q` - 285 passed, 1 Linux-only
  marker/flock test skipped локально, 162 deselected.
- Targeted operational tests - 24 passed; Linux-only marker/flock behavior отдельно
  выполнен в локальном Linux-контейнере.
- PostgreSQL readiness integration - 1 passed.
- `bash -n ops/deploy_self_hosted.sh ops/github_deploy_entrypoint.sh` - passed через
  Git for Windows Bash.
- YAML parse и `docker compose config --quiet` - passed.
- `git diff --check` - passed.
- Secret pattern scan по tracked и untracked области - совпадений не найдено.
- Linux container behavior test - два последовательных deploy разрешены, duplicate и
  stale пары отклонены с code 3, mode `0777` отклонен с code 1, marker и уникальная
  runtime identity подтверждены.
- GitHub `main` protection включена: strict App-bound checks, PR, enforce admins,
  conversation resolution, запрет force push/deletion; разрешены только merge commits.
- Environment `production` создан с required reviewer, protected-branch policy и без
  admin bypass.

## Еще обязательные внешние проверки

- Независимый final review уровня 3.
- PR CI с тремя зелеными checks.
- Установка отдельного deploy key/entrypoint и GitHub secrets без вывода значений.
- Merge, provenance release, Environment approval, production deploy и health/outbox check.
- Два живых Telegram-сценария отмены между `default` и `tg-test` с cleanup.

## Остаточный риск

Первый production запуск нового workflow одновременно является проверкой реального
GitHub artifact API и forced-command SSH boundary. Любое несовпадение или отсутствие
секрета завершает workflow до изменения runtime; обход gate не допускается.
