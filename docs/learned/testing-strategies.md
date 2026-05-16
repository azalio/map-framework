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
- **Validate every new branch artifact in all ledgers** (2026-05-15): When adding a `.map/<branch>/` artifact, update the writer, `artifact_manifest.json` stages, schema tests, review/learning bundle inventories, docs, and generated `mapify init` smoke; otherwise the artifact can exist locally but disappear from resume/review handoffs. [workflow: improvement-plan-loop]
- **Make live Claude E2E prompts defeat workflow-fit off-ramps** (2026-05-16): When a slow test asserts `/map-plan` artifacts via `claude -p`, use a shared prompt that explicitly forces the `map-plan` workflow-fit outcome and includes non-trivial invariants; trivial “add function” prompts can correctly off-ramp to `direct-edit` and make the test measure routing variance instead of the artifact contract. [workflow: improvement-plan-loop]
- **Test prompt snippets for decision timing and non-happy-path status** (2026-05-16): When adding closeout commands to skill prompts, regression tests should reject both direct hard-coded happy-path arguments and variable defaults like `RUN_HEALTH_STATUS="complete"`; also assert the snippet appears after the verdict/verification section that determines the terminal status. [workflow: improvement-plan-loop]
- **Treat hook JSON fields as untrusted types** (2026-05-16): When a hook accepts JSON from Claude/tooling, test malformed JSON, wrong top-level types, wrong field types, missing state, and invalid state; the hook must keep exit 0, persist skipped reasons only when existing state is parseable, and never create or clobber state just to record diagnostics. [workflow: improvement-plan-loop]
