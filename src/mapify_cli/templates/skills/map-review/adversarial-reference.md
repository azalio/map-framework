# Adversarial Review Reference

Detailed workflow for `map-review --adversarial`. See [SKILL.md](SKILL.md) for context and integration points.

## Overview

Five reviewers run in parallel, each with only its permitted inputs:

| Reviewer | Context | Finds |
|----------|---------|-------|
| **Blind Hunter** | diff only | Typos, dead code, logic errors visible in isolation |
| **Edge Case Hunter** | diff + repo read access | Null handling, boundary conditions, error paths, codebase consistency |
| **Acceptance Auditor** | diff + spec + plan + artifacts | Missed requirements, spec violations, AC gaps, extra/unplanned work |
| **User (`user_experience`)** | diff + repo read access | Regressions in the already-shipped path: extra mandatory steps, confusable flags, an explicit value silently overridden |
| **Maintainer (`maintainer`)** | diff + repo read access | Branch-scoped litter in comments, implementation leaking into user-facing text, copy-paste, split sources of truth, version predicates by number, embedded foreign-language code |

With `--quick`: skip Edge Case Hunter (Blind + Acceptance + both roles).

The two role reviewers answer to the five-part output contract (`problem`,
`current_code`, `proposed_code`, `why_better`, `cost`). A finding that cannot
fill all five is dropped by `aggregate_adversarial_findings` into
`contract_incomplete` — reported, never counted.

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
USER_EXPERIENCE_DESC=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("user_experience",{}).get("description",""))')

MAINTAINER_PROMPT=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("maintainer",{}).get("prompt",""))')
MAINTAINER_DESC=$(printf '%s' "$ADV_PROMPTS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompts",{}).get("maintainer",{}).get("description",""))')
```

## Step B.adversarial.1: Launch all five in parallel (fan-out)

```text
# Launch all five reviewers in parallel — they are fully independent
# with no shared context. Wait for all to complete before aggregation.

Task(subagent_type="general-purpose", description=BLIND_DESC, prompt=BLIND_PROMPT)
# Save output as BLIND_OUTPUT
Task(subagent_type="general-purpose", description=EDGE_DESC, prompt=EDGE_PROMPT)
# Save output as EDGE_OUTPUT  (skip if --quick)
Task(subagent_type="general-purpose", description=ACCEPTANCE_DESC, prompt=ACCEPTANCE_PROMPT)
# Save output as ACCEPTANCE_OUTPUT
Task(subagent_type="general-purpose", description=USER_EXPERIENCE_DESC, prompt=USER_EXPERIENCE_PROMPT)
# Save output as USER_EXPERIENCE_OUTPUT
Task(subagent_type="general-purpose", description=MAINTAINER_DESC, prompt=MAINTAINER_PROMPT)
# Save output as MAINTAINER_OUTPUT
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
printf '%s' "$ACCEPTANCE_OUTPUT" > .map/$BRANCH/adversarial-acceptance.json
printf '%s' "$USER_EXPERIENCE_OUTPUT" > .map/$BRANCH/adversarial-user-experience.json
printf '%s' "$MAINTAINER_OUTPUT" > .map/$BRANCH/adversarial-maintainer.json

# The Edge Case Hunter did not run under --quick. Writing its file anyway
# would leave an EMPTY payload (or a stale one from an earlier full run)
# that the `-f` test below happily forwards; the aggregator then reports
# edge_case as parse_error, or folds in findings from another review.
# Remove it, then write it only when the pass actually ran.
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

## Step B.adversarial.4: Present unified adversarial report

Parse the aggregated JSON and present the report in this structure:

```
# Adversarial Review Report

## Summary
- Total findings: N (C CRITICAL, I IMPORTANT, M MINOR)
- Corroborated (found by 2+ reviewers): K — highest confidence
- Per-reviewer: Blind: B, Edge Case: E, Acceptance: A, User: U, Maintainer: M
- All-clear: [reviewers who reported all_clear=true]
- Dropped for an incomplete output contract: [contract_incomplete entries]

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

### All reviewers fail

Stop with CLARIFICATION_NEEDED. The diff may be too large or the context too complex for adversarial review.

### Edge Case Hunter runs out of context

Edge Case Hunter has repo read access. If the repo is very large, limit its scope by pre-computing an impact graph of files importing/imported-by the changes plus relevant tests. Defer full implementation to v2.