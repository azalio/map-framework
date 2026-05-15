---
paths:
  - "**/test_*"
  - "**/tests/**"
  - "**/*_test.*"
  - "**/*.test.*"
---

# Testing Strategies (Learned)

<!-- IMPROVEMENT-PLAN-LOOP: promoted from loop learnings. Edit freely and commit with the project. -->

- **Lint skill metadata, not just sync** (2026-04-13): When testing shipped skill frontmatter, always cover description length, unresolved `map-*` references, and manual-skill argument hints because template sync alone does not catch slash-menu UX regressions. [workflow: improvement-plan-loop]
- **Validate skill catalog wiring, not just skill files** (2026-05-15): When changing shipped skills, test `skill-rules.json` against `SKILL.md` frontmatter so manual slash skills have argument hints, direct invocation trigger keywords/patterns, selected negative-trigger fixtures, synced supporting files, resolved Markdown links, and valid `CLAUDE_PLUGIN_ROOT` hook script paths. [workflow: improvement-plan-loop]
- **Test skill runtime class boundaries** (2026-05-15): When adding or reclassifying shipped skills, require `skillClass` in `skill-rules.json`, enforce task/manual consistency, reject reference skills with hidden manual invocation or hooks, and require hybrid skills to list `runtimeEffects`. [workflow: improvement-plan-loop]
- **Reject stale prompt phase wording, not just old schema fields** (2026-05-15): When moving a MAP workflow from proposal JSON to direct Edit/Write behavior, tests must reject old output fields like `code_changes` and leftover prose such as `Apply fix` or `ACCEPT and apply changes`; otherwise the workflow can still imply a second apply phase after Actor already wrote files. [workflow: improvement-plan-loop]
