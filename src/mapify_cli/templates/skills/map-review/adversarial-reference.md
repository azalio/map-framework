# Adversarial Review Reference

Detailed workflow for `map-review --adversarial`. See [SKILL.md](SKILL.md) for context and integration points.

## Overview

Three reviewers run in parallel, each with only its permitted inputs:

| Reviewer | Context | Finds |
|----------|---------|-------|
| **Blind Hunter** | diff only | Typos, dead code, logic errors visible in isolation |
| **Edge Case Hunter** | diff + repo read access | Null handling, boundary conditions, error paths, codebase consistency |
| **Acceptance Auditor** | diff + spec + plan + artifacts | Missed requirements, spec violations, AC gaps, extra/unplanned work |

With `--quick`: skip Edge Case Hunter (Blind + Acceptance only).

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
```

## Step B.adversarial.1: Launch all three in parallel (fan-out)

```text
# Launch all three adversarial reviewers in parallel — they are fully independent
# with no shared context. Wait for all to complete before aggregation.

Task(subagent_type="general", description=BLIND_DESC, prompt=BLIND_PROMPT)
# Save output as BLIND_OUTPUT
Task(subagent_type="general", description=EDGE_DESC, prompt=EDGE_PROMPT)
# Save output as EDGE_OUTPUT  (skip if --quick)
Task(subagent_type="general", description=ACCEPTANCE_DESC, prompt=ACCEPTANCE_PROMPT)
# Save output as ACCEPTANCE_OUTPUT
```

## Step B.adversarial.2: Validate reviewer outputs

Each reviewer must return valid JSON matching the adversarial finding schema. If any reviewer output is truncated or invalid JSON:
- Log the failure
- Re-invoke that specific reviewer ONCE with the same prompt
- If still invalid, record the reviewer as `parse_error` and continue with remaining reviewers

## Step B.adversarial.3: Aggregate findings

Write each reviewer's raw JSON output to a temp file, then aggregate:

```bash
printf '%s' "$BLIND_OUTPUT" > .map/$BRANCH/adversarial-blind.json
printf '%s' "$EDGE_OUTPUT" > .map/$BRANCH/adversarial-edge.json
printf '%s' "$ACCEPTANCE_OUTPUT" > .map/$BRANCH/adversarial-acceptance.json

BLIND_ARG=""
EDGE_ARG=""
ACCEPTANCE_ARG=""
if [ -f .map/$BRANCH/adversarial-blind.json ]; then
  BLIND_ARG="--blind .map/$BRANCH/adversarial-blind.json"
fi
if [ -f .map/$BRANCH/adversarial-edge.json ]; then
  EDGE_ARG="--edge-case .map/$BRANCH/adversarial-edge.json"
fi
if [ -f .map/$BRANCH/adversarial-acceptance.json ]; then
  ACCEPTANCE_ARG="--acceptance .map/$BRANCH/adversarial-acceptance.json"
fi

ADV_AGGREGATED=$(python3 .map/scripts/map_step_runner.py aggregate_adversarial_findings \
  $BLIND_ARG $EDGE_ARG $ACCEPTANCE_ARG)
```

## Step B.adversarial.4: Present unified adversarial report

Parse the aggregated JSON and present the report in this structure:

```
# Adversarial Review Report

## Summary
- Total findings: N (C CRITICAL, I IMPORTANT, M MINOR)
- Corroborated (found by 2+ reviewers): K — highest confidence
- Per-reviewer: Blind: B, Edge Case: E, Acceptance: A
- All-clear: [reviewers who reported all_clear=true]

## CRITICAL
[per finding: severity, category, file:line, failure_mode, evidence, reported_by, corroborated flag]

## IMPORTANT
[per finding: same structure]

## MINOR
[per finding: same structure]

## Cross-Reviewer Convergence
[Highlight what multiple reviewers independently found — these are highest-confidence issues]

## Reviewer All-Clear Statements
[Per reviewer who said all_clear: what they checked and why it's clean]
```

When `--show-raw-findings` is set, also show the raw per-reviewer JSON files.

## Step B.adversarial.5: Determine verdict

Based on aggregated findings:
- **BLOCK**: any CRITICAL finding with corroboration OR > 2 CRITICAL from any single reviewer
- **REVISE**: any CRITICAL (uncorroborated) OR any IMPORTANT
- **PROCEED**: only MINOR findings OR all all_clear

## Step B.adversarial.6: Skip to Final Verdict

After presenting the adversarial report, skip the normal 4-section interactive walkthrough and go directly to Final Verdict → Handoff Artifacts.

## Flow summary for adversarial

When `ADVERSARIAL_FLAG=true`, the workflow is:
Phase A (all steps) → Phase B: Adversarial Review → Final Verdict → Handoff Artifacts.
Do NOT run the normal Monitor/Predictor/Evaluator fan-out or the 4-section walkthrough.

## Examples

See [review-reference.md](review-reference.md#examples) for adversarial examples.

## Troubleshooting

### Reviewer returns invalid JSON

Re-invoke that specific reviewer ONCE. If still invalid, record `parse_error` and continue — two valid reviewers are better than zero.

### All three reviewers fail

Stop with CLARIFICATION_NEEDED. The diff may be too large or the context too complex for adversarial review.

### Edge Case Hunter runs out of context

Edge Case Hunter has repo read access. If the repo is very large, limit its scope by pre-computing an impact graph of files importing/imported-by the changes plus relevant tests. Defer full implementation to v2.