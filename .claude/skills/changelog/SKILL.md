---
name: changelog
description: Generate a CHANGELOG entry in Keep-a-Changelog format. Use when the
  user asks for a changelog, release notes, or a summary of recent changes.
license: MIT
metadata:
  author: you
  version: "1.0"
---

# Changelog entry

1. Run `git log --oneline <from>..<to>` to list commits in the range.
2. Group by type: Added, Changed, Deprecated, Removed, Fixed, Security.
3. Write each entry as "- <imperative summary> ([#PR](url))".
4. Output the block under the version heading: `## [Unreleased] - YYYY-MM-DD`.
