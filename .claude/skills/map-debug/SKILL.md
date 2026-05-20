---
name: map-debug
description: |
  Structured MAP debugging via task-decomposer, actor, and monitor agents. Use when reproducing a bug, isolating a regression, or diagnosing an error with specialized agents. Do NOT use for greenfield features; use map-plan or map-efficient.
effort: medium
disable-model-invocation: true
argument-hint: "[bug description]"
---
# MAP Debugging Workflow

## Workflow Guardrails

Use the specialized MAP agents because debugging depends on isolated root-cause evidence:

- Start with `task-decomposer` so investigation, fix, and verification work are separated.
- Use `actor` for each investigation or fix subtask rather than a general-purpose agent.
- Use `monitor` after each fix subtask so written code is validated before impact analysis.
- Use `predictor` and `evaluator` only after Monitor approves a fix, as described below.
- Do not combine phases to save time; each phase consumes the previous phase's evidence.

Debug the following issue using the MAP framework:

**Debug Request:** $ARGUMENTS

Use compact evidence-first examples from [Evidence-First Output Examples](../../references/map-output-examples.md) when asking agents to report root causes, validation failures, or impact risks. Use the shared [XML Prompt Envelope](../../references/map-xml-prompt-envelopes.md) for long debugging prompts so logs, affected files, and fixes are separated from instructions and output contracts.

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: sequential_root_cause_first
```

- Spend reasoning on reproducing symptoms, isolating the root cause, and verifying the fix; do not drift into broad cleanup or feature work.
- Keep the debugging pipeline sequential because each phase depends on the latest evidence and written repo state.
- Parallelize only independent read-only log/code searches during initial investigation.

## When Not To Expand Scope

- Do not turn a bug fix into a refactor, feature, or architecture cleanup unless the root cause requires that change.
- Do not add extra agents beyond the documented debugging sequence; switch workflows only if the task stops being a debugging task.
- Do not continue polishing after the original symptom is reproduced, fixed, and verified.

## Mutation Boundary Constraints

These constraints apply to every fix subtask:

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the root cause evidence explicitly requires that dependency change.
- Do not refactor neighboring code unless the bug cannot be fixed and verified without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff instead of doing it silently.

## Workflow Overview

Debugging workflow focuses on analysis before implementation:

```
1. DECOMPOSE → task-decomposer (break down debugging steps)
2. FOR each debugging step:
   3. IMPLEMENT → actor (edit files directly)
   4. VALIDATE → monitor (check written files)
   5. PREDICT → predictor (assess impact of fix)
   6. EVALUATE → evaluator (verify fix quality)
   7. Keep Actor's already-written fix
3. DONE → Suggest /map-learn if user wants to preserve patterns
```

## Step 1: Analyze the Issue

Before calling task-decomposer, gather context:

1. **Read error logs/stack traces** (if provided in $ARGUMENTS)
2. **Identify affected files**: Use Grep/Glob to find relevant code
3. **Reproduce the issue** (if possible): Read test files or run commands

## Step 2: Decompose Debugging Process

```
Task(
  subagent_type="task-decomposer",
  description="Decompose debugging steps",
  prompt="<documents>
  <document source='debug-request'>
    <document_content>$ARGUMENTS</document_content>
  </document>
  <document source='error-logs'>
    <document_content>[if available]</document_content>
  </document>
  <document source='affected-files'>
    <document_content>[from analysis]</document_content>
  </document>
</documents>

<task>
Break down this debugging process into atomic investigation, fix, and verification steps.
</task>

JSON contract reference: [Decomposition Output](../../references/map-json-output-contracts.md#decomposition-output).

<expected_output>
Output JSON with:
- subtasks: array of {id, description, debug_type: 'investigation'|'fix'|'verification', acceptance_criteria}
- root_cause_hypothesis: string
- estimated_complexity: 'low'|'medium'|'high'
</expected_output>

<constraints>
Debug types:
- investigation: analyze code, logs, reproduce issue
- fix: implement solution
- verification: test fix, check for regressions
</constraints>"
)
```

## Step 3: For Each Debugging Step

### Investigation Steps

For subtasks with `debug_type: 'investigation'`:

```
Task(
  subagent_type="actor",
  description="Investigate issue",
  prompt="Investigate this debugging step:

**Step:** [description]
**Goal:** [acceptance_criteria]

Perform analysis and provide:
- quotes: array of {source, locator, quote, relevance}; quote exact logs, test output, or code fragments before root_cause
- findings: array of observations
- root_cause: string (if identified)
- next_steps: array of recommended actions
- code_locations: array of {file, line_range, issue_description}

Use Read, Grep tools to analyze code. Do NOT make changes yet."
)
```

### Fix Steps

For subtasks with `debug_type: 'fix'`:

```
Task(
  subagent_type="actor",
  description="Implement fix for [issue]",
  prompt="Implement a fix for this issue:

**Issue:** [from investigation]
**Root Cause:** [identified root cause]

Apply the fix directly with Edit/Write tools.
Do not edit unrelated files, add or upgrade dependencies, or refactor neighboring code unless the root cause evidence explicitly requires it. Report any required scope expansion as a blocker/tradeoff.

JSON contract reference: [Actor Change Summary](../../references/map-json-output-contracts.md#actor-change-summary).

Output JSON with:
- approach: string (fix strategy)
- files_changed: array of file paths actually edited
- tests_run: array of commands run, or [] if deferred to the orchestrator
- why_this_fixes_it: string (explain the fix)
- potential_side_effects: array of strings
- remaining_risks: array of strings

Do not serialize full file contents in your response."
)
```

### Monitor Validation

After each fix (max 5 Actor->Monitor retry iterations per subtask):

```
Task(
  subagent_type="monitor",
  description="Validate fix",
  prompt="<documents>
  <document source='original-issue'>
    <document_content>[description]</document_content>
  </document>
  <document source='written-files'>
    <document_content>Written Files: [files_changed from Actor]</document_content>
  </document>
  <document source='root-cause'>
    <document_content>[identified root cause]</document_content>
  </document>
</documents>

<task>
Validate this debugging fix in the written repo state.
</task>

<instructions>
Check:
- Read the written files and verify the code exists in the repo
- Does the fix address the root cause?
- Are there any security issues introduced?
- Are there proper error handling?
- Is the fix testable?
- Are there any edge cases missed?
</instructions>

<expected_output>
Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; cite the changed code or failing/passing test before verdict fields
- valid: boolean
- issues: array of {severity, category, description}
- verdict: 'approved'|'needs_revision'|'rejected'
- feedback: string
</expected_output>"
)
```

### Predictor Impact Analysis

For approved fixes:

```
Task(
  subagent_type="predictor",
  description="Analyze fix impact",
  prompt="Analyze the impact of this debugging fix:

**Fix:** [paste actor JSON]
**Monitor Verdict:** approved

Analyze:
- Could this fix introduce new bugs?
- Are there other places with similar issues?
- Does this require updating tests?
- Are there performance implications?

Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; include support for each similar issue or high-risk claim
- similar_issues: array of {file, line, description}
- risk_level: 'low'|'medium'|'high'
- recommended_additional_changes: array of strings
- regression_test_requirements: array of strings"
)
```

### Evaluator Quality Check

```
Task(
  subagent_type="evaluator",
  description="Evaluate fix quality",
  prompt="Evaluate this debugging fix:

**Fix:** [paste actor JSON]
**Monitor Verdict:** [verdict]
**Predictor Analysis:** [paste predictor JSON]

Score (0-10):
- correctness: does it fix the issue?
- completeness: are all edge cases covered?
- clarity: is the fix understandable?
- testing: is it properly tested?

Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; cite changed code or test output for any score below 7
- scores: object
- overall_score: number
- recommendation: 'proceed'|'improve'|'reject'
- justification: string"
)
```

### Proceed After Evaluation

If evaluator recommends proceeding:
- Keep Actor's already-written changes
- Run tests to verify fix
- Check that original issue is resolved
- Write a deferred learning handoff so `/map-learn` can reuse the debug context later:

```bash
python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-debug \
  "$ARGUMENTS" \
  "Debugging workflow complete" \
  "Ship the fix, or run /map-review if you want independent scrutiny" \
  "<root cause + fix summary>"
```

This writes `.map/<branch>/learning-handoff.md` and `.json`, updates `artifact_manifest.json`, and keeps post-debug learning cheap.

## Step 4: Verification

After all fixes applied:

1. **Run full test suite** to check for regressions
2. **Verify original issue is resolved**
3. **Check predictor's similar_issues** - fix those too if relevant
4. **Create commit** with clear description of fix and root cause
5. **Write a run health report** with the terminal status that matches the verified debug outcome:

```bash
# Set from verification: complete, pending, blocked, won't_do, or superseded.
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set RUN_HEALTH_STATUS from the debug verification outcome}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-debug \
  "$RUN_HEALTH_STATUS"
```

Use `complete` only when the bug is fixed and verified. Use `pending` when more code work remains, `blocked` when an external/tooling dependency prevents verification, `won't_do` when the fix is intentionally abandoned, and `superseded` when another branch/workflow owns the resolution. This writes `.map/<branch>/run_health_report.json`, updates the `run_health` stage in `artifact_manifest.json`, and gives reviewers one machine-readable snapshot of retries, artifact presence, hook status, and terminal state.

---

## 💡 Optional: Preserve Debugging Lessons

**If you want to save debugging patterns for future use:**

```
/map-learn
```

This is **completely optional**. Run it when debugging patterns are valuable for future reference.

## MCP Tools for Debugging

- `mcp__sequential-thinking__sequentialthinking` - Complex root cause analysis
- `mcp__deepwiki__ask_question` - Learn from how others solved similar issues

## Debugging Constraints

- Identify the root cause before implementing fixes.
- Test after applying fixes.
- Check for similar issues in other parts of the codebase when Predictor flags them or the root cause pattern is reusable.
- Use the Task tool to call the specialized subagents in the sequence above.

## Example

User says: `/map-debug TypeError in authentication middleware`

You should:
1. Gather context (read error logs, find middleware file)
2. Task(subagent_type="task-decomposer") → get investigation + fix steps
3. For investigation steps: Task(subagent_type="actor") to analyze
4. For fix steps: actor → monitor → predictor → evaluator → apply
5. Run tests, verify fix
6. Done! Optionally run `/map-learn` to preserve debugging patterns

Begin debugging now.


## Examples

```
/map-debug <typical args>
```

## Troubleshooting

- **Issue:** Workflow doesn't behave as expected. **Fix:** Re-read the section above titled 'What this command CANNOT do' (if present) and ensure prerequisites are met. Run `/map-resume` to recover from interruptions.
