---
paths:
  - "**/test_*"
  - "**/tests/**"
  - "**/*_test.*"
  - "**/*.test.*"
---

# Testing Strategies (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Monitor Bugs Must Generate Regression Tests** (2026-03-26): When Monitor (or any review tool) finds a bug, always write a failing test that reproduces the bug BEFORE fixing it, because without a regression test the same bug silently reappears during future refactors. Name tests `test_<function>_<what_was_found>` to serve as living documentation. [workflow: map-learn-improvement]
