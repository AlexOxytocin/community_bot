# CB-13 — решения владельца перед реализацией

Status: accepted

Владелец подтвердил весь пакет P-001–P-003 11 августа 2026 года. Ниже
зафиксированы принятые правила MVP, а не предложения.

Ниже один согласованный пакет правил MVP.

## P-001. Полномочия

Принято:

- active moderator и active administrator без конфликта интересов разрешают
  спор и создают `notice|warning|restriction|suspension`;
- только active administrator рассматривает апелляцию, создаёт/revokes `ban`,
  выполняет fraud reversal и закрывает interaction alert с penalty;
- interaction alert и penalty дополнительно требуют `interaction_review`;
  raw karma остаётся только у administrator с `karma_review`.

## P-002. Исходы спора

Принято:

| Код | Assignment | Экономика | Надёжность |
|---|---|---|---|
| `full_payment` | `approved` | полная выплата | `approved` |
| `partial_payment` | `partially_approved` | `ceil(50%)`, остаток автору | `partially_approved` |
| `full_refund` | `rejected` | полный refund / без community issuance | `rejected` |
| `cancel_without_fault` | `cancelled` | полный refund / без issuance | `responsibility_excused` |
| `performer_no_show` | `no_show` | полный refund / без issuance | `no_show` |
| `creator_abuse` | `approved` | полная выплата исполнителю | `approved` + risk signal автору |
| `fraud` | `rejected` | refund либо exact reversal ранее выплаченного | `rejected` + risk signal сторонам |

Апелляция — одна новая append-only resolution в течение семи дней. Она точно
реверсирует экономические эффекты предыдущего решения и применяет новый исход
одной транзакцией; прежние audit/resolution строки не меняются.

## P-003. Karma risk signals

Принято автоматически создавать только приватный сигнал, без санкции:

- взаимные `-1`, если между парой есть спор;
- три и более текущих `-1` одному target за rolling 24 часа;
- три одинаковых нормализованных отрицательных комментария от разных авторов за
  rolling 24 часа.

Повтор одного правила в одном временном bucket идемпотентен. Исключение оценки
из aggregate и ограничение голосования выполняет только administrator с
`karma_review`, с причиной, аудитом и возможностью восстановления.
