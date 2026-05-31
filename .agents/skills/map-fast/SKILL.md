---
name: map-fast
description: "Minimal workflow for small, low-risk changes — no planning, no learning"
---

# $map-fast — Quick Implementation

Minimal MAP workflow for small changes. Skips planning and learning phases.

## Usage

```
$map-fast <task description>
```

## Mutation Boundary Constraints

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the task explicitly names that dependency change.
- Do not refactor neighboring code unless the acceptance criteria cannot pass without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff instead of doing it silently.

## Workflow

1. Research: `shell_command` to explore relevant files
2. Implement: `apply_patch` or `shell_command` to make changes
3. Verify: `shell_command` to run tests/build

No decomposition, no state tracking, no artifacts.
