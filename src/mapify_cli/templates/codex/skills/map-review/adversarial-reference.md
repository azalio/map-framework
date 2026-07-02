# Adversarial Review Reference

Detailed workflow for `$map-review --adversarial`. See [SKILL.md](SKILL.md)
for context and integration points. This is the Codex counterpart to Claude
`--adversarial`: the same three-reviewer contract, run as three SEQUENTIAL
IN-SESSION passes by the current Codex session instead of a parallel agent
fan-out.

## Design note: why sequential in-session passes, not spawn_agent()

The currently-registered Codex agent types are `researcher`, `decomposer`,
`monitor`, `predictor`, `evaluator` (see `config.toml.jinja` and the
`agents/*.toml.jinja` files). None of them is "blind hunter", "edge case
hunter", or "acceptance auditor" — those are ad-hoc, generically-typed
reviewer roles in the sibling implementation for another AI harness, not
registered Codex agent types.

**Whether `spawn_agent()` can target a NEW, ad-hoc, unregistered agent name
(one outside the five above) is an UNVERIFIED ASSUMPTION carried over from
discovery, not a proven platform limitation.** This file deliberately does
NOT resolve that assumption — it picks the simpler, verifiably-correct
option instead: run the three reviewer passes sequentially in the current
Codex session, with the session itself switching context/persona between
passes, rather than betting on an unconfirmed dispatch capability.

Spot-check performed during research: reviewed `spawn_agent` usage in the
existing map-plan Codex port
(`src/mapify_cli/templates_src/codex/skills/map-plan/SKILL.md.jinja`) and
`docs/ARCHITECTURE.md`. Every `spawn_agent(agent_type=...)` call site in
map-plan targets one of the five registered types above; no example
anywhere spawns an ad-hoc unregistered agent name. `docs/ARCHITECTURE.md`
documents the audited dispatch sites and registered agent roster but does
not state whether the underlying platform primitive accepts arbitrary
`agent_type` strings. No Codex platform documentation is available in this
repo or environment to confirm or deny ad-hoc agent spawning either way.
**Treat this as open and unresolved** — if a future change confirms
`spawn_agent()` does support ad-hoc names, revisit this file and the
parallel-fan-out design can be reconsidered; do not assume it silently
works today.

## Overview

Three reviewer passes, each with only its permitted inputs, run ONE AFTER
ANOTHER in the current session (never in parallel, never via a new
agent-dispatch primitive):

| Pass | Context | Finds |
|------|---------|-------|
| **Blind Hunter** | diff only | Typos, dead code, logic errors visible in isolation |
| **Edge Case Hunter** | diff + repo read access | Null handling, boundary conditions, error paths, codebase consistency |
| **Acceptance Auditor** | diff + spec + plan + artifacts | Missed requirements, spec violations, AC gaps, extra/unplanned work |

With `--quick`: skip the Edge Case Hunter pass (Blind + Acceptance only).

Between passes, deliberately narrow the session's working context to match
the pass's permitted inputs (e.g. do not consult the spec while running the
Blind Hunter pass) so the three passes stay as independent as a sequential,
single-session execution allows.

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

`build_adversarial_review_prompts` is the exact same CLI verb the Claude
port calls — payload flows out via stdout JSON only, never via argv, per
the stdin-safe piping convention used throughout this skill.

## Step B.adversarial.1: Run all three passes sequentially, in-session

```text
# Run the three adversarial reviewer passes ONE AFTER ANOTHER in the
# current Codex session. Do NOT call spawn_agent() for these passes and do
# NOT invent a new agent-dispatch primitive — see "Design note" above for
# why. Each pass consumes only its permitted context (BLIND_PROMPT /
# EDGE_PROMPT / ACCEPTANCE_PROMPT) and produces its own JSON finding
# report before the next pass begins.

Pass 1 (Blind Hunter):      execute BLIND_PROMPT in-session -> BLIND_OUTPUT
Pass 2 (Edge Case Hunter):  execute EDGE_PROMPT in-session -> EDGE_OUTPUT   (skip if --quick)
Pass 3 (Acceptance Auditor): execute ACCEPTANCE_PROMPT in-session -> ACCEPTANCE_OUTPUT
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
- Per-pass: Blind: B, Edge Case: E, Acceptance: A
- All-clear: [passes that reported all_clear=true]

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
Phase A (all steps) → Phase B: Adversarial Review (3 sequential in-session
passes) → Final Verdict → Handoff Artifacts. Do NOT run the normal
Monitor/Predictor/Evaluator fan-out or the 4-section walkthrough.

## Examples

See [review-reference.md](review-reference.md#examples) for adversarial examples.

## Troubleshooting

### A pass returns invalid JSON

Re-run that specific pass ONCE. If still invalid, record `parse_error` and
continue — two valid passes are better than zero.

### All three passes fail

Stop with CLARIFICATION_NEEDED. The diff may be too large or the context
too complex for adversarial review.

### Edge Case Hunter pass runs out of context

The Edge Case Hunter pass has repo read access. If the repo is very large,
limit its scope by pre-computing an impact graph of files
importing/imported-by the changes plus relevant tests. Defer full
implementation to v2.
