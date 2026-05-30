# Iteration History (Ralph Loop Black Box)

This template documents the history of Ralph Loop iterations for a workflow.
Used for context pruning and debugging long-running workflows.

---

## Iteration {{iteration_number}}

**Timestamp:** {{timestamp}}
**Phase:** {{phase}}
**Result:** {{result}}
**Confidence:** {{confidence}}

### Verification Report
- Tests run: {{tests_run}}
- Tests passed: {{tests_passed}}
- Tests failed: {{tests_failed}}
- Ground truth check: {{ground_truth_status}}
- Integration check: {{integration_status}}

### Root Cause (if failed)
- **Unmet requirements:** {{unmet_requirements}}
- **Error files:** {{error_files}}
- **Fix type:** {{fix_type}}
- **Invalidated subtasks:** {{invalidated_subtasks}}
- **Suggested action:** {{suggested_action}}

### Decision
{{decision_arrow}} {{decision_reason}}

---

## Usage Notes

This template is populated by the orchestrator (map-efficient.md) after each
Final Verification step. The data comes from:

1. `.map/<branch>/final_verification.json` - Structured verification result
2. `.map/<branch>/ralph_state.json` - Iteration counters and phase
3. Orchestrator decision logic - COMPLETE / RE_DECOMPOSE / ESCALATE

### Template Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `iteration_number` | `ralph_state.plan_iteration` | Current re-decomposition iteration |
| `timestamp` | `final_verification.timestamp` | When verification completed |
| `phase` | `ralph_state.phase` | Current Ralph Loop phase |
| `result` | `final_verification.passed` | PASSED or FAILED |
| `confidence` | `final_verification.confidence` | 0.0-1.0 confidence score |
| `tests_run` | `final_verification.evidence.tests_run` | Number of tests executed |
| `tests_passed` | `final_verification.evidence.tests_passed` | Passing test count |
| `tests_failed` | `final_verification.evidence.tests_failed` | Failing test count |
| `ground_truth_status` | `final_verification.evidence.ground_truth_check` | passed/failed/skipped |
| `integration_status` | `final_verification.evidence.integration_check` | passed/failed |
| `unmet_requirements` | `final_verification.root_cause.unmet_requirements` | List of unfulfilled requirements |
| `error_files` | `final_verification.root_cause.error_files` | Files with issues |
| `fix_type` | `final_verification.root_cause.fix_type` | code_fix/plan_change/both |
| `invalidated_subtasks` | `final_verification.root_cause.invalidated_subtasks` | Subtasks needing redo |
| `suggested_action` | `final_verification.root_cause.suggested_action` | Recommended fix |
| `decision_arrow` | Orchestrator | Arrow indicating next step (e.g., "→") |
| `decision_reason` | Orchestrator | Why this decision was made |

### Example Populated Entry

```markdown
## Iteration 1

**Timestamp:** 2025-01-26T10:15:30
**Phase:** FINAL_VERIFICATION
**Result:** FAILED
**Confidence:** 0.45

### Verification Report
- Tests run: 15
- Tests passed: 12
- Tests failed: 3
- Ground truth check: skipped
- Integration check: failed

### Root Cause (if failed)
- **Unmet requirements:** ["Authentication flow incomplete"]
- **Error files:** ["src/auth.py:78", "src/api/users.py:23"]
- **Fix type:** code_fix
- **Invalidated subtasks:** ["ST-003"]
- **Suggested action:** Add token refresh logic in auth.py

### Decision
→ RE_DECOMPOSE (iteration 1 < max 2)

---
```
