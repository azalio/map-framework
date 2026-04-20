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

## Workflow

1. Research: `shell_command` to explore relevant files
2. Implement: `apply_patch` or `shell_command` to make changes
3. Verify: `shell_command` to run tests/build

No decomposition, no state tracking, no artifacts.
