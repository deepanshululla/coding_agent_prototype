# Project Learnings

> Project-wide, committed log of non-obvious technical discoveries about *this codebase*. Distinct from per-user agent memory (preferences) and `plans/` (forward-looking work in progress).

## Purpose

Capture surprising behaviors, debugging gotchas, and "we tried X and Y broke" stories that:

- Span sessions and contributors (not just one user's preferences).
- Future agents and humans would benefit from *before* they re-discover the same thing.
- Aren't already documented in the code or in `CLAUDE.md`.

If the same lesson keeps showing up across PRs and onboarding, it has graduated from a learning into a convention — promote it to `CLAUDE.md` and remove or shorten the entry here.

## When to log here vs. elsewhere

| Surface | Scope | Visibility | Use for |
|---------|-------|------------|---------|
| `learnings.md` (this file) | Project-wide | Committed, every contributor + agent reads it | Non-obvious technical facts about this codebase |
| Agent auto-memory (per-user) | Per-user | Private, persists across the user's conversations | Preferences, communication style, validated judgment calls |
| `plans/<YYYY-MM-DD>-<slug>.md` | Per-task | Committed, ephemeral | Multi-session implementation plans |
| `CLAUDE.md` / `AGENTS.md` | Project-wide | Committed, loaded on every session | Stable conventions and guidance |

Tiebreaker: a fact that would help a brand-new engineer onboarding to this repo → `learnings.md`. A fact about how *this user* likes to work → auto-memory.

## Entry format

Append new entries **at the top** (newest first). Keep each entry to ~150 words.

```markdown
## YYYY-MM-DD — Short title

**Context:** What you were trying to do.
**What happened:** The surprising behavior or failure.
**Root cause:** Why it happened (link to code, commit SHA, or PR if useful).
**Lesson:** One-sentence takeaway — what to do (or avoid) next time.
**Tags:** comma, separated, tags
```

Anything that touches secrets, internal credentials, or private user data does **not** belong here — it's a committed file. Use auto-memory or local notes instead.

---

## Entries

<!-- Add new entries below, newest first. -->
