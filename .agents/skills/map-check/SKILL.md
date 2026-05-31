---
name: map-check
description: "Quality gates and verification for MAP workflow"
---

# $map-check — Quality Gates & Verification

Run quality gates on the current MAP workflow state.

## Usage

```
$map-check [subtask-id]
```

## Workflow

1. Load state: `shell_command` to read .map/<branch>/step_state.json
2. Run tests: `shell_command` for project test suite
3. Run linter: `shell_command` for project linter
4. Report: Output verification results
