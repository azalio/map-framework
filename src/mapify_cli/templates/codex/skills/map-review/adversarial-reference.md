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

## Steps B.adversarial.0–3: Collect through the Codex runner

After admission and immutable bundle creation, run:

```bash
python3 .map/scripts/codex_review_runner.py
```

The driver reads the admitted roster, creates independent environment-free threads,
probes each host boundary, serves only each role's permitted immutable context,
validates individual reports and captures the tagged adversarial aggregate. Blind
remains diff-only. Compare-orderings uses separate thread/session/receipt sets.
Poll the running command; on interruption rerun it under the same admitted round.
Do not spawn native readers, copy chunks through the parent, or promote an unverified
probe. See SKILL.md Step A.2 for the capability and recovery contract. Read the
captured `review-agent-adversarial.json` (or both review-collections in compare mode)
for presentation, then proceed below.

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
