# Step State Schema Reference

## Overview

The `step_state.json` file tracks **the next required workflow action** for MAP state-machine workflows (primarily `/map-efficient`). It is optimized for fast reads by hooks.

It enables:
- **Sequencing:** `.map/scripts/map_orchestrator.py` decides the next step deterministically
- **Reminders:** `workflow-context-injector.py` injects a short reminder before significant tool calls
- **User checkpoints:** explicit plan approval + execution mode selection

This is separate from `workflow_state.json`, which tracks subtask execution steps for enforcement (see `workflow-state-schema.md`).

## Location

```
.map/<branch>/step_state.json
```

Branch name is sanitized (e.g., `feature/foo` → `feature-foo`).

## Schema (current)

```json
{
  "workflow": "map-efficient",
  "started_at": "ISO8601",

  "current_subtask_id": "ST-001|null",
  "subtask_index": 0,
  "subtask_sequence": ["ST-001", "ST-002"],

  "current_step_id": "1.0",
  "current_step_phase": "DECOMPOSE",

  "completed_steps": ["1.0", "1.5"],
  "pending_steps": ["1.55", "1.56", "1.6"],

  "retry_count": 0,
  "max_retries": 5,

  "plan_approved": false,
  "execution_mode": "batch"
}
```

## Key Fields

- `current_step_id` / `current_step_phase`: the single step the orchestrator expects next
- `current_subtask_id`: current subtask (e.g. `ST-003`) or null while planning
- `plan_approved`: explicit human approval gate before initializing execution state
- `execution_mode`: `batch` or `step_by_step` (pauses between subtasks)

## Step IDs (map-efficient)

Current step set (linear order; some are conditional):

1. `1.0` DECOMPOSE
2. `1.5` INIT_PLAN
3. `1.55` REVIEW_PLAN
4. `1.56` CHOOSE_MODE
5. `1.6` INIT_STATE
6. `2.0` XML_PACKET
7. `2.1` MEM0_SEARCH
8. `2.2` RESEARCH (conditional)
9. `2.3` ACTOR
10. `2.4` MONITOR
11. `2.6` PREDICTOR (conditional)
12. `2.7` UPDATE_STATE
13. `2.8` TESTS_GATE (conditional)
14. `2.9` LINTER_GATE (conditional)
15. `2.10` VERIFY_ADHERENCE
16. `2.11` SUBTASK_APPROVAL (conditional; step_by_step only)

## Relationship to workflow_state.json

- `step_state.json`: sequencing + reminders (cheap to read, small)
- `workflow_state.json`: enforcement gate for Edit/Write (actor+monitor must be completed)
