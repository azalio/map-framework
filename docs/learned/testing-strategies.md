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

