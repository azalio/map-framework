# Adversarial Review Reference

Detailed workflow for `$map-review --adversarial`. See [SKILL.md](SKILL.md)
for context and integration points. It preserves the five-reviewer contract
using Codex configured subagents and concurrent dispatch where the passes are
independent.

## Dispatch design

Codex dispatch targets configured roles rather than inventing ad-hoc agent
names. Use `monitor` for Blind and Edge Case, `evaluator` for Acceptance,
`predictor` for User Experience, and `documentation-reviewer` for Maintainer.
Each prompt supplies the narrower reviewer persona and permitted inputs. Spawn
the independent passes in one batch when concurrency is available; otherwise
dispatch them sequentially without merging their contexts.

## Overview

Five reviewer passes, each with only its permitted inputs:

| Pass | Context | Finds |
|------|---------|-------|
| **Blind Hunter** | diff only | Typos, dead code, logic errors visible in isolation |
| **Edge Case Hunter** | diff + repo read access | Null handling, boundary conditions, error paths, codebase consistency |
| **Acceptance Auditor** | diff + spec + plan + artifacts | Missed requirements, spec violations, AC gaps, extra/unplanned work |
| **User (`user_experience`)** | diff + repo read access | Regressions in the already-shipped path: extra mandatory steps, confusable flags, an explicit value silently overridden |
| **Maintainer (`maintainer`)** | diff + repo read access | Branch-scoped litter in comments, implementation leaking into user-facing text, undiagnosable errors, copy-paste, split sources of truth, version predicates by number, embedded foreign-language code, settings carried through layers that only pass them on, names that promise more than the body does, mechanisms named after their first application, files placed against the local convention |

With `--quick`: skip the Edge Case Hunter pass (Blind + Acceptance + both
role passes).

The two role passes answer to the five-part output contract (`problem`,
`current_code`, `proposed_code`, `why_better`, `cost`); a finding that
cannot fill all five is dropped into `contract_incomplete` by the
aggregator — reported, never counted. See
[review-reference.md](review-reference.md#role-reviewers) for what each role
checks.

Keep every prompt scoped to its permitted inputs (for example, do not supply
the spec to Blind Hunter), and collect each result independently before
aggregation.

## Step B.adversarial.0: Build adversarial review prompts

```bash
QUICK_ARG=""
if [ "$QUICK_FLAG" = "true" ]; then
  QUICK_ARG="--quick"
fi

ADV_PROMPTS_JSON=$(python3 .map/scripts/map_step_runner.py build_adversarial_review_prompts $QUICK_ARG)

BLIND_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("blind",{}).get("prompt",""))')
BLIND_DESC=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("blind",{}).get("description",""))')

EDGE_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("edge_case",{}).get("prompt",""))')
EDGE_DESC=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("edge_case",{}).get("description",""))')

ACCEPTANCE_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("acceptance",{}).get("prompt",""))')
ACCEPTANCE_DESC=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("acceptance",{}).get("description",""))')

USER_EXPERIENCE_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("user_experience",{}).get("prompt",""))')
MAINTAINER_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("maintainer",{}).get("prompt",""))')
```

`build_adversarial_review_prompts` is the exact same CLI verb the Claude
port calls — payload flows out via stdout JSON only, never via argv, per
the stdin-safe piping convention used throughout this skill.

## Step B.adversarial.1: Dispatch all five passes

```text
Dispatch these independent calls together when slots permit; every call must
include a unique `task_name`, its generated prompt as `message`, and a reminder
that the reviewer is read-only and must return only the required JSON:

Blind Hunter:       spawn_agent(agent_type="monitor", task_name="review_blind", message=BLIND_PROMPT)
Edge Case Hunter:   spawn_agent(agent_type="monitor", task_name="review_edge", message=EDGE_PROMPT) (skip under --quick)
Acceptance Auditor: spawn_agent(agent_type="evaluator", task_name="review_acceptance", message=ACCEPTANCE_PROMPT)
User Experience:   spawn_agent(agent_type="predictor", task_name="review_user_experience", message=USER_EXPERIENCE_PROMPT)
Maintainer:         spawn_agent(agent_type="documentation-reviewer", task_name="review_maintainer", message=MAINTAINER_PROMPT)

Wait for all dispatched reviewers and map their final JSON to `BLIND_OUTPUT`,
`EDGE_OUTPUT`, `ACCEPTANCE_OUTPUT`, `USER_EXPERIENCE_OUTPUT`, and
`MAINTAINER_OUTPUT`. If concurrency is unavailable, make the same calls
sequentially; do not replace independent review with parent-session personas.
```

## Step B.adversarial.2: Validate reviewer outputs

Each pass must produce valid JSON matching the adversarial finding schema.
Validate the same way Phase A validates monitor/predictor/evaluator output
— pipe the raw response via stdin, never pass it as an argv positional:

```bash
printf '%s' "$BLIND_OUTPUT" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent review-monitor
```

If a pass's output is truncated or invalid JSON:
- Log the failure
- Re-run that specific pass ONCE with the same prompt
- If still invalid, record the pass as `parse_error` and continue with the
  remaining passes

## Step B.adversarial.3: Aggregate findings

Write each pass's raw JSON output to a temp file, then aggregate:

```bash
printf '%s' "$BLIND_OUTPUT" > .map/$BRANCH/adversarial-blind.json
printf '%s' "$ACCEPTANCE_OUTPUT" > .map/$BRANCH/adversarial-acceptance.json
printf '%s' "$USER_EXPERIENCE_OUTPUT" > .map/$BRANCH/adversarial-user-experience.json
printf '%s' "$MAINTAINER_OUTPUT" > .map/$BRANCH/adversarial-maintainer.json

# The Edge Case Hunter pass did not run under --quick. Writing its file
# anyway would leave an EMPTY payload (or a stale one from an earlier full
# run) that the `-f` test below happily forwards; the aggregator then
# reports edge_case as parse_error, or folds in findings from another
# review. Remove it, then write it only when the pass actually ran.
rm -f .map/$BRANCH/adversarial-edge.json
if [ "$QUICK_FLAG" != "true" ]; then
  printf '%s' "$EDGE_OUTPUT" > .map/$BRANCH/adversarial-edge.json
fi

ADV_ARGS=""
if [ -f .map/$BRANCH/adversarial-blind.json ]; then
  ADV_ARGS="$ADV_ARGS --blind .map/$BRANCH/adversarial-blind.json"
fi
if [ -f .map/$BRANCH/adversarial-edge.json ]; then
  ADV_ARGS="$ADV_ARGS --edge-case .map/$BRANCH/adversarial-edge.json"
fi
if [ -f .map/$BRANCH/adversarial-acceptance.json ]; then
  ADV_ARGS="$ADV_ARGS --acceptance .map/$BRANCH/adversarial-acceptance.json"
fi
if [ -f .map/$BRANCH/adversarial-user-experience.json ]; then
  ADV_ARGS="$ADV_ARGS --user-experience .map/$BRANCH/adversarial-user-experience.json"
fi
if [ -f .map/$BRANCH/adversarial-maintainer.json ]; then
  ADV_ARGS="$ADV_ARGS --maintainer .map/$BRANCH/adversarial-maintainer.json"
fi

ADV_AGGREGATED=$(python3 .map/scripts/map_step_runner.py aggregate_adversarial_findings \
  $ADV_ARGS)
```

`aggregate_adversarial_findings` is the exact same CLI verb the Claude port
calls, taking file paths (not raw payload on argv) — the raw finding JSON
itself never travels on the command line.

## Step B.adversarial.4: Present unified adversarial report

Parse the aggregated JSON and present the report in this structure:

```
# Adversarial Review Report

## Summary
- Total findings: N (C CRITICAL, I IMPORTANT, M MINOR)
- Corroborated (found by 2+ passes): K — highest confidence
- Per-pass: Blind: B, Edge Case: E, Acceptance: A, User: U, Maintainer: M
- All-clear: [passes that reported all_clear=true]
- Dropped for an incomplete output contract: [contract_incomplete entries]

## CRITICAL
[per finding: severity, category, file:line, failure_mode, evidence, reported_by, corroborated flag]

## IMPORTANT
[per finding: same structure]

## MINOR
[per finding: same structure]

## Cross-Reviewer Convergence
[Highlight what multiple passes independently found — these are highest-confidence issues]

## Reviewer All-Clear Statements
[Per pass that said all_clear: what it checked and why it's clean]
```

When `--show-raw-findings` is set, also show the raw per-pass JSON files.

## Step B.adversarial.5: Determine verdict

Based on aggregated findings:
- **BLOCK**: any CRITICAL finding with corroboration OR > 2 CRITICAL from any single pass
- **REVISE**: any CRITICAL (uncorroborated) OR any IMPORTANT
- **PROCEED**: only MINOR findings OR all all_clear

## Step B.adversarial.6: Skip to Final Verdict

After presenting the adversarial report, skip the normal 4-section
interactive walkthrough and go directly to Final Verdict → Handoff
Artifacts.

## Flow summary for adversarial

When `ADVERSARIAL_FLAG=true`, the workflow is:
Phase A (all steps) → Phase B: Adversarial Review (5 sequential in-session
passes, 4 with `--quick`) → Final Verdict → Handoff Artifacts. Do NOT run the normal
Monitor/Predictor/Evaluator fan-out or the 4-section walkthrough.

## Examples

See [review-reference.md](review-reference.md#examples) for adversarial examples.

## Troubleshooting

### A pass returns invalid JSON

Re-run that specific pass ONCE. If still invalid, record `parse_error` and
continue — two valid passes are better than zero.

### All passes fail

Stop with CLARIFICATION_NEEDED. The diff may be too large or the context
too complex for adversarial review.

### Edge Case Hunter pass runs out of context

The Edge Case Hunter pass has repo read access. If the repo is very large,
limit its scope by pre-computing an impact graph of files
importing/imported-by the changes plus relevant tests. Defer full
implementation to v2.
