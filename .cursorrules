# Workspace Workflow Guidance

_Generic development practices for any repo. Same content drops as `CLAUDE.md` (Claude Code), `AGENTS.md` (Codex / generic), and `.cursorrules` (Cursor)._

## Development practices

### Test-driven development (TDD)

When adding any new code (a new function, class, module, skill runner, detector, parser, etc.), follow the TDD loop:

1. **Write a failing test first** under the appropriate `tests/` tree that exercises the smallest meaningful slice of the new behavior. Run it and confirm it fails for the *right* reason (assertion, not import error).
2. **Write the minimum code** to make that test pass. Don't add scope beyond what the test demands.
3. **Refactor** with the test as a safety net — names, dedup, extraction. Re-run the test after every change.
4. **Repeat** for the next slice until the feature is complete.

Applies to: new features, runners, detectors, modules, shared utilities. Does **not** apply to: pure prose changes (docs, comments, config descriptions), template-only edits, one-off scripts the user explicitly marks as throwaway.

When TDD genuinely doesn't fit (e.g., exploring an unfamiliar API, prototyping a UI layout, hand-debugging a flaky integration), say so explicitly in the conversation before writing code — don't silently skip the test. Backfill the test once the shape is known.

### Plan-first for non-trivial work

For any change that touches 3+ files, introduces a new abstraction, or makes an architectural decision: state the plan in conversation first — *what* changes, *where*, in what order, and what gets tested. One paragraph is enough; this isn't a design doc. In auto mode, state the plan and proceed; outside auto mode, wait for the user to confirm.

If the plan goes sideways mid-implementation (the abstraction doesn't fit, a test reveals a wrong mental model, a file you didn't expect to touch needs surgery): **stop and re-plan**. Don't push through with a worse version of the original plan — that's how scope creep and half-finished refactors land in commits.

### Persist plans that outlive the conversation

When a plan needs to survive past the current chat — multi-session work, large feature scaffolding, design decisions worth referencing later — write it to `plans/<YYYY-MM-DD>-<slug>.md` at the workspace root.

- **Filename:** `YYYY-MM-DD-<kebab-slug>.md`. Date = when the plan was written (not when work completes). Slug = 2-6 words, lowercase, hyphen-separated. Example: `2026-04-29-workspace-claude-md.md`. Don't add suffixes like `-plan` or `-design`.
- **Contents:** the same plan you'd state in chat — goal, file-by-file change table, ordering, tests. Add a `Status:` field at the top: `not started | in progress | done | abandoned`. Update it as you go; closing a plan as `abandoned` with one line on *why* is more useful than letting it rot.
- **When NOT to write a file:** one-shot conversational work, single-file edits, throwaway prototypes. The chat history is the plan in those cases.
- **Before starting non-trivial work in a workspace:** `ls plans/` first. A prior plan may already cover what you're about to redo.

### Verify before declaring done

Never report a task complete on intent alone. Prove it:

- New code path → run the test that exercises it.
- CLI change → run the CLI and read the output.
- Service / handler change → run the service against a real fixture or staging input and check the response.
- Schema / template change → render it and check the artifact.

"It should work" is not verification — "I ran X and got Y" is. If verification surfaces a failure that's non-obvious to fix, surface it explicitly to the user with the failing output, not a hopeful "should be done now."

### Pursue elegance, but balanced

For non-trivial changes, pause once before declaring done and ask: *knowing what I know now, is there a more elegant approach?* If the working code feels hacky — duplicated branches, special cases bolted on, names that don't match what the function does — rewrite it before presenting.

Skip this gate for one-line fixes, mechanical renames, and obvious tweaks; over-engineering simple work is its own anti-pattern. The bar is "would a staff engineer be comfortable owning this?" — not "is this the most beautiful code possible?"

### Root cause over patch

When a bug, test failure, or unexpected behavior appears: **find why before fixing**. A patch that only suppresses the symptom (catching-and-ignoring, hard-coding around a flaky boundary, marking a test `skip`, adding a `try/except` that swallows the exception) is a debt note, not a fix.

If root-causing genuinely costs more than the user wants to spend right now, surface that tradeoff explicitly and let them choose. Don't ship a silent papering-over.

### Capture lessons from corrections

When the user course-corrects ("no, do X instead", "stop doing Y", "yes, that bundled approach was right"), save a `feedback` memory in the agent's project memory folder (Claude Code: `~/.claude/projects/<project-key>/memory/`; other agents: their per-project memory equivalent). Record the rule, the *why*, and how to apply it — corrections **and** validated judgment calls. The next session reads project memory automatically; the lesson sticks. This is the project's self-improvement loop.
