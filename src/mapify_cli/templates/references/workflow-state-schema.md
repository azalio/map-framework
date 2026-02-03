# Workflow State Schema Reference

## Overview

The `workflow_state.json` file tracks execution state for MAP Framework workflows. It enables:
- **Enforcement:** workflow-gate.py hook blocks Edit/Write without required steps
- **Resumption:** Continue workflows after context resets
- **Visibility:** Explicit tracking of what steps were completed
- **Audit:** Verify workflow adherence

## Location

```
.map/<branch>/workflow_state.json
```

Branch name is sanitized (e.g., `feature/foo` → `feature-foo`).

## Schema

```json
{
  "workflow": "string",              // Workflow name (e.g., "map-efficient")
  "started_at": "ISO8601",           // Workflow start timestamp
  "current_subtask": "string|null",  // Current subtask ID (e.g., "ST-001")
  "current_state": "string",         // Current workflow state (see Valid States)
  "completed_steps": {               // Steps completed per subtask
    "ST-001": ["step1", "step2"],    // Array of completed step names
    "ST-002": ["step1"]
  },
  "pending_steps": {                 // Steps pending per subtask
    "ST-001": ["step3", "step4"],
    "ST-002": ["step2", "step3"]
  },
  "subtask_sequence": ["string"]     // Ordered list of all subtask IDs
}
```

## Valid States

State transitions follow this progression:

```
INITIALIZED                 → Workflow started, no subtask active
  ↓
XML_PACKET_CREATED         → AI packet created for current subtask
  ↓
CONTEXT_LOADED             → mem0 tiered search completed
  ↓
RESEARCH_DONE              → Research agent completed (if 3+ files)
  ↓
ACTOR_CALLED               → Actor agent generated implementation
  ↓
MONITOR_PASSED             → Monitor agent validated changes
  ↓
PREDICTOR_ANALYZED         → Predictor assessed impact (if medium/high risk)
  ↓
TESTS_PASSED               → Test gate passed
  ↓
LINTER_PASSED              → Linter gate passed
  ↓
SUBTASK_COMPLETE           → Subtask fully done, ready for next
  ↓
(repeat for each subtask)
  ↓
WORKFLOW_COMPLETE          → All subtasks done, final verification pending
```

## Step Names

Standard step names used in `completed_steps` arrays:

- `"xml_packet"` - AI-friendly subtask packet created
- `"mem0_search"` - Context patterns retrieved from mem0
- `"research"` - Research agent analyzed codebase (optional, for 3+ files)
- `"actor"` - Actor agent generated implementation
- `"monitor"` - Monitor agent validated implementation
- `"predictor"` - Predictor agent analyzed impact (optional, for medium/high risk)
- `"tests"` - Test gate passed
- `"linter"` - Linter gate passed

## Example Workflow Progression

### Initial State (after Step 1.6)

```json
{
  "workflow": "map-efficient",
  "started_at": "2026-01-27T10:30:00Z",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": []
}
```

### After Decomposition

```json
{
  "workflow": "map-efficient",
  "started_at": "2026-01-27T10:30:00Z",
  "current_subtask": "ST-001",
  "current_state": "XML_PACKET_CREATED",
  "completed_steps": {
    "ST-001": ["xml_packet"]
  },
  "pending_steps": {
    "ST-001": ["mem0_search", "actor", "monitor", "tests", "linter"],
    "ST-002": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"],
    "ST-003": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"]
  },
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"]
}
```

### After Actor + Monitor

```json
{
  "workflow": "map-efficient",
  "started_at": "2026-01-27T10:30:00Z",
  "current_subtask": "ST-001",
  "current_state": "MONITOR_PASSED",
  "completed_steps": {
    "ST-001": ["xml_packet", "mem0_search", "actor", "monitor"]
  },
  "pending_steps": {
    "ST-001": ["tests", "linter"],
    "ST-002": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"],
    "ST-003": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"]
  },
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"]
}
```

At this point, workflow-gate.py will **ALLOW** Edit/Write because both "actor" and "monitor" are in `completed_steps["ST-001"]`.

### Subtask Complete

```json
{
  "workflow": "map-efficient",
  "started_at": "2026-01-27T10:30:00Z",
  "current_subtask": "ST-001",
  "current_state": "SUBTASK_COMPLETE",
  "completed_steps": {
    "ST-001": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"]
  },
  "pending_steps": {
    "ST-001": [],
    "ST-002": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"],
    "ST-003": ["xml_packet", "mem0_search", "actor", "monitor", "tests", "linter"]
  },
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"]
}
```

## Enforcement Logic (workflow-gate.py)

The workflow-gate.py hook enforces this rule:

```python
# BLOCKS Edit/Write/MultiEdit if:
if "actor" not in completed_steps[current_subtask]:
    BLOCK("Must call Actor first")

if "monitor" not in completed_steps[current_subtask]:
    BLOCK("Must call Monitor after Actor")

# ALLOWS Edit/Write/MultiEdit if:
if "actor" in completed_steps[current_subtask] and "monitor" in completed_steps[current_subtask]:
    ALLOW("Required workflow steps completed")
```

## State Update Pattern

After each workflow step, update state using this pattern:

```python
import json
from pathlib import Path
import subprocess

# Load state
branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                       capture_output=True, text=True).stdout.strip().replace('/', '-')
state_file = Path(f".map/{branch}/workflow_state.json")
state = json.loads(state_file.read_text())

# Update
subtask_id = state["current_subtask"]
state["completed_steps"][subtask_id].append("step_name")  # e.g., "actor"
state["current_state"] = "NEW_STATE"  # e.g., "ACTOR_CALLED"

# Write back
state_file.write_text(json.dumps(state, indent=2))
```

## Recovery from Skipped Steps

If workflow_state.json shows steps were skipped but hook blocks:

1. **Option A:** Complete missing steps
   ```python
   # Go back and actually call the agents
   Task(subagent_type="actor", ...)
   Task(subagent_type="monitor", ...)
   # Update state after each
   ```

2. **Option B:** Manual state update (if steps were actually done)
   ```python
   # Load state
   state = json.loads(Path(f".map/{branch}/workflow_state.json").read_text())

   # Add missing steps
   state["completed_steps"]["ST-001"].extend(["actor", "monitor"])
   state["current_state"] = "MONITOR_PASSED"

   # Write back
   Path(f".map/{branch}/workflow_state.json").write_text(json.dumps(state, indent=2))
   ```

## Debugging

Check current state:

```bash
# Show current state
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
cat .map/${BRANCH}/workflow_state.json | jq '.'

# Check what steps are completed for current subtask
cat .map/${BRANCH}/workflow_state.json | jq '.completed_steps[.current_subtask]'

# Check what's pending
cat .map/${BRANCH}/workflow_state.json | jq '.pending_steps[.current_subtask]'
```

Enable debug mode for workflow-gate.py:

```bash
export DEBUG_WORKFLOW_GATE=1
# Now run Claude Code commands - hook will print debug info to stderr
```

## Design Rationale

Based on LLM Council recommendation:

> "Reify State - Don't tell the model 'remember to call Monitor.'
> Make the environment hostile to action until the Monitor is called."

This external state file combined with hook enforcement implements that principle:
- **Visible State:** State is in filesystem, not just in prompt
- **Enforced Rules:** Hook physically blocks non-compliant actions
- **Explicit Tracking:** No relying on LLM memory
- **Resumable:** State persists across context resets

## Related Files

- `.claude/hooks/workflow-gate.py` - Enforcement hook
- `.claude/commands/map-efficient.md` - Workflow definition
- `.map/<branch>/task_plan_<branch>.md` - Human-readable plan
- `.claude/settings.hooks.json` - Hook registration
