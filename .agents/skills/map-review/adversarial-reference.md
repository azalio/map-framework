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
| **Maintainer (`maintainer`)** | diff + repo read access | Branch-scoped litter in comments, implementation leaking into user-facing text, undiagnosable errors, copy-paste, split sources of truth, version predicates by number, embedded foreign-language code, settings carried through layers that only pass them on, names that promise more than the body does, mechanisms named after their first application, files placed against the local convention |

With `--quick`: skip Edge Case Hunter (Blind + Acceptance + both roles).

The two role reviewers answer to the five-part output contract (`problem`,
`current_code`, `proposed_code`, `why_better`, `cost`). A finding that cannot
fill all five is dropped by `aggregate_adversarial_findings` into
`contract_incomplete` — reported, never counted.

## Step B.adversarial.0: Build adversarial review prompts

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
BRANCH_DIR=".map/$BRANCH"
QUICK_ARG=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("--quick" if "edge_case" not in d["scheduled_reviewers"] else "")' "$BRANCH_DIR/review-mode.json") || exit 1

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
# Dispatch all five reviewers together — they are fully independent.
# <n> increments on every dispatch in the run.

spawn_agent(agent_type="monitor", task_name="map_review_blind_<n>", message=BLIND_PROMPT)
spawn_agent(agent_type="monitor", task_name="map_review_edge_case_<n>", message=EDGE_PROMPT)  # skip if --quick
spawn_agent(agent_type="evaluator", task_name="map_review_acceptance_<n>", message=ACCEPTANCE_PROMPT)
spawn_agent(agent_type="predictor", task_name="map_review_user_experience_<n>", message=USER_EXPERIENCE_PROMPT)
spawn_agent(agent_type="documentation-reviewer", task_name="map_review_maintainer_<n>", message=MAINTAINER_PROMPT)
```

Codex dispatch rules:

- `<n>` increments on every dispatch in the run (including the Step A.2b truncation retry, the Step B.adversarial.2 re-invoke, and the second `--compare-orderings` collection), so every call gets a unique `task_name`.
- Each call sends its generated prompt as `message`, plus a reminder that the reviewer is read-only and must return only the required JSON.
- Wait for all dispatched reviewers and map each final JSON back to `BLIND_OUTPUT`, `EDGE_OUTPUT`, `ACCEPTANCE_OUTPUT`, `USER_EXPERIENCE_OUTPUT`, and `MAINTAINER_OUTPUT`.
- If concurrency is unavailable, make the same calls sequentially.
- Never replace independent review with parent-session personas.
- The routed Codex agent types carry their own developer instructions; the role prompt in `message` supplements them, it does not replace them.

## Step B.adversarial.2: Validate reviewer outputs

Each reviewer must return valid JSON matching the adversarial finding schema. If any reviewer output is truncated or invalid JSON:
- Log the failure
- Re-invoke that specific reviewer ONCE with the same prompt
- If still invalid, record the reviewer as `parse_error` and continue with remaining reviewers

## Step B.adversarial.3: Aggregate findings

Write each reviewer's raw JSON output to a temp file, then aggregate:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
BRANCH_DIR=".map/$BRANCH"
RUN_MODE="$BRANCH_DIR/review-mode.json"
QUICK_FLAG=$(python3 -c 'import json,sys; print("true" if "edge_case" not in json.load(open(sys.argv[1]))["scheduled_reviewers"] else "false")' "$RUN_MODE") || exit 1
# In compare-orderings set ORDERING_LABEL=default or reverse in this call.
if [ -n "${ORDERING_LABEL:-}" ]; then BRANCH_DIR="$BRANCH_DIR/review-collections/$ORDERING_LABEL"; fi
mkdir -p "$BRANCH_DIR"
cat > "$BRANCH_DIR/adversarial-blind.json" <<'BLIND_EOF'
<paste the Blind JSON envelope verbatim>
BLIND_EOF
cat > "$BRANCH_DIR/adversarial-acceptance.json" <<'ACCEPTANCE_EOF'
<paste the Acceptance JSON envelope verbatim>
ACCEPTANCE_EOF
cat > "$BRANCH_DIR/adversarial-user-experience.json" <<'USER_EOF'
<paste the User Experience JSON envelope verbatim>
USER_EOF
cat > "$BRANCH_DIR/adversarial-maintainer.json" <<'MAINTAINER_EOF'
<paste the Maintainer JSON envelope verbatim>
MAINTAINER_EOF
rm -f "$BRANCH_DIR/adversarial-edge.json"
ADV_ARGS=(--blind "$BRANCH_DIR/adversarial-blind.json" --acceptance "$BRANCH_DIR/adversarial-acceptance.json"
  --user-experience "$BRANCH_DIR/adversarial-user-experience.json" --maintainer "$BRANCH_DIR/adversarial-maintainer.json")
if [ "$QUICK_FLAG" != "true" ]; then
  cat > "$BRANCH_DIR/adversarial-edge.json" <<'EDGE_EOF'
<paste the Edge Case JSON envelope verbatim>
EDGE_EOF
  ADV_ARGS+=(--edge-case "$BRANCH_DIR/adversarial-edge.json")
fi
python3 .map/scripts/map_step_runner.py aggregate_adversarial_findings \
  "${ADV_ARGS[@]}" > "$BRANCH_DIR/review-agent-adversarial.json" || exit 1
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

## Step B.adversarial.5: Feed the verdict ledger

This phase does not assign a verdict. The capture block persists the complete
`adversarial_aggregate.v1` report, including `ledger_findings`, `reviewer_status`
and `parse_errors`. Closeout reads the current roster from `review-mode.json`;
`write_review_verdict_ledger --current-run` then computes
`PROCEED`/`REVISE`/`BLOCK` from the decision table in
[review-reference.md § Verdict Ledger](review-reference.md#verdict-ledger).
Corroboration raises confidence in the report; it does not change the verdict.

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