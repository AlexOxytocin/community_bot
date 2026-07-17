# Community Bot Workspace Instructions

## Project purpose

- This workspace contains the Telegram bot for the user's community.
- Keep product decisions, architecture, and operational knowledge in `docs/`.
- Update `docs/PROJECT_CONTEXT.md` when a durable requirement or constraint is established.
- Record meaningful architectural choices in `docs/DECISIONS.md`.

## Language

- Write user-facing reports and project documentation in Russian unless the user asks otherwise.
- Code identifiers, configuration keys, logs, and runtime error messages must be in English.

## Telegram

- Reuse the canonical Telegram tooling from `C:\Users\User\jarvis`; do not create another user-session store.
- Use `C:\Users\User\.codex\tools\telegram.ps1` for Telegram operations.
- The canonical connector is `C:\Users\User\jarvis\integrations\telegram`.
- The canonical shared GramJS session is managed outside this repository.
- Never copy Telegram credentials, session contents, phone numbers, or pending authentication data into this workspace.
- Do not read chats, download media, or send messages unless the user explicitly requests that specific action.
- Before retrying a possibly completed send, check recent messages and avoid duplicates.
- Bot API credentials, once introduced, must be supplied through local environment variables or a secrets manager and never committed.

## Memory

- This project has a dedicated MemPalace at `C:\Users\User\.mempalace\palaces\community_bot`.
- Use the `community_bot` wing for project knowledge.
- Do not mix this project's memory with the existing `flatscanner` palace.
- Mine durable project files only. Never mine `.env`, credentials, Telegram sessions, raw private chats, build output, or temporary files.
- Treat repository documentation as the source of truth; MemPalace is a retrieval index, not the canonical store.

## Development

- Do not select a framework, database, hosting platform, or bot library until requirements justify the choice.
- Prefer a small modular monolith for the first production version.
- Separate Telegram transport, application use cases, domain rules, and infrastructure integrations.
- Add automated tests for business rules and update documentation with every material behavior change.
- Preserve unrelated user changes and never commit secrets.
