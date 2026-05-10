---
name: map-check
description: |
  Run quality gates (lint, types, tests) and verify MAP workflow completion. Use when user asks to run checks, validate a workflow, or confirm a MAP run is done. Do NOT use to plan or execute new tasks; use map-plan or map-efficient.
disable-model-invocation: true
argument-hint: "[focus area]"
---
# /map-check — Quality Gates & Verification

**Purpose:** Run code quality checks (linters, type checkers, tests) and/or verify MAP workflow completion.

**Two Modes:**

## Mode 1: Standalone Quality Check (No MAP workflow)

If no `.map/<branch>/step_state.json` exists, run full quality suite:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"

if [[ ! -f "$STATE_FILE" ]]; then
    echo "🔬 Running full quality checks (standalone mode)..."
    # Continue with quality checks below
fi
```

### Quality Checks by Language

**Python (if pyproject.toml/setup.py/requirements.txt exists):**
```bash
echo "=== Python Checks ==="
# Ruff (fast linter + formatter)
ruff check . && ruff format --check . && echo "✅ Ruff OK"
# MyPy (type checker)
mypy src/ --ignore-missing-imports && echo "✅ MyPy OK"
# Tests
pytest -x && echo "✅ Tests OK"
```

**Go (if go.mod exists):**
```bash
echo "=== Go Checks ==="
# Vet
go vet ./... && echo "✅ go vet OK"
# Staticcheck
staticcheck ./... && echo "✅ staticcheck OK"
# Tests
go test ./... -short && echo "✅ Tests OK"
```

**TypeScript/Node (if package.json exists):**
```bash
echo "=== TypeScript/Node Checks ==="
npm run lint && echo "✅ Lint OK"
npm run typecheck 2>/dev/null || tsc --noEmit && echo "✅ Types OK"
npm test && echo "✅ Tests OK"
```

**Rust (if Cargo.toml exists):**
```bash
echo "=== Rust Checks ==="
cargo check && echo "✅ cargo check OK"
cargo clippy -- -D warnings && echo "✅ Clippy OK"
cargo test && echo "✅ Tests OK"
```

### Output (Standalone Mode)

```
🔬 Running full quality checks (standalone mode)...

=== Python Checks ===
✅ Ruff OK
✅ MyPy OK
✅ Tests OK

=== Security ===
✅ No secrets in staged files
✅ No .env files staged

Summary: All checks passed!
```

**STOP after standalone checks.** No MAP workflow to verify.

---

## Mode 2: MAP Workflow Verification

If `.map/<branch>/step_state.json` exists, verify subtask completion.

**When to use:**
- After completing all subtasks
- Need to verify nothing was missed
- Ready to close out the task

**What this command does:**
- Calls final-verifier agent to audit completion
- Checks step_state.json for all subtasks marked SUBTASK_COMPLETE
- Validates acceptance criteria from task_plan_<branch>.md
- Runs final quality gates (tests, linter)
- **STOPS** with APPROVED or REJECTED verdict

**What this command CANNOT do:**
- ❌ Edit code (verification is read-only)
- ❌ Plan new work (use /map-plan for that)
- ❌ Execute missing subtasks

---

## Workflow Steps

### Step 1: Load Workflow State

Read the current state to understand what was completed:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"

# Use Read tool to load the state file contents
```

### Step 2: Validate All Subtasks Complete

Check that every subtask in subtask_sequence is marked SUBTASK_COMPLETE:

```bash
# Get subtask sequence
SUBTASKS=$(jq -r '.subtask_sequence[]' "$STATE_FILE")

# Check each subtask
for ST in $SUBTASKS; do
  PENDING=$(jq -r ".pending_steps[\"$ST\"] | length" "$STATE_FILE")
  if [[ "$PENDING" -gt 0 ]]; then
    echo "❌ $ST has pending steps:"
    jq -r ".pending_steps[\"$ST\"][]" "$STATE_FILE"
  fi
done
```

**If any subtask has pending steps:**
```
═══════════════════════════════════════════════════
⛔ VERIFICATION FAILED: Incomplete Subtasks
═══════════════════════════════════════════════════
The following subtasks are not complete:

- ST-002: Pending steps [actor, monitor, tests]
- ST-004: Pending steps [linter]

Action Required:
1. Complete pending subtasks
2. Re-run /map-check when all subtasks done

Cannot proceed with verification until all work is complete.
═══════════════════════════════════════════════════
```

**STOP** - do not proceed with verification.

### Step 3: Load Original Plan

Read task_plan_<branch>.md to get acceptance criteria:

```bash
PLAN_FILE=".map/${BRANCH}/task_plan_${BRANCH}.md"
# Use Read tool to load the plan file contents
```

### Step 4: Call Final Verifier

**MANDATORY:** Call final-verifier agent to audit the work:

```
Task(
  subagent_type="final-verifier",
  description="Verify all subtasks complete",
  prompt=f"""
Verify that all subtasks from the plan have been completed successfully.

Plan: {task_plan_content}
State: {step_state_content}

For each subtask, check:
1. All acceptance criteria met
2. Code changes align with description
3. Tests cover the implementation
4. No regressions introduced

Output: APPROVED or REJECTED with specific findings
"""
)
```

**Note:** final-verifier reads state from .map/ files directly, so you don't need to pass full context. Just invoke it.

### Step 5: Run Final Quality Gates

Even if verifier approves, run automated checks:

**Tests:**
```bash
TEST_CMD="pytest"  # Default; override if project uses different test runner
echo "Running final tests..."
eval "$TEST_CMD"

# Optional (structured diagnostics):
# If tests fail and you want a durable artifact for follow-up/debugging,
# re-run capturing output and parse to .map/<branch>/diagnostics.json:
#
# BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
# LOG_FILE=".map/${BRANCH}/tests.log"
# mkdir -p ".map/${BRANCH}"
# ( $TEST_CMD ) >"$LOG_FILE" 2>&1
# python3 .map/scripts/diagnostics.py parse --tool tests --log "$LOG_FILE" --command "$TEST_CMD" --exit-code $?

if [[ $? -ne 0 ]]; then
  echo "❌ Tests failed - verification REJECTED"
  VERDICT="REJECTED"
  REASON="Test suite has failures"
fi
```

**Linter:**
```bash
LINT_CMD="make lint"  # Default; override if project uses different linter
echo "Running final lint..."
eval "$LINT_CMD"

# Optional (structured diagnostics):
# BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
# LOG_FILE=".map/${BRANCH}/lint.log"
# mkdir -p ".map/${BRANCH}"
# ( $LINT_CMD ) >"$LOG_FILE" 2>&1
# python3 .map/scripts/diagnostics.py parse --tool lint --log "$LOG_FILE" --command "$LINT_CMD" --exit-code $?

if [[ $? -ne 0 ]]; then
  echo "❌ Linter failed - verification REJECTED"
  VERDICT="REJECTED"
  REASON="Code quality issues detected"
fi
```

**Git Status:**
```bash
# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
  echo "⚠️  Warning: Uncommitted changes detected"
  git status --short
fi
```

### Step 5b: Record Run Summary and Known Issues

After each major gate (tests, lint, final verifier), write a compact run summary and a timestamped run dossier under `.map/<branch>/runs/<timestamp>/`, and keep accepted blockers in `.map/<branch>/known-issues.json`.

Examples:

```bash
python3 .map/scripts/diagnostics.py summarize \
  --tool tests \
  --command "$TEST_CMD" \
  --exit-code $? \
  --summary "Pytest run for branch verification" \
  --known-issues ".map/${BRANCH}/known-issues.json" \
  --notes "Capture any deviations, flaky behavior, or environment quirks here"

python3 .map/scripts/map_step_runner.py ensure_known_issues_file
python3 .map/scripts/map_step_runner.py add_known_issue "Flaky integration test in CI" accepted "Non-blocking for local verification; tracked for follow-up"
```

Use `known-issues.json` only for issues intentionally accepted or deferred. Do NOT hide new blocking failures there.

Run dossier contract:

- `.map/<branch>/runs/<timestamp>/RESULTS.md` — mandatory
- `.map/<branch>/runs/<timestamp>/NOTES.md` — optional

`RESULTS.md` should act as the canonical historical record for that verification run and include:
- setup/context
- summary verdict
- test matrix row(s)
- detailed results
- bugs/blockers found
- accepted/deferred issues count

### Step 6: Update Workflow State (Complete)

If verification passes, mark workflow complete via the orchestrator. **Never edit `step_state.json` directly with `jq` / `sed`** — partial mutations leave `current_step_phase` stale and break `reopen_for_fixes` in the next `/map-review`.

```bash
python3 .map/scripts/map_orchestrator.py mark_workflow_complete
```

This atomically sets `workflow_status=WORKFLOW_COMPLETE`, `current_step_id=COMPLETE`, `current_step_phase=COMPLETE`, and `completed_at=<UTC ISO-8601>`. Refuses if any work is still pending.

### Step 7: Output Verification Report

Before printing the console report, update `.map/<branch>/verification-summary.md` with:

```bash
python3 .map/scripts/map_step_runner.py write_verification_summary "READY FOR REVIEW" "<task title>" "- pytest ...,- ruff ..." "- key findings" "- open PR"
```

This file should be a compact human-readable report with:
- branch and task title
- overall verdict (`READY FOR REVIEW` or `NEEDS WORK`)
- commands/tests run
- key failures or warnings
- recommended next step

Then persist canonical verification handoff artifacts:

```bash
# Machine-readable gate semantics
python3 .map/scripts/map_step_runner.py write_stage_gate \
  verification \
  ready \
  verification-summary.md \
  "Verification passed and branch is ready for review"

# Current unresolved set for the branch/workflow stage
python3 .map/scripts/map_step_runner.py ensure_active_issues_file
python3 .map/scripts/map_step_runner.py replace_active_issues \
  verification \
  verification-summary.md \
  "- [list unresolved verification issues here, or '(None)']"
```

Use these verdict mappings consistently:
- `ready` — verification passed, safe to move to `/map-review`
- `needs-revision` — implementation changes required before review
- `blocked` — external/tooling/environment issue prevents safe progress

Then build a handoff bundle and update `.map/<branch>/pr-draft.md` from the collected artifacts:

```bash
BUNDLE=$(python3 .map/scripts/map_step_runner.py build_handoff_bundle)
SUMMARY=$(echo "$BUNDLE" | jq -r '.summary')
VALIDATION=$(echo "$BUNDLE" | jq -r '.validation')
RISKS=$(echo "$BUNDLE" | jq -r '.risks_follow_up')
python3 .map/scripts/map_step_runner.py write_pr_draft "$SUMMARY" "$VALIDATION" "$RISKS"
```

This ensures `pr-draft.md` is built from actual workflow artifacts instead of freeform memory.
It also means `/map-review` can consume a single consolidated verification handoff instead of re-deriving the branch state from scratch.

Then write the deferred learning handoff so the philosophical `LEARN` stage stays cheap at runtime:

```bash
python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-check \
  "<task title>" \
  "READY FOR REVIEW|NEEDS WORK" \
  "<run /map-review next, or rework and rerun /map-check>" \
  "<optional verification note>"
```

This writes `.map/<branch>/learning-handoff.md` and `.json`, updates `artifact_manifest.json`, and lets `/map-learn` auto-load the workflow context later with no manual reconstruction.

Recommended format:

```markdown
# Verification Summary

- Branch: <branch>
- Task: <title>
- Verdict: READY FOR REVIEW | NEEDS WORK

## Checks Run
- pytest ...
- ruff ...

## Findings
- ...

## Next Action
- ...
```

Print detailed verification results:

**If APPROVED:**
```
═══════════════════════════════════════════════════
✅ VERIFICATION PASSED: All Subtasks Complete
═══════════════════════════════════════════════════
Task: [task_title from plan]
Branch: ${BRANCH}
Started: [started_at from step_state.json]
Completed: [completed_at from step_state.json]

Subtasks Verified:
✅ ST-001: [title] - All acceptance criteria met
✅ ST-002: [title] - All acceptance criteria met
✅ ST-003: [title] - All acceptance criteria met

Quality Gates:
✅ Tests: PASSED
✅ Linter: PASSED
✅ Final Verifier: APPROVED

Summary:
[final-verifier's summary of what was accomplished]

Next Steps:
1. Review changes: git diff main...${BRANCH}
2. Commit if needed: git add . && git commit -m "..."
3. Open PR: gh pr create --fill

Status: READY FOR REVIEW
═══════════════════════════════════════════════════
```

**If REJECTED:**
```
═══════════════════════════════════════════════════
❌ VERIFICATION FAILED: Issues Found
═══════════════════════════════════════════════════
Task: [task_title from plan]
Branch: ${BRANCH}

Issues Identified:

1. [Subtask ID]: [Issue description]
   - Expected: [acceptance criterion]
   - Actual: [what was found]
   - Fix: [recommended action]

2. [Another issue]
   ...

Quality Gates:
[✅/❌] Tests: [status]
[✅/❌] Linter: [status]
❌ Final Verifier: REJECTED

Action Required:
1. Fix issues listed above
2. Re-run affected subtasks
3. Re-verify: /map-check

Status: NEEDS WORK
═══════════════════════════════════════════════════
```

### Step 8: STOP

**This phase ends here.** Verification is complete. User can review the report and decide next steps.

---

## Design Rationale

**Why separate verification from execution?**

1. **Independent Audit:** Verifier has no bias from implementation decisions - fresh perspective.

2. **Clear Success Signal:** Explicit approval/rejection eliminates ambiguity about completion.

3. **Quality Assurance:** Final gates catch regressions that might slip through individual subtask checks.

4. **Workflow Closure:** Provides psychological completion and clear transition to review/merge phase.

---

## Enforcement Mechanisms

**Read-Only Nature:**
- final-verifier agent does NOT have Edit/Write capabilities
- workflow-gate.py would block edits anyway (this command doesn't update completed_steps)
- Forces separation between audit and correction

**State Machine Validation:**
- Checks step_state.json to ensure all subtasks are SUBTASK_COMPLETE
- Verifies no pending_steps remain
- Transitions to WORKFLOW_COMPLETE only if all checks pass

---

## Related Commands

- **/map-plan** - Create task decomposition (run first)
- **/map-check** - This command (run last)
- **/map-efficient** - Monolithic workflow (alternative to phased approach)

---

## Example Usage

```bash
# After completing all subtasks from /map-plan:

User: "/map-check"

# Scenario 1: Success
# Output: ✅ VERIFICATION PASSED with full report
# User can now open PR or merge

# Scenario 2: Failure
# Output: ❌ VERIFICATION FAILED
# - ST-002 missing test coverage
# - Linter found unused imports

# User fixes issues:
# User fixes ST-002 issues directly

# User re-verifies:
User: "/map-check"
# Output: ✅ VERIFICATION PASSED
```

---

## Verification Checklist

The final-verifier agent checks:

**Per Subtask:**
- [ ] All acceptance criteria from plan met
- [ ] Code changes align with subtask description
- [ ] Implementation follows project conventions
- [ ] Tests exist and cover implementation
- [ ] No obvious bugs or security issues

**Whole Task:**
- [ ] All subtasks completed (step_state.json)
- [ ] No pending steps remain
- [ ] Integration between subtasks works correctly
- [ ] No regressions in existing functionality
- [ ] Documentation updated if needed

**Quality Gates:**
- [ ] Test suite passes
- [ ] Linter passes
- [ ] No uncommitted changes (warning only)

---

## Troubleshooting

**Q: Verification failed but I think everything is done?**
A: Read the REJECTED report carefully. final-verifier found specific gaps - address each one listed.

**Q: Can I skip verification and just open a PR?**
A: You can, but verification catches issues before review. Better to fix now than get PR feedback.

**Q: Verification passed but tests are red in CI?**
A: Local environment differs from CI. Check:
- Python/Node version mismatch
- Missing dependencies in CI
- Different test data or fixtures

**Q: How do I re-verify after fixes?**
A: Just run `/map-check` again. It reads current state and re-runs all checks.

---

## Success Criteria

This command succeeds when:
- ✅ All subtasks in step_state.json are SUBTASK_COMPLETE
- ✅ final-verifier returned APPROVED
- ✅ All quality gates passed (tests, linter)
- ✅ Verification report printed with detailed findings
- ✅ step_state.json updated to WORKFLOW_COMPLETE
- ✅ You STOPPED (did not edit code or start new work)

---

## State Transition

This command transitions step_state.json:

```
SUBTASK_COMPLETE (all subtasks) → WORKFLOW_COMPLETE
```

After WORKFLOW_COMPLETE, the task is done. User can:
- Review git diff
- Commit changes
- Open pull request
- Start new task with /map-plan


## Examples

```
/map-check <typical args>
```
