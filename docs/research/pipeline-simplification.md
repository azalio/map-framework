# Pipeline Simplification Design Doc

**Date:** 2026-03-22
**Branch:** autoresearch
**Status:** Approved direction, pending execution plan

---

## Problem

Current map-efficient pipeline has 11 phases per subtask. In practice ~6-7 are no-op for typical tasks. Feedback from real workflow run (7 subtasks, greenfield):

- ~70 validate_step calls, mostly rubber-stamp
- 21 evidence files nobody reads
- XML_PACKET reformats data Actor already has in prompt
- VERIFY_ADHERENCE self-audit never actually executed
- Hooks print noise on every tool call
- Dual state files (workflow_state.json + step_state.json) cause confusion

~80% of value came from /map-plan. The rest was ceremony.

## New Pipeline

### Per subtask (2-3 phases):

```
[RESEARCH] → ACTOR → MONITOR
   ^only if: 3+ existing files OR risk=high
```

### Per wave (after all subtasks in wave pass Monitor):

```
TESTS + LINTER (one run)
```

### After all waves:

```
[FINAL-VERIFIER] → done
   ^optional: skip if all subtasks low-risk AND < 5 subtasks
```

### Retry loop

ACTOR → MONITOR, max 5 retries per subtask. Stuck recovery at retry 3 (research-agent → predictor).

### Per-wave guard failure isolation (P1 resolution)

When per-wave TESTS/LINTER gate fails after a parallel wave, the orchestrator cannot know which subtask caused the regression. Isolation strategy:

1. **Isolate:** Use `subtask_files_changed` from step_state.json to identify which files belong to which subtask. Run the failing test/linter against each subtask's file set individually to narrow the culprit.
2. **Identify:** The subtask(s) whose files trigger the failure are the culprits.
3. **Interaction fallback:** If no single subtask's files reproduce the failure (interaction bug between subtasks), rerun the wave sequentially — Actor+Monitor each subtask one at a time with full test suite after each. The subtask whose addition causes the gate to fail is the culprit (or both are, if failure requires their combination — in that case reopen both).
4. **Retry:** Send identified culprit subtask(s) back to Actor with guard failure context (test/lint output + which other subtask(s) interact). Max 2 rework attempts per identified subtask.
5. **Re-gate:** After rework, re-run the full wave gate (all subtasks together).
6. **Escalate:** If 2 rework attempts fail, escalate to user: "Guard failure in wave N after 2 rework attempts. Subtask(s): ST-XXX. Skip/Abort?"

For sequential waves (single subtask), the culprit is trivially the only subtask — no isolation needed.

### State lifecycle (P1 resolution)

State does NOT auto-advance on Monitor pass. Instead:

```
Per-subtask states:
  ACTOR_PENDING → ACTOR_DONE → MONITOR_PASSED | MONITOR_FAILED

Per-wave states:
  WAVE_MONITORS_DONE → WAVE_GATES_PENDING → WAVE_GATES_PASSED | WAVE_GATES_FAILED
  (WAVE_GATES_FAILED → isolation → rework → re-gate)

Post-all-waves:
  FINAL_VERIFY_PENDING → COMPLETE | FAILED
```

State advances:
- After Monitor pass → subtask marked MONITOR_PASSED (not "done")
- After ALL subtasks in wave reach MONITOR_PASSED → wave state becomes WAVE_GATES_PENDING
- After TESTS+LINTER pass → WAVE_GATES_PASSED, wave advances
- After FINAL-VERIFIER (if required) → COMPLETE

This ensures resume always lands at the correct execution point. The single `step_state.json` file tracks both per-subtask and per-wave states.

### Predictor: single authoritative rule (P2 resolution)

Predictor runs in exactly ONE context: **stuck recovery at retry 3**.

It is NOT a regular phase in the pipeline. The per-subtask pipeline is always:
```
[RESEARCH] → ACTOR → MONITOR
```

Predictor is invoked only when:
1. Actor → Monitor retry count reaches 3
2. Research-agent is called first for alternative approaches
3. Predictor analyzes why current approach fails (skip for risk_level=low)
4. Recovery context passed to Actor for retries 4-5

The phase-count table reflects this: "high-risk, security" row is 3 phases (RESEARCH → ACTOR → MONITOR), same as medium-risk with 3+ files. Predictor does not add a phase — it's an inline recovery step within the retry loop.

## What's Removed

| Removed | Reason |
|---------|--------|
| XML_PACKET (2.0) | Actor gets same info in prompt via AAG contract |
| CONTEXT_SEARCH (2.1) | Never used; /map-plan discovery sufficient |
| Evidence files (actor/monitor/predictor JSON) | Write-only, nobody reads; validate_step existence check removed |
| Evidence directory | Consequence of above |
| VERIFY_ADHERENCE (2.10) | Self-audit checklist never actually executed |
| APPROVAL (2.11) | Already auto-skipped in batch mode |
| UPDATE_STATE (2.7) | Replaced by state lifecycle (per-subtask + per-wave states) |
| workflow_state.json | Merged into step_state.json (single source of truth) |
| session-log.md | Boilerplate, not read |
| devlog-XXX.md | Boilerplate, not read |
| Per-subtask TESTS/LINTER gates | Moved to per-wave (one run after all Monitor passes in wave) |
| PREDICTOR as regular phase | Moved to stuck recovery only (retry 3) |

## What's Kept

| Kept | Why |
|------|-----|
| /map-plan (decomposition + DA) | ~80% of value |
| Wave computation + parallel execution | Real time savings |
| AAG contracts | Clear spec for Actor |
| RESEARCH (conditional) | Useful for complex existing-code tasks |
| ACTOR agent | Core implementation |
| MONITOR agent | Catches real bugs (1/7 in test run) |
| Predictor (stuck recovery only) | Intermediate recovery at retry 3 |
| Guard pattern (per-wave) | Regression prevention with isolation strategy |
| Stuck recovery (retry 3) | research-agent → predictor → retry 4-5 |
| FINAL-VERIFIER (conditional) | Full goal verification, useful for complex tasks |
| code-review-XXX.md | Monitor results, readable history |
| step_state.json | Single canonical state file |

## What's Changed

### RESEARCH gating

**Was:** Call if refactoring OR touching 3+ files
**Now:** Call only if 3+ existing files OR risk=high. Medium-risk with 1-2 existing files → Actor handles it, Monitor catches if not.

### Per-wave GATES

- Tests + linter run once after ALL Monitor passes in wave
- NOT between Actor→Monitor retry iterations
- Guard failure → isolation (identify culprit subtask) → rework (max 2) → re-gate → escalate

### FINAL-VERIFIER

- Optional: skip if all subtasks low-risk AND < 5 subtasks total
- Always run for: high-risk subtasks, security_critical, 5+ subtasks

### Hooks

- **workflow-context-injector.py**: print only on phase/subtask change, not every tool call. Track last-printed state; skip if unchanged.
- **workflow-gate.py**: reads step_state.json only (already done). Constraints field moves from workflow_state.json to step_state.json.

### State management

- Single file: step_state.json
- workflow_state.json: removed entirely
- Per-subtask state: ACTOR_PENDING → ACTOR_DONE → MONITOR_PASSED
- Per-wave state: WAVE_GATES_PENDING → WAVE_GATES_PASSED
- Constraints: moved to step_state.json

## Phase Count Comparison

| Scenario | Old (11 phases) | New (2-3 phases) | Reduction |
|----------|-----------------|-------------------|-----------|
| Low-risk, new files | 11 (6-7 no-op) | 2 (ACTOR → MONITOR) | 82% |
| Medium-risk, 1-2 files | 11 (4-5 no-op) | 2 (ACTOR → MONITOR) | 82% |
| Medium-risk, 3+ files | 11 (3-4 no-op) | 3 (RESEARCH → ACTOR → MONITOR) | 73% |
| High-risk, security | 11 (1-2 no-op) | 3 (RESEARCH → ACTOR → MONITOR) | 73% |

Per-wave GATES and optional FINAL-VERIFIER add 1-2 phases total (not per subtask).
Predictor is inline within stuck recovery, not a separate phase.

## step_state.json Schema (new)

```json
{
  "workflow": "map-efficient",
  "started_at": "ISO-8601",
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"],
  "aag_contracts": {"ST-001": "...", "ST-002": "..."},

  "execution_waves": [["ST-001", "ST-002"], ["ST-003"]],
  "current_wave_index": 0,

  "current_step_phase": "ACTOR",
  "current_subtask_id": "ST-002",

  "subtask_phases": {"ST-001": "COMPLETE", "ST-002": "2.3"},
  "subtask_retry_counts": {"ST-001": 0, "ST-002": 1},
  "guard_rework_counts": {},

  "subtask_files_changed": {
    "ST-001": ["src/models/user.py", "src/models/__init__.py"],
    "ST-002": ["src/services/auth.py"]
  },

  "constraints": {
    "scope_glob": null,
  },

  "workflow_status": "IN_PROGRESS",

  "tdd_mode": false,
  "plan_approved": true
}
```

### Field contracts for hooks

| Field | Written by | Read by | Purpose |
|-------|-----------|---------|---------|
| `current_step_phase` | Orchestrator (before each agent call) | workflow-gate.py, workflow-context-injector.py | Gating: Edit allowed only during ACTOR, APPLY, TEST_WRITER. Reminder: show current phase. |
| `current_subtask_id` | Orchestrator | workflow-context-injector.py | Reminder: show which subtask is active |
| `subtask_files_changed` | Orchestrator (after Actor returns) | Guard isolation strategy | Map subtask → files for per-subtask revert during wave gate failure |
| `workflow_status` | Orchestrator (at lifecycle boundaries) | Resume, /map-check, CI/CD | Overall workflow outcome |

Valid `current_step_phase` values: phase names from STEP_PHASES (`DECOMPOSE`, `INIT_PLAN`, `REVIEW_PLAN`, `CHOOSE_MODE`, `INIT_STATE`, `RESEARCH`, `TEST_WRITER`, `TEST_FAIL_GATE`, `ACTOR`, `MONITOR`, `COMPLETE`)
Valid `workflow_status` values: `INITIALIZED`, `IN_PROGRESS`, `FINAL_VERIFY_PENDING`, `COMPLETE`, `FAILED`, `ABORTED`

### Hook contract mapping (old → new)

| Hook | Old field | New field | Notes |
|------|-----------|-----------|-------|
| workflow-gate.py | `current_step_phase` in EDITING_PHASES | `current_step_phase` in {ACTOR, APPLY, TEST_WRITER} | Same logic, same field |
| workflow-gate.py | `subtask_phases` dict (parallel) | `subtask_phases` dict + `current_step_phase` fallback | During parallel wave, any subtask in EDITING_PHASES allows edits |
| workflow-gate.py | constraints from workflow_state.json | `constraints` in step_state.json | Same structure, moved |
| context-injector | `current_step_phase` + `current_subtask_id` | `current_step_phase` + `current_subtask_id` | Same contract, same fields |

## Full Migration Surface (P2 resolution)

All files referencing workflow_state.json, evidence/, session-log, devlog, or removed phases.

### Commands (must update):
| File | References | Action |
|------|-----------|--------|
| `.claude/commands/map-efficient.md` | workflow_state.json, evidence, all 11 phases, session-log, devlog | **Rewrite** |
| `.claude/commands/map-plan.md` | workflow_state.json (init) | Update to write step_state.json |
| `.claude/commands/map-tdd.md` | evidence (test_writer), XML_PACKET | Remove evidence, remove XML_PACKET |
| `.claude/commands/map-task.md` | workflow_state.json | Update to step_state.json |
| `.claude/commands/map-resume.md` | workflow_state.json, evidence | Update to step_state.json |
| `.claude/commands/map-check.md` | workflow_state.json | Update to step_state.json |
| `.claude/commands/map-debate.md` | evidence | Remove evidence refs |

### Hooks (must update):
| File | References | Action |
|------|-----------|--------|
| `.claude/hooks/workflow-gate.py` | step_state.json (already migrated) | Remove workflow_state.json fallback if any |
| `.claude/hooks/workflow-context-injector.py` | step_state.json, phase names | Update phase names, add dedup |
| `.claude/hooks/ralph-context-pruner.py` | evidence/ | Remove evidence refs |
| `.claude/hooks/post-compact-context.py` | workflow_state.json | Update to step_state.json |

### Agents (must update):
| File | References | Action |
|------|-----------|--------|
| `.claude/agents/actor.md` | evidence file writing | Remove evidence instructions |
| `.claude/agents/monitor.md` | evidence file writing | Remove evidence instructions |
| `.claude/agents/predictor.md` | evidence file writing | Remove evidence instructions |

### Python scripts (must update):
| File | References | Action |
|------|-----------|--------|
| `src/mapify_cli/templates/map/scripts/map_orchestrator.py` | STEP_PHASES, evidence checks, all phase constants | **Major rewrite** |
| `src/mapify_cli/templates/map/scripts/map_step_runner.py` | workflow_state.json, session-log, devlog | Remove/update |
| `src/mapify_cli/__init__.py` | session-log, devlog in artifact list | Remove |

### References/schemas (must update):
| File | References | Action |
|------|-----------|--------|
| `.claude/references/workflow-state-schema.md` | workflow_state.json schema | Remove or redirect to step_state.json |
| `.claude/references/step-state-schema.md` | step_state.json schema | Update with new schema |

### Documentation (must update):
| File | References | Action |
|------|-----------|--------|
| `docs/ARCHITECTURE.md` | workflow_state.json, evidence, phase descriptions | Update |
| `docs/WORKFLOW_FLOW.md` | Phase flow diagrams | Update |

### Skills (must update):
| File | References | Action |
|------|-----------|--------|
| `.claude/skills/map-planning/SKILL.md` | workflow_state.json | Update to step_state.json |

### Tests (must update):
| File | References | Action |
|------|-----------|--------|
| `tests/test_map_orchestrator.py` | STEP_PHASES, evidence, phase constants | **Major rewrite** |
| `tests/test_map_step_runner.py` | workflow_state.json, session-log, devlog | Update |
| `tests/test_workflow_gate.py` | Already uses step_state.json | May need wave_states tests |
| `tests/test_command_templates.py` | session-log, devlog assertions | Remove assertions |

### Template sync:
All `.claude/` changes → `src/mapify_cli/templates/` (doubles the file count above).

**Total: ~25 unique files + ~25 template mirrors = ~50 files to touch.**

## Risk

- map-efficient.md is ~900 lines — major rewrite
- map_orchestrator.py is ~1700 lines — significant changes to step sequencing
- Backward compat: old step_state.json files will not work with new pipeline (need migration or clean break)
- ~50 files to touch across the repo
- Tests: test_map_orchestrator.py, test_map_step_runner.py, test_command_templates.py need updating
- Parallel wave guard isolation adds complexity not present in current sequential model
