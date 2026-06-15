# Step State Schema Reference

## Overview

The `step_state.json` file tracks **the next required workflow action** for MAP state-machine workflows (primarily `/map-efficient`). It is optimized for fast reads by hooks.

It enables:
- **Sequencing:** `.map/scripts/map_orchestrator.py` decides the next step deterministically
- **Reminders:** `workflow-context-injector.py` injects a short reminder before significant tool calls
- **User checkpoints:** explicit plan approval + execution mode selection

`step_state.json` is the single source of truth for workflow state, used by both the orchestrator and enforcement hooks.

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

Current step set (linear order; some phases use conditional subagents):

1. `1.0` DECOMPOSE
2. `1.5` INIT_PLAN
3. `1.55` REVIEW_PLAN
4. `1.56` CHOOSE_MODE
5. `1.6` INIT_STATE
7. `2.2` RESEARCH (artifact required; research-agent conditional)
9. `2.3` ACTOR
10. `2.4` MONITOR
