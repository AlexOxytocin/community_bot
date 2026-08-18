# CB-53 — post-escalation planning checkpoint

## Причина

Два review выявили security/contract gaps: transaction replay/audit/browser
proof, затем неисполнимую fine-grained error taxonomy, external material links
и неполную wire precedence. Runtime не начинался.

## Owner decision

Владелец подтвердил: one privacy-safe `409 assignment_unavailable`; literal
materials/no links; canonical positive int64 key и fixed precedence; DTO
enrichment/no detail owner; raw key запрещён. Первоначальная actor-only
derivation была отклонена review и заменена ниже owner-authorized
command/actor/task/key contract; zero domain rewrite/new receipt table/framework.

## Consolidated correction

`plan.md` заменён единым executable contract. Удалены HTTP receipt
table/fingerprint, exact domain 403/404 distinctions и dynamic links. Добавлены
precedence, cross-actor privacy, receipt-first status-change replay, literal-XSS
oracle и machine-checkable route/schema/domain gates.

## Terminal gate

Предыдущий post-escalation recheck завершился `changes_requested` и вызвал
owner resolution ниже; runtime тогда не начинался.

## Owner-authorized resolution после terminal review

Jira comment `10243` разрешает ещё один independent full recheck и фиксирует
минимальный hardening без новой architecture:

- operation ID включает length-encoded `accept/member/task/key`;
- replay возвращается только после exact assignment actor/task match;
- unique assignment `(task_id, performer_id)` используется как natural
  idempotency resource под existing gates; active row возвращается без effects,
  terminal/cancelled не реанимируется;
- concurrent different keys не используют unique violation как normal flow;
- malformed persisted public allowlist fail closed в empty projection.

Это transport/mechanical owner hardening; Category C business outcome changes
остаётся zero. Новый table/service/framework/ADR не добавляется. Один
owner-authorized independent recheck является terminal gate: exact `approved`
открывает runtime, иной verdict останавливает работу.
