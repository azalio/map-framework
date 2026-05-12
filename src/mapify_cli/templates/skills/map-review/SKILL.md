---
name: map-review
description: |
  Interactive 4-section code review using Monitor, Predictor, and Evaluator agents on current changes. Use when reviewing a diff, PR, or staged work before merge. Do NOT use to plan or implement; use map-plan or map-efficient.
disable-model-invocation: true
argument-hint: "[review focus] [--detached] [--ci]"
---
# MAP Review Workflow

Interactive, structured code review of current changes using Monitor, Predictor, and Evaluator agents.

**Task:** $ARGUMENTS

## Flags

- `--ci` / `--auto` — Non-interactive mode; auto-select recommended options. Suitable for CI pipelines.
- `--detached` — Prepare an isolated git worktree for the review so reviewer agents read source files
  from a clean detached context. The source branch is **never mutated** (no `git checkout`, no `git stash`,
  no working-tree edits). If the detached path already exists, the helper reports `unavailable` and the
  review **still proceeds** using the in-place bundle (graceful degradation). The detached worktree is
  created at `.map/<branch>/detached-review/`.

## Execution Rules

1. Execute all steps in the order listed below
2. Use the exact `subagent_type` values specified (monitor, predictor, evaluator)
3. All 3 agents are required — do not skip any
4. **Monitor `valid=false` is a hard stop** — report issues immediately, do not proceed to interactive presentation
5. Wait for all parallel calls to complete before proceeding to the next phase

## Review Preferences (Customize per project)

These defaults guide how agents weigh findings. Override by editing this section:

- **DRY:** Important — flag duplication aggressively
- **Testing:** Non-negotiable — missing tests = high severity
- **Engineering level:** "Engineered enough" — reject both under-engineering and over-engineering
- **Edge cases:** Prefer handling more, especially for public APIs
- **Clarity:** Explicit over clever — readable code wins
- **Performance:** Flag only when measurable impact is likely

## Expected Agent Output Schemas (Contract Reference)

These are the fields each agent is expected to return. The command prompt explicitly requests them.

**Monitor:**
- `valid`: boolean — overall pass/fail
- `summary`: string — brief description of findings
- `verdict`: `'approved'` | `'needs_revision'` | `'rejected'` — requested explicitly (not in base schema, `additionalProperties: true`)
- `issues[]`: array of `{severity, category, description, file_path, line_range, suggestion}`
- `passed_checks[]`: array of strings — checks that passed
- `failed_checks[]`: array of strings — checks that failed

**Predictor:**
- `risk_assessment`: `'low'` | `'medium'` | `'high'` | `'critical'`
- `predicted_state.affected_components[]`: array of affected components/files
- `predicted_state.breaking_changes[]`: array of `{type, description, mitigation}`
- `predicted_state.required_updates[]`: array of required follow-up changes
- `confidence.score`: float 0.0-1.0

**Evaluator:**
- `scores.functionality`: int 0-10
- `scores.code_quality`: int 0-10
- `scores.performance`: int 0-10
- `scores.security`: int 0-10
- `scores.testability`: int 0-10
- `scores.completeness`: int 0-10
- `overall_score`: float 1.0-10.0 (weighted)
- `recommendation`: `'proceed'` | `'improve'` | `'reconsider'`
- `strengths[]`: array of strings
- `weaknesses[]`: array of strings
- `next_steps[]`: array of strings

## Review Section Protocol

This protocol is used identically by all 4 review sections below. Do NOT deviate.

1. **Present top 4 issues** from the primary source agent for this section, using the section prefix (e.g., ARCH-1, QUALITY-2, TESTS-1, PERF-3)
2. **For each issue:**
   - Describe the problem with `file:line` references where available
   - Present 2-3 options with tradeoffs (pros/cons for each)
   - **Recommended option is always listed first** (marked with "(Recommended)")
3. **AskUserQuestion** with numbered issues and lettered options for each
   - Example: "ARCH-1: Option A (Recommended) / Option B / Option C"
   - **Skip AskUserQuestion in CI mode** — auto-select recommended options
4. **Summarize decisions** from this section in 3-5 lines before proceeding to the next section
   - Include: which issues were addressed, which options were chosen, what remains

## Step 0: Detect CI Mode and Flags

**Parse $ARGUMENTS for `--ci` or `--auto`:**
- If `--ci` or `--auto` is present in $ARGUMENTS → set CI_MODE=true
- CI_MODE skips all AskUserQuestion calls and auto-selects recommended options

**Parse $ARGUMENTS for `--detached`:**
```bash
DETACHED_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--detached'; then
  DETACHED_FLAG=true
  ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--detached//g' | xargs)
fi
```

**Always use comprehensive review** — up to 4 issues per section, no mode selection menu.

## Phase A: Collection (Parallel)

### Step A.1: Gather changes

```bash
git diff HEAD
git status
```

Save the diff output — it will be passed to all 3 agents.

### Step A.1b: Load canonical review context (bundle + handoff)

Before launching agents, build and load the persisted review bundle so review works
from all accumulated MAP artifacts rather than reconstructing context ad hoc.

**MANDATORY — run `create_review_bundle` first:**

```bash
BUNDLE_JSON=$(python3 .map/scripts/map_step_runner.py create_review_bundle)
BUNDLE_JSON_PATH=$(echo "$BUNDLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['bundle_path_json'])")
```

This produces two durable files:
- `.map/<branch>/review-bundle.json` — machine-readable PRIMARY review contract
- `.map/<branch>/review-bundle.md` — human-readable summary of the same data

Read `.map/<branch>/review-bundle.md` now and pass its content to all three agents
as their **primary context**. The bundle surfaces, when present:
- `spec` and `task_plan` artifacts (what was planned)
- latest `plan-review-00N.md` and `code-review-00N.md` (prior review history)
- `verification-summary.md` and `qa-001.md`
- `pr-draft.md` and `active-issues.json`
- artifact manifest status and git code state

Then also load the legacy handoff for any supplementary fields:

```bash
HANDOFF=$(python3 .map/scripts/map_step_runner.py build_review_handoff)
```

**Priority rule:** bundle artifacts are PRIMARY context; raw diff is SECONDARY
(use diff only to confirm or expand specific findings the bundle surfaces).

### Step A.1c: Prepare detached review context (optional, `--detached` only)

If `DETACHED_FLAG=true`, invoke the helper and parse the result:

```bash
DETACHED_RESULT=$(python3 .map/scripts/map_step_runner.py prepare_detached_review "$BUNDLE_JSON_PATH")
DETACHED_STATUS=$(echo "$DETACHED_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])")
DETACHED_PATH=$(echo "$DETACHED_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worktree_path') or '')")
DETACHED_REASON=$(echo "$DETACHED_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reason') or '')")
```

Handle all three outcomes — the workflow **still proceeds** in every case:

- **`status=success`**: Announce the detached worktree path to the user. Instruct reviewer agents
  to read source files from `$DETACHED_PATH` (read-only — do NOT edit files in the detached
  worktree). Pass `DETACHED_PATH` as additional context in each agent prompt.
- **`status=unavailable`**: Announce the reason (e.g., path already exists — does NOT overwrite).
  Continue review using the in-place bundle. The review still proceeds normally.
- **`status=error`**: Announce the error reason. Continue review using the in-place bundle.
  The review still proceeds normally.

The source branch is **never mutated** by `prepare_detached_review` — no `git checkout`,
`git stash`, `git reset`, or any working-tree edits are performed.

### Step A.2: Launch all parallel calls

In **ONE message**, launch all 3 calls in parallel (no dependencies between them):

**3 agent Task calls** (pass the bundle summary + git diff + Review Preferences to each):

```
Task(
  subagent_type="monitor",
  description="Review code changes",
  prompt="Your primary context is the persisted review bundle at `.map/<branch>/review-bundle.json`
(human-readable summary at `.map/<branch>/review-bundle.md`). Read the bundle first.
Use the raw diff only to confirm or expand specific findings the bundle surfaces.

**Review Bundle Summary:**
[paste contents of .map/<branch>/review-bundle.md]

**Review Preferences:**
[paste Review Preferences section above]

**Changes (secondary — use to confirm bundle findings):**
[paste git diff output]

Check for:
- Code correctness and logic errors
- Security vulnerabilities (OWASP top 10)
- Standards compliance
- Test coverage gaps
- Performance issues

Output JSON with:
- valid: boolean
- summary: string
- verdict: 'approved' | 'needs_revision' | 'rejected'
- issues: array of {severity, category, description, file_path, line_range, suggestion}
- passed_checks: array of strings
- failed_checks: array of strings"
)

Task(
  subagent_type="predictor",
  description="Analyze change impact",
  prompt="Your primary context is the persisted review bundle at `.map/<branch>/review-bundle.json`
(human-readable summary at `.map/<branch>/review-bundle.md`). Read the bundle first.
Use the raw diff only to confirm or expand specific findings the bundle surfaces.

**Review Bundle Summary:**
[paste contents of .map/<branch>/review-bundle.md]

**Review Preferences:**
[paste Review Preferences section above]

**Changes (secondary — use to confirm bundle findings):**
[paste git diff output]

Analyze:
- Affected components and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment (low/medium/high/critical)
- Integration points affected

Output JSON with:
- risk_assessment: 'low' | 'medium' | 'high' | 'critical'
- predicted_state:
    affected_components: array of affected files/modules
    breaking_changes: array of {type, description, mitigation}
    required_updates: array of strings
- confidence:
    score: float 0.0-1.0"
)

Task(
  subagent_type="evaluator",
  description="Score change quality",
  prompt="Your primary context is the persisted review bundle at `.map/<branch>/review-bundle.json`
(human-readable summary at `.map/<branch>/review-bundle.md`). Read the bundle first.
Use the raw diff only to confirm or expand specific findings the bundle surfaces.

**Review Bundle Summary:**
[paste contents of .map/<branch>/review-bundle.md]

**Review Preferences:**
[paste Review Preferences section above]

**Changes (secondary — use to confirm bundle findings):**
[paste git diff output]

Provide quality assessment using 1-10 scoring:
- Functionality score (1-10)
- Code quality score (1-10)
- Performance score (1-10)
- Security score (1-10)
- Testability score (1-10)
- Completeness score (1-10)

Output JSON with:
- scores: {functionality, code_quality, performance, security, testability, completeness}
- overall_score: weighted float (1.0-10.0)
- recommendation: 'proceed' | 'improve' | 'reconsider'
- strengths: array of strings
- weaknesses: array of strings
- next_steps: array of strings"
)
```

**Parallel execution:** All 3 agent calls MUST be issued in a single message. Wait for all to complete before proceeding.

### Hard Stop Check

After all agents complete, check Monitor output:
- If `Monitor.valid = false` → **HARD STOP**. Present Monitor issues immediately and do not proceed to Phase B. The user must fix issues before re-running the review.

## Phase B: Interactive Presentation (4 Sections)

Present findings section by section. Each section follows the **Review Section Protocol** defined above.

### Section 1: Architecture

**Primary source:** Predictor (`breaking_changes`, `affected_components`, `risk_assessment`)
**Cross-reference:** Evaluator `scores.completeness`
**Issue prefix:** `ARCH`

Focus on:
- Breaking changes and their mitigations
- Affected component blast radius
- Architectural fit of the changes
- Completeness of the change set (are all affected areas updated?)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 2

### Section 2: Code Quality

**Primary source:** Monitor (`issues` filtered by category: correctness, code-quality, maintainability)
**Cross-reference:** Evaluator `scores.code_quality`
**Issue prefix:** `QUALITY`

Focus on:
- Correctness issues (logic errors, edge cases)
- Code quality issues (naming, structure, DRY violations)
- Maintainability concerns
- Standards compliance

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 3

### Section 3: Tests

**Primary source:** Monitor (`issues` filtered by category: testability, test-coverage)
**Cross-reference:** Evaluator `scores.testability`
**Issue prefix:** `TESTS`

Focus on:
- Missing test coverage for new/changed code
- Test quality (edge cases, error paths)
- Testability of the implementation (dependency injection, mocking seams)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 4

### Section 4: Performance

**Primary source:** Monitor (`issues` filtered by category: performance)
**Cross-reference:** Evaluator `scores.performance` + Predictor `risk_assessment`
**Issue prefix:** `PERF`

Focus on:
- Performance regressions
- Algorithmic complexity concerns
- Resource usage (memory, CPU, I/O)
- Only flag issues where measurable impact is likely (per Review Preferences)

→ Follow **Review Section Protocol**

## Final Verdict

Based on combined agent outputs, determine one of:

**PROCEED:** All conditions met:
- `Monitor.verdict = 'approved'` AND `Monitor.valid = true`
- `Evaluator.recommendation = 'proceed'`

**REVISE:** Any condition true:
- `Monitor.verdict = 'needs_revision'`
- `Evaluator.recommendation = 'improve'`

**BLOCK:** Any condition true (highest priority):
- `Monitor.verdict = 'rejected'`
- `Evaluator.recommendation = 'reconsider'`
- `Evaluator.scores.security < 5`
- `Evaluator.scores.functionality < 5`
- `Predictor.risk_assessment = 'high'` AND `predicted_state.breaking_changes` is non-empty

**Priority:** BLOCK > REVISE > PROCEED

Present the verdict with a summary table:
- Monitor verdict + valid status
- Evaluator overall score + recommendation
- Predictor risk assessment
- Key issues resolved during interactive review
- Remaining action items

## Workflow Gate Unlock (REVISE/BLOCK only)

If the verdict is **REVISE** or **BLOCK** and the user asks to fix the issues,
the workflow gate may block edits because the workflow is in COMPLETE phase.

**Before applying any fixes**, run:

```bash
python3 .map/scripts/map_orchestrator.py reopen_for_fixes --feedback "Review findings: [summary of issues to fix]"
```

This transitions the workflow from COMPLETE → ACTOR so the edit gate unlocks.
Skip this step if the workflow is not in COMPLETE phase (e.g., review was run mid-workflow).

## Handoff Artifact Update

After the final verdict, update branch-scoped handoff artifacts so review output survives beyond the chat:

1. Write or append the most important review findings into the next `code-review-00N.md`
2. Persist final review gate + active unresolved set:

```bash
python3 .map/scripts/map_step_runner.py write_stage_gate \
  review \
  ready \
  code-review-001.md \
  "Final review passed"

python3 .map/scripts/map_step_runner.py ensure_active_issues_file
python3 .map/scripts/map_step_runner.py replace_active_issues \
  review \
  code-review-001.md \
  "- [remaining reviewer action items, or '(None)']"
```

Map verdicts to gate values:
- `PROCEED` -> `ready`
- `REVISE` -> `needs-revision`
- `BLOCK` -> `blocked`

2. Rebuild the PR handoff from current artifacts:

```bash
BUNDLE=$(python3 .map/scripts/map_step_runner.py build_handoff_bundle)
SUMMARY=$(echo "$BUNDLE" | jq -r '.summary')
VALIDATION=$(echo "$BUNDLE" | jq -r '.validation')
RISKS=$(echo "$BUNDLE" | jq -r '.risks_follow_up')
python3 .map/scripts/map_step_runner.py write_pr_draft "$SUMMARY" "$VALIDATION" "$RISKS"
```

This keeps `pr-draft.md` aligned with the latest review verdict and follow-up work.

`active-issues.json` is the current unresolved set. Historical issues remain in `plan-review-00N.md`, `code-review-00N.md`, `qa-001.md`, and run dossiers under `.map/<branch>/runs/`.

3. Write the deferred learning handoff so review lessons can be preserved later without hand-writing a summary:

```bash
python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-review \
  "$ARGUMENTS" \
  "<PROCEED|REVISE|BLOCK>" \
  "<next action based on the verdict>" \
  "<brief note about the most reusable review lesson>"
```

This writes `.map/<branch>/learning-handoff.md` and `.json`, updates `artifact_manifest.json`, and allows `/map-learn` to auto-load the review context later with no extra reconstruction.

## CI/Auto Mode Behavior

When `CI_MODE = true` (triggered by `--ci` or `--auto` in $ARGUMENTS):
- Skip all AskUserQuestion calls
- Auto-select recommended options for all issues
- Present all 4 sections as a batch report (no pauses between sections)
- Output structured verdict at the end
- Suitable for CI pipelines and automated review contexts

## Optional: Preserve Review Learnings

If the review revealed valuable patterns or common issues worth preserving:

```
/map-learn
```

## MCP Tools Used

- `mcp__sequential-thinking__sequentialthinking` — Complex analysis decisions during interactive presentation

---

**Begin review now.**


## Examples

```
/map-review <typical args>
```

## Troubleshooting

- **Issue:** Workflow doesn't behave as expected. **Fix:** Re-read the section above titled 'What this command CANNOT do' (if present) and ensure prerequisites are met. Run `/map-resume` to recover from interruptions.
