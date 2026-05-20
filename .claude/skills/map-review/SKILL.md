---
name: map-review
description: |
  Interactive 4-section code review using Monitor, Predictor, and Evaluator agents on current changes. Use when reviewing a diff, PR, or staged work before merge. Do NOT use to plan or implement; use map-plan or map-efficient.
effort: high
disable-model-invocation: true
argument-hint: "[review focus] [--detached] [--ci] [--reverse-sections] [--shuffle-sections] [--seed <int>] [--compare-orderings]"
---
# MAP Review Workflow

Interactive, structured code review of current changes using Monitor, Predictor, and Evaluator agents.

Task: `$ARGUMENTS`

Use [review-reference.md](review-reference.md) for detailed examples, section rubrics, and troubleshooting. When a workflow step points to a reference section, read that section before executing the step; supporting files are not assumed to be in context automatically. Reviewer prompt construction must follow the shared [XML Prompt Envelope](../../references/map-xml-prompt-envelopes.md): persisted artifacts appear in `<documents>` before instructions and `<expected_output>`.

## Effort and Parallelism Policy

```yaml
thinking_policy: high/adaptive
parallel_tool_policy: single_review_fanout
```

- Use deeper reasoning for verdicts, risk ranking, section tradeoffs, and contradictory reviewer evidence.
- Use exactly one parallel reviewer fan-out after bundle preparation: Monitor, Predictor, and Evaluator may run together because they inspect the same review input independently.
- Wait for all reviewer agents before section presentation. Do not parallelize interactive decisions, ordering comparisons that share state, or review-bundle writes.

## Flags

- `--ci` / `--auto`: non-interactive mode; auto-select the line whose text contains the `(Recommended)` marker substring.
- `--detached`: prepare `.map/<branch>/detached-review/` so reviewer agents can read an isolated worktree. The source branch is never mutated. If detached prep is unavailable, review still proceeds from the in-place bundle as graceful degradation.
- `--reverse-sections`: present review sections in reverse canonical order.
- `--shuffle-sections`: randomize section order with a branch+commit derived seed.
- `--seed <int>`: override shuffle seed with a non-negative integer.
- `--compare-orderings`: run default and reverse ordering reviews, then aggregate drift. Cannot be combined with `--shuffle-sections` (EC-1/EC-17).

## Execution Rules

1. Execute all phases in order.
2. Build the review bundle before launching reviewer agents.
3. Build bounded review prompts before launching reviewer agents.
4. Launch all three reviewer agents exactly once per review run: monitor, predictor, evaluator.
5. Monitor `valid=false` is a hard stop; do not proceed to section presentation.
6. Present options neutrally as A/B/C. Append `(Recommended)` after the option label, not by position.

## Review Preferences (Customize per project)

- DRY: flag duplication when it affects maintainability.
- Testing: missing tests for changed behavior is high severity.
- Engineering level: reject both under-engineering and over-engineering.
- Edge cases: prefer explicit handling for public APIs and persistence boundaries.
- Clarity: explicit over clever.
- Performance: flag only when measurable impact is plausible.

## Expected Agent Output Schemas (Contract Reference)

Use [Evidence-First Output Examples](../../references/map-output-examples.md). Evidence first: reviewers populate quote/evidence arrays before verdict, risk, or score fields.

Monitor:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before verdict fields.
- `valid`: boolean.
- `verdict`: `approved` | `needs_revision` | `rejected`.
- `issues[]`: severity, category, description, file_path, line_range, suggestion.

Predictor:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before risk_assessment.
- `risk_assessment`: `low` | `medium` | `high` | `critical`.
- `predicted_state.affected_components[]`, `breaking_changes[]`, `required_updates[]`.

Evaluator:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before scores.
- `scores.functionality`, `code_quality`, `performance`, `security`, `testability`, `completeness`.
- `overall_score` and `recommendation`.

## Review Section Protocol

For each section, present up to four issues with file/line evidence, show 2-3 A/B/C options neutrally, append `(Recommended)` after the recommended option label, ask the user unless CI mode is active, and summarize before the next section.

CI mode scans for the `(Recommended)` marker; it does not pick by first position.

## Step 0: Detect CI Mode and Flags

```bash
CI_MODE=false
if echo "$ARGUMENTS" | grep -qE -- '--(ci|auto)'; then
  CI_MODE=true
fi

DETACHED_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--detached'; then
  DETACHED_FLAG=true
  ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--detached//g' | xargs)
fi

REVERSE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--reverse-sections'; then
  REVERSE_FLAG=true
fi

SHUFFLE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--shuffle-sections'; then
  SHUFFLE_FLAG=true
fi

SEED_RAW=""
if echo "$ARGUMENTS" | grep -qE -- '--seed[ =][0-9]+'; then
  SEED_RAW=$(echo "$ARGUMENTS" | sed -nE 's/.*--seed[ =]([0-9]+).*/\1/p')
fi

COMPARE_FLAG=false
if echo "$ARGUMENTS" | grep -q -- '--compare-orderings'; then
  COMPARE_FLAG=true
fi

if [ "$COMPARE_FLAG" = "true" ] && [ "$SHUFFLE_FLAG" = "true" ]; then
  echo '{"status":"error","reason":"--compare-orderings always uses default+reverse; cannot combine with --shuffle-sections (EC-1/EC-17)"}'
  exit 1
fi

MODE_FLAG="default"
if [ "$REVERSE_FLAG" = "true" ]; then
  MODE_FLAG="reverse-sections"
elif [ "$SHUFFLE_FLAG" = "true" ]; then
  MODE_FLAG="shuffle-sections"
fi
```

## Phase A: Collection (Parallel)

### Step A.1: Gather changes

```bash
git diff HEAD
git status
```

### Step A.1b: Load canonical review context (bundle + handoff)

Run this before any reviewer agent:

```bash
BUNDLE_JSON=$(python3 .map/scripts/map_step_runner.py create_review_bundle)
BUNDLE_JSON_PATH=$(echo "$BUNDLE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['bundle_path_json'])")
```

This creates `.map/<branch>/review-bundle.json` and `.map/<branch>/review-bundle.md`. These are PRIMARY review context. The bundle includes prior-stage consumption status; missing inputs are review evidence, not invisible setup noise.

### Step A.1c: Prepare detached review context (optional, `--detached` only)

```bash
DETACHED_PATH=""
if [ "$DETACHED_FLAG" = "true" ]; then
  # EC-15: prepare detached review once; compare runs reuse the same path.
  DETACHED_JSON=$(python3 .map/scripts/map_step_runner.py prepare_detached_review "$BUNDLE_JSON_PATH")
  DETACHED_STATUS=$(echo "$DETACHED_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))")
  DETACHED_PATH=$(echo "$DETACHED_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worktree_path') or '')")
  DETACHED_REASON=$(echo "$DETACHED_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reason') or '')")
fi
```

If `DETACHED_STATUS` is `success`, tell reviewer agents to read source files from `$DETACHED_PATH` read-only. If status is `unavailable` or `error`, announce `$DETACHED_REASON` and continue in place. Do not mutate the source branch.

### Step A.1d: Prepare compare-mode ordering (optional, `--compare-orderings` only)

When compare mode is active, run two review collections with `ordering_label='default'` and `ordering_label='reverse'`, then call `compare-review-runs` and `record-review-ordering` to stage the drift summary. See [review-reference.md](review-reference.md#compare-orderings) for the detailed loop.

### Step A.2: Launch all parallel calls

Before launching agents, build bounded reviewer prompts. `build_review_prompts` uses `MAP_REVIEW_PROMPT_BUDGET_TOKENS`, emits a Review Prompt Budget note, and clips lower-priority raw diff before review-bundle context.

```bash
REVIEW_PROMPTS_JSON=$(python3 .map/scripts/map_step_runner.py build_review_prompts \
  --review-preferences "[paste Review Preferences section above]")

MONITOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["monitor"]["prompt"])')
PREDICTOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["predictor"]["prompt"])')
EVALUATOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["evaluator"]["prompt"])')
```

Use the extracted prompt variables as the Task prompts. Keep reviewer task calls below the bundle and prompt-builder commands.

```text
Task(subagent_type="monitor", description="Review diff for correctness", prompt=MONITOR_PROMPT)
Task(subagent_type="predictor", description="Predict integration risk", prompt=PREDICTOR_PROMPT)
Task(subagent_type="evaluator", description="Score review quality", prompt=EVALUATOR_PROMPT)
```

Reviewer prompts reference `review-bundle.json`, `review-bundle.md`, the raw diff as secondary context, and the expected output schema.

### Hard Stop Check

If Monitor returns `valid=false`, report findings immediately and skip Phase B. Record `REVISE` or `BLOCK` as appropriate.

## Phase B: Interactive Presentation (4 Sections)

### Step B.0: Determine section presentation order

```bash
SECTIONS_JSON=$(python3 .map/scripts/map_step_runner.py shuffle-sections "$MODE_FLAG" "$SEED_RAW")
```

Iterate over the helper-returned order and summarize before the next section.

### Section: Architecture

Focus on design boundaries, hidden coupling, state lifecycle, hard/soft constraints, and reviewability.

### Section: Code Quality

Focus on clarity, duplication, error handling, maintainability, and fit with existing patterns.

### Section: Tests

Focus on changed behavior, failure modes, fixtures, and whether tests prove the contract rather than the implementation.

### Section: Performance

Focus only on plausible measurable impact, hot paths, accidental N+1 behavior, large artifacts, or prompt/context blowups.

## Final Verdict

Choose exactly one:

- `PROCEED`: no blocking findings remain.
- `REVISE`: actionable changes are required before review can pass.
- `BLOCK`: external, safety, or correctness blocker prevents review completion.

## Workflow Gate Unlock (REVISE/BLOCK only)

If edits are needed, write the stage gate so the owning workflow can continue:

```bash
python3 .map/scripts/map_step_runner.py write_stage_gate review "$FINAL_VERDICT" "$REVIEW_SUMMARY"
```

## Handoff Artifact Update

Update durable review artifacts before closeout:

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

BUNDLE=$(python3 .map/scripts/map_step_runner.py build_handoff_bundle)
SUMMARY=$(echo "$BUNDLE" | jq -r '.summary')
VALIDATION=$(echo "$BUNDLE" | jq -r '.validation')
RISKS=$(echo "$BUNDLE" | jq -r '.risks_follow_up')
python3 .map/scripts/map_step_runner.py write_pr_draft "$SUMMARY" "$VALIDATION" "$RISKS"

python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-review \
  "$ARGUMENTS" \
  "<PROCEED|REVISE|BLOCK>" \
  "<next action based on the verdict>" \
  "<brief note about the most reusable review lesson>"
```

This preserves `active-issues`, `pr-draft`, and `learning-handoff` flows.

Set `RUN_HEALTH_STATUS` from verdict:

- `PROCEED -> complete`
- `REVISE -> pending`
- `BLOCK -> blocked`

```bash
RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?set from final review verdict}"
python3 .map/scripts/map_step_runner.py write_run_health_report \
  map-review \
  "$RUN_HEALTH_STATUS"
```

This writes `.map/<branch>/run_health_report.json` and updates the `run_health` manifest stage.

## CI/Auto Mode Behavior

CI mode auto-selects options marked `(Recommended)`, records the selected path, writes the same artifacts, and exits non-zero for `REVISE` or `BLOCK` when the caller expects gate semantics.

## Optional: Preserve Review Learnings

After review closes, run `/map-learn` if this review produced reusable rules, gotchas, or repeated issues.

## MCP Tools Used

No MCP tool is required. Prefer repo-local artifacts and git state.

## Examples

See [review-reference.md](review-reference.md#examples) for normal, CI, detached, shuffle, and compare-ordering examples.

## Troubleshooting

See [review-reference.md](review-reference.md#troubleshooting) for unavailable detached worktrees, missing review bundles, review prompt clipping, and ordering drift.
