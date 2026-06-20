# Plans

Persistent implementation plans that outlive a single conversation. Read by humans and AI agents alike.

## When to write one

A change that touches 3+ files, introduces a new abstraction, or spans multiple sessions deserves a plan file. One-shot edits, single-file fixes, and throwaway prototypes don't — the chat history is the plan in those cases.

## Filename

`YYYY-MM-DD-<kebab-slug>.md` — date is when the plan was *written* (not when work completes), slug is 2–6 lowercase hyphen-separated words.

Examples:
- `2026-04-29-cross-repo-search.md`
- `2026-05-04-make-to-task-migration.md`

No `-plan` / `-design` suffix — the folder name already says "plan".

## Required field

Every plan starts with a `Status:` line:

- `not started`
- `in progress`
- `done`
- `abandoned`

Closing a plan as `abandoned` with one line on *why* is more useful than letting it rot.

## Skeleton

See [`_template.md`](_template.md) — copy it, rename to today's date + slug, fill in.

## Before starting non-trivial work

`ls plans/` first. A prior plan may already cover what you're about to redo.
