# CB-10 — plan review, попытка 1

Status: changes_requested

## Обязательные замечания

1. Не была определена единая caller-owned UoW граница для повторной проверки
   каталога и draft-мутаций; `CatalogService.for_creation` открывал бы nested
   transaction, а empty `EconomyMutationPort.prepare_batch` запрещён.
2. Cancellation и acceptance требовали assignment-aware данных, хотя таблица
   assignments явно оставалась CB-11.
3. Сценарий двух разных publish keys одного автора был недостижим при одном
   active draft и одном стабильном command ID.

## Результат попытки

Пакет был исправлен одним проходом: добавлены caller-owned catalog primitives и
раздельные lock paths; assignment-aware часть перенесена в CB-11; разрешены
несколько долговечных drafts при одном current и публичный resume.
