---
name: map-check
description: |
  Run quality gates (lint, types, tests) and verify MAP workflow completion. Use when user asks to run checks, validate a workflow, or confirm a MAP run is done. Do NOT use to plan or execute new tasks; use map-plan or map-efficient.
effort: low
disable-model-invocation: true
argument-hint: "[focus area]"
---
# /map-check - Quality Gates & Verification

Purpose: run quality gates and MAP workflow verification only. Do not plan, implement, or fix from this skill.
Use [check-reference.md](check-reference.md) for command matrices, examples, and troubleshooting. When a workflow step points to a reference section, read that section before executing the step; supporting files are not assumed to be in context automatically.

## Effort and Parallelism Policy

```yaml
thinking_policy: low/direct
parallel_tool_policy: independent_checks_only
```

- Stay in verification mode: run the relevant gates, interpret failures, and stop with a clear pass/fail summary.
- Do not plan or execute new work from this skill. If checks reveal missing implementation, report it and hand off to `/map-task`, `/map-efficient`, or `/map-debug`.
- Parallelize only independent quality gates or artifact reads. Do not parallelize final-verifier, state validation, or any step that depends on previous check output.

## When Not To Expand Scope

- Do not fix failures from inside `/map-check`; report the failing gate and hand off to the workflow that should own the fix.
- Do not decompose, research, or implement new subtasks from this skill.
- Do not run extra audits after the requested quality gates and MAP completion checks have a clear pass/fail result.

## Mode 1: Standalone Quality Check (No MAP workflow)

Use this mode when `.map/<branch>/step_state.json` does not exist.

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "Running standalone quality checks."
fi
```

### Quality Checks by Language

Run the repo's configured checks first. If no repo command exists, use the language fallbacks in [check-reference.md](check-reference.md#quality-checks-by-language).

Python fallback:
```bash
ruff check .
ruff format --check .
mypy src/ --ignore-missing-imports
pytest -x
```

Go fallback:
```bash
go vet ./...
staticcheck ./...
go test ./... -short
```

TypeScript/Node fallback:
```bash
npm run lint
npm run typecheck 2>/dev/null || tsc --noEmit
npm test
```

Rust fallback:
```bash
cargo check
cargo clippy -- -D warnings
cargo test
```

### Output (Standalone Mode)

Report checks run, pass/fail status, first actionable failure, and next action. Then STOP. There is no MAP workflow to verify.

## Mode 2: MAP Workflow Verification

Use this mode when `.map/<branch>/step_state.json` exists.

This mode verifies that implementation is complete, quality gates pass, review artifacts are updated, and closeout state is machine-readable.

What this command does:
- Calls final-verifier to audit completion against the persisted plan.
- Checks every subtask is complete in `step_state.json`.
- Runs final tests/lint/build gates.
- Writes `.map/<branch>/verification-summary.md` and `.json`.
- Writes `.map/<branch>/run_health_report.json` with `run_health` manifest status.
- Stops with `READY FOR REVIEW`, `NEEDS WORK`, or `BLOCKED`.

What this command cannot do:
- Edit code.
- Plan new work.
- Execute missing subtasks.

## Workflow Steps

### Step 1: Load Workflow State

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
STATE_FILE=".map/${BRANCH}/step_state.json"
PLAN_FILE=".map/${BRANCH}/task_plan_${BRANCH}.md"
```

Read `step_state.json` and the task plan. If either required artifact is missing, report `BLOCKED` unless this is standalone mode.

### Step 2: Validate All Subtasks Complete

Schema note: `step_state.json` carries `pending_steps` as a FLAT `list[str]` of
workflow phase ids (e.g. `"2.2"`, `"2.3"`) scoped to the currently active
subtask — it is NOT a dict keyed by subtask id. The workflow-level completion
signal is `workflow_status == "WORKFLOW_COMPLETE"`. Treating `pending_steps`
as `.pending_steps["ST-001"]` crashes jq with `Cannot index array with string`.

```bash
WORKFLOW_STATUS=$(jq -r '.workflow_status // ""' "$STATE_FILE")
CURRENT_ST=$(jq -r '.current_subtask_id // ""' "$STATE_FILE")
CURRENT_PHASE=$(jq -r '.current_step_phase // ""' "$STATE_FILE")
PENDING_COUNT=$(jq -r '.pending_steps | length' "$STATE_FILE")
SUBTASK_INDEX=$(jq -r '.subtask_index // 0' "$STATE_FILE")
SUBTASK_TOTAL=$(jq -r '.subtask_sequence | length' "$STATE_FILE")

if [[ "$WORKFLOW_STATUS" != "WORKFLOW_COMPLETE" ]]; then
  echo "Workflow incomplete: status=$WORKFLOW_STATUS, current=$CURRENT_ST ($CURRENT_PHASE), subtask $((SUBTASK_INDEX + 1)) of $SUBTASK_TOTAL"
  if [[ "$PENDING_COUNT" -gt 0 ]]; then
    echo "Pending workflow phases for $CURRENT_ST:"
    jq -r '.pending_steps[]' "$STATE_FILE"
  fi
fi
```

If `workflow_status` is not `WORKFLOW_COMPLETE` (or any phase is still pending), STOP with `NEEDS WORK` and name the handoff command (`/map-task`, `/map-efficient`, or `/map-debug`).

### Step 3: Load Original Plan

Read `task_plan_<branch>.md` for acceptance criteria, subtask scopes, and validation criteria.

### Step 4: Call Final Verifier

```text
Task(
  subagent_type="final-verifier",
  description="Verify all subtasks complete",
  prompt="""
Verify all subtasks from the plan are complete.

Read these artifacts from disk:
- .map/<branch>/task_plan_<branch>.md
- .map/<branch>/step_state.json
- .map/<branch>/artifact_manifest.json
- verification/test/check artifacts present in the manifest

Source authority: source files, tests, schemas, and configs beat transcripts, summaries, commit messages, and stale docs. If a plan or transcript claim disagrees with source, report drift and trust source.

Dismissal verdict gate: any `false_positive`, `covered`, `out_of_scope`, `pre_existing`, `no_tests_needed`, `safe_to_skip`, or `not_applicable` claim requires `path:line` source evidence, a quote, and confidence. Without source evidence, output `needs_investigation`.

For each subtask, check:
1. acceptance criteria met
2. code changes align with the subtask description
3. tests cover the implementation
4. no obvious regressions introduced

Output APPROVED or REJECTED with specific findings.
"""
)
```

### Step 5: Run Final Quality Gates

Run project-native checks first. If no project command exists, use the fallback matrix in [check-reference.md](check-reference.md#quality-checks-by-language).

Optional structured diagnostics for failing gates:
```bash
TEST_CMD="${TEST_CMD:-pytest}"
LOG_FILE=".map/${BRANCH}/tests.log"
mkdir -p ".map/${BRANCH}"
set +e
$TEST_CMD >"$LOG_FILE" 2>&1
TEST_EXIT=$?
set -e
python3 .map/scripts/diagnostics.py parse --tool tests --log "$LOG_FILE" --command "$TEST_CMD" --exit-code "$TEST_EXIT"
```

Also check git state:
```bash
git status --short
```

### Step 5b: Record Run Summary and Known Issues

After each major gate, write a compact run summary and use `known-issues.json` only for intentionally accepted or deferred issues.

```bash
python3 .map/scripts/diagnostics.py summarize \
  --tool tests \
  --command "$TEST_CMD" \
  --exit-code "$TEST_EXIT" \
  --summary "Pytest run for branch verification" \
  --known-issues ".map/${BRANCH}/known-issues.json" \
  --notes "Capture deviations, flaky behavior, or environment quirks here"

python3 .map/scripts/map_step_runner.py ensure_known_issues_file
python3 .map/scripts/map_step_runner.py add_known_issue "Flaky integration test in CI" accepted "Non-blocking for local verification; tracked for follow-up"
```

### Step 6: Update Workflow State (Complete)

Use the final result to set `RUN_HEALTH_STATUS`:

- `READY FOR REVIEW -> complete`
- `NEEDS WORK -> pending`
- external/tooling blocker -> `blocked`

```bash
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set from final verification result}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-check \
  "$RUN_HEALTH_STATUS"
```

This writes `.map/<branch>/run_health_report.json`, updates the `run_health` stage, and preserves terminal state for reviewers and operators.

### Step 7: Output Verification Report

Before printing the console report, update `.map/<branch>/verification-summary.md` and the handoff artifacts:

```bash
python3 .map/scripts/map_step_runner.py write_verification_summary "READY FOR REVIEW" "<task title>" "- pytest ...,- ruff ..." "- key findings" "- open PR"

python3 .map/scripts/map_step_runner.py write_stage_gate \
  verification \
  ready \
  verification-summary.md \
  "Verification passed and branch is ready for review"

python3 .map/scripts/map_step_runner.py ensure_active_issues_file
python3 .map/scripts/map_step_runner.py replace_active_issues \
  verification \
  verification-summary.md \
  "- [list unresolved verification issues here, or '(None)']"

BUNDLE=$(python3 .map/scripts/map_step_runner.py build_handoff_bundle)
SUMMARY=$(echo "$BUNDLE" | jq -r '.summary')
VALIDATION=$(echo "$BUNDLE" | jq -r '.validation')
RISKS=$(echo "$BUNDLE" | jq -r '.risks_follow_up')
python3 .map/scripts/map_step_runner.py write_pr_draft "$SUMMARY" "$VALIDATION" "$RISKS"

python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-check \
  "<task title>" \
  "READY FOR REVIEW|NEEDS WORK" \
  "<run /map-review next, or rework and rerun /map-check>" \
  "<optional verification note>"
```

Use this compact structure:

```markdown
# Verification Summary

Status: READY FOR REVIEW | NEEDS WORK | BLOCKED

## Checks Run
- <command>: pass/fail

## Findings
- <file/step>: <issue or evidence>

## Next Action
- <exact handoff command or review readiness statement>
```

### Step 8: STOP

Stop after the report. If `NEEDS WORK`, do not fix it here; hand off to the owner workflow.

## Enforcement Mechanisms

- `step_state.json` proves subtask completion.
- final-verifier audits plan coverage.
- automated checks prove the repo state.
- `verification-summary.md/json` records human and machine-readable evidence.
- `run_health_report.json` records terminal status and artifact health.

## Related Commands

- `/map-task` resumes one incomplete subtask.
- `/map-efficient` owns implementation fixes.
- `/map-debug` owns root-cause investigation.
- `/map-review` runs structured review after `READY FOR REVIEW`.

## Examples

See [check-reference.md](check-reference.md#examples) for success/failure transcripts and language-specific command examples.

## Troubleshooting

See [check-reference.md](check-reference.md#troubleshooting) for missing state, verifier rejection, diagnostics parsing, and blocked closeout cases.

## Success Criteria

- Every subtask is complete or the report names the owner workflow.
- final-verifier verdict is recorded.
- Automated checks were actually run or a concrete blocker is documented.
- `write_run_health_report` ran with a non-default `RUN_HEALTH_STATUS`.
- The final answer gives a clear `READY FOR REVIEW`, `NEEDS WORK`, or `BLOCKED` result.
