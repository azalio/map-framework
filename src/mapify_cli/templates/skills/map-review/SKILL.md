---
name: map-review
description: |
  Interactive 4-section code review using Monitor, Predictor, and Evaluator agents on current changes. Use when reviewing a diff, PR, or staged work before merge. Do NOT use to plan or implement; use map-plan or map-efficient.
disable-model-invocation: true
argument-hint: "[review focus] [--detached] [--ci] [--reverse-sections] [--shuffle-sections] [--seed <int>] [--compare-orderings]"
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
- `--reverse-sections` — Present the four review sections in reverse canonical order
  (Performance → Tests → Code Quality → Architecture). Useful for bias detection across sequential reviews.
- `--shuffle-sections` — Randomize the section presentation order using a branch+commit derived seed.
  The seed is recorded under the `ordering` key in `.map/<branch>/review-bundle.json` for reproducibility.
- `--seed <int>` — Override the shuffle seed with an explicit non-negative integer. Only meaningful when
  `--shuffle-sections` is also set. The integer is validated server-side; non-integer values are rejected.
- `--compare-orderings` — Run the full review twice (default order, then reverse order) and aggregate
  results via `compare_review_runs`. Records drift metrics in the ordering artifact. Cannot be combined
  with `--shuffle-sections` (EC-1/EC-17: conflicting ordering strategies; use one or the other).

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
   - List options neutrally as A/B/C/... Append `(Recommended)` AFTER the recommended
     option's label — NOT as a positional preference. Example: "Option B (Recommended)".
3. **AskUserQuestion** with numbered issues and lettered options for each
   - Example: "ARCH-1: Option A / Option B (Recommended) / Option C"
   - **Skip AskUserQuestion in CI mode** — scan options for the line whose text contains
     the `(Recommended)` substring and auto-select that option (INV-11). If multiple options
     carry the marker, pick the first match. If no option carries the marker, default to PROCEED.
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

**Parse $ARGUMENTS for `--reverse-sections`:**
```bash
REVERSE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--reverse-sections'; then
  REVERSE_FLAG=true
fi
```

**Parse $ARGUMENTS for `--shuffle-sections`:**
```bash
SHUFFLE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--shuffle-sections'; then
  SHUFFLE_FLAG=true
fi
```

**Parse $ARGUMENTS for `--seed <int>` (EC-16: never $(...)-expand user-supplied token):**
```bash
SEED_RAW=""
if echo "$ARGUMENTS" | grep -qE -- '--seed[ =][0-9]+'; then
  SEED_RAW=$(echo "$ARGUMENTS" | sed -nE 's/.*--seed[ =]([0-9]+).*/\1/p')
fi
```

**Parse $ARGUMENTS for `--compare-orderings`:**
```bash
COMPARE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--compare-orderings'; then
  COMPARE_FLAG=true
fi
```

**EC-1/EC-17 mutual exclusion: --compare-orderings and --shuffle-sections cannot be combined:**
```bash
if [ "$COMPARE_FLAG" = "true" ] && [ "$SHUFFLE_FLAG" = "true" ]; then
  echo '{"status":"error","reason":"--compare-orderings always uses default+reverse; cannot combine with --shuffle-sections (EC-1/EC-17)"}'
  exit 1
fi
```

**Determine MODE_FLAG for section-order helper:**
MODE_FLAG values MUST match `REVIEW_VALID_MODES` in `map_step_runner.py`:
`default` / `reverse-sections` / `shuffle-sections`. `--compare-orderings` is NOT
a helper mode — it is handled separately at Step A.1d and internally launches
default + reverse runs.
```bash
MODE_FLAG="default"
if [ "$REVERSE_FLAG" = "true" ]; then
  MODE_FLAG="reverse-sections"
elif [ "$SHUFFLE_FLAG" = "true" ]; then
  MODE_FLAG="shuffle-sections"
fi
# COMPARE_FLAG does not set MODE_FLAG; compare flow drives its own two runs.
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
# EC-15: prepare_detached_review is called ONCE here. When --compare-orderings is also
# set, both compare runs reuse the same DETACHED_PATH (detached is a bundle-collection
# concern, not a per-run concern).
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

### Step A.1d: Prepare compare-mode ordering (optional, `--compare-orderings` only)

If `COMPARE_FLAG=true`, perform two full agent runs and aggregate before Phase B.

**This step replaces the single-run Phase A.2 + Phase B sequence when compare-mode is active.**

**Run 1 — default order:**

Call the ordering helper for default order:
```bash
SECTIONS_DEFAULT=$(python3 .map/scripts/map_step_runner.py shuffle-sections "default" "")
```

Launch all 3 agents (same prompts as Step A.2) in a single message. Capture the full agent
result set as `RUN_DEFAULT` dict with keys:
- `verdict`: `'PROCEED'|'REVISE'|'BLOCK'` (derived per Final Verdict rules)
- `primary_issues`: array of top issue IDs surfaced
- `ordering_label`: `'default'`

**Run 2 — reverse order:**

Call the ordering helper for reverse order:
```bash
SECTIONS_REVERSE=$(python3 .map/scripts/map_step_runner.py shuffle-sections "reverse-sections" "")
```

Launch all 3 agents again in a single message (same prompts, reverse section sequence).
Capture result set as `RUN_REVERSE` dict with keys:
- `verdict`: `'PROCEED'|'REVISE'|'BLOCK'`
- `primary_issues`: array of top issue IDs surfaced
- `ordering_label`: `'reverse'`

**Step A.1d.3 — Aggregate runs:**

`compare-review-runs` expects a JSON array of run *objects* (not strings), each with
`verdict` / `primary_issues` / `ordering_label` keys. Build the array by parsing each
captured run text back to a dict.

```bash
RUNS_JSON=$(python3 -c "import json,sys; \
  print(json.dumps([json.loads(sys.argv[1]), json.loads(sys.argv[2])]))" \
  "$RUN_DEFAULT" "$RUN_REVERSE")
DRIFT_RESULT=$(python3 .map/scripts/map_step_runner.py compare-review-runs "$RUNS_JSON")
```

Parse the aggregated result:
```bash
DRIFT_DETECTED=$(echo "$DRIFT_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['drift_detected'])")
FINAL_VERDICT=$(echo "$DRIFT_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['final_verdict'])")
DRIFT_SUMMARY=$(echo "$DRIFT_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('drift_summary') or '')")
```

**Step A.1d.4 — Stage ordering payload:**

`record-review-ordering` expects a wrapper object with two keys: `runs` (the run list)
and `drift` (the `compare-review-runs` output). Build that wrapper:

```bash
RUNS_AND_DRIFT_JSON=$(python3 -c "import json,sys; \
  print(json.dumps({'runs':[json.loads(sys.argv[1]), json.loads(sys.argv[2])], \
                    'drift':json.loads(sys.argv[3])}))" \
  "$RUN_DEFAULT" "$RUN_REVERSE" "$DRIFT_RESULT")
python3 .map/scripts/map_step_runner.py record-review-ordering compare-orderings "" "$RUNS_AND_DRIFT_JSON"
```

**Step A.1d.5 — Announce drift and proceed to bundle:**

Announce to the user:
- Whether drift was detected (`DRIFT_DETECTED`)
- The final aggregated verdict (`FINAL_VERDICT`)
- The drift summary if drift was detected (`DRIFT_SUMMARY`)

Then call `create_review_bundle` (existing flow at Step A.1b) — it will consume the staged
ordering payload. Skip the second Phase A.2 parallel launch (agents already ran above).
Proceed directly to Phase B using `FINAL_VERDICT` as the authoritative verdict.

**EC-11 partial failure:** If one of the two runs fails mid-flight, record the successful
run's verdict as provisional, set `compare_status='partial_failure'` in the ordering artifact,
and announce that drift could not be confirmed. The review still proceeds with the provisional
verdict.

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

### Step B.0: Determine section presentation order

Before presenting any section, call the ordering helper to get the section sequence.
For default (no ordering flag), the helper returns canonical order. For `--reverse-sections`,
`--shuffle-sections`, or compare-mode runs, the helper returns the chosen order.

```bash
SECTIONS_JSON=$(python3 .map/scripts/map_step_runner.py shuffle-sections "$MODE_FLAG" "$SEED_RAW")
```

The result is a JSON array of section IDs, e.g. `["architecture","code_quality","tests","performance"]`
(underscore, NOT hyphen — matches `REVIEW_SECTION_IDS` in `map_step_runner.py`).
**Iterate over this returned list** — do not hard-code a presentation sequence.
The four section blocks below describe each section's content; they are not a fixed presentation order.

Present findings section by section in the order returned above. Each section follows the
**Review Section Protocol** defined above.

### Section: Architecture

**Primary source:** Predictor (`breaking_changes`, `affected_components`, `risk_assessment`)
**Cross-reference:** Evaluator `scores.completeness`
**Issue prefix:** `ARCH`

Focus on:
- Breaking changes and their mitigations
- Affected component blast radius
- Architectural fit of the changes
- Completeness of the change set (are all affected areas updated?)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to the next section

### Section: Code Quality

**Primary source:** Monitor (`issues` filtered by category: correctness, code-quality, maintainability)
**Cross-reference:** Evaluator `scores.code_quality`
**Issue prefix:** `QUALITY`

Focus on:
- Correctness issues (logic errors, edge cases)
- Code quality issues (naming, structure, DRY violations)
- Maintainability concerns
- Standards compliance

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to the next section

### Section: Tests

**Primary source:** Monitor (`issues` filtered by category: testability, test-coverage)
**Cross-reference:** Evaluator `scores.testability`
**Issue prefix:** `TESTS`

Focus on:
- Missing test coverage for new/changed code
- Test quality (edge cases, error paths)
- Testability of the implementation (dependency injection, mocking seams)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to the next section

### Section: Performance

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

4. Write the run health report using the final review verdict's terminal status:

```bash
# PROCEED -> complete; REVISE -> pending; BLOCK -> blocked.
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set RUN_HEALTH_STATUS from the review verdict}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-review \
  "$RUN_HEALTH_STATUS"
```

This writes `.map/<branch>/run_health_report.json`, updates the `run_health` stage in `artifact_manifest.json`, and keeps review closeout evidence machine-readable for CI, `/map-resume`, and follow-up reviewers.

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
