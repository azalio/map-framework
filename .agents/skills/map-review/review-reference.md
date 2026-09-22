# $map-review Supporting Reference

This file contains lower-frequency review details for the Codex
`$map-review` port. Keep [SKILL.md](SKILL.md) focused on the active review
sequence. Read a section here only when the workflow step in SKILL.md
points to it.

## Modes

```bash
REVIEW_MODE="full"
# Empty / placeholder review-bundle.md => lightweight.
if [ -f ".map/$BRANCH/review-bundle.md" ] && \
   grep -qE 'MISSING|^- $|^—$' ".map/$BRANCH/review-bundle.md" && \
   ! grep -qE '^\s*##' ".map/$BRANCH/review-bundle.md"; then
   REVIEW_MODE="lightweight"
fi
# "twin of X", "sibling controller", "mirror of Y" in commit or PR body
# => sibling-aware (operator probably wants comparison, not synthesis).
SIBLING_HINT=""
if git log -1 --format=%B | grep -iE 'twin of |sibling |mirror of |port of ' >/dev/null; then
  REVIEW_MODE="sibling-aware"
  SIBLING_HINT=$(git log -1 --format=%B | grep -m1 -oiE '(twin of|sibling|mirror of|port of)[^.]*')
fi
REVIEW_MODE="$REVIEW_MODE" SIBLING_HINT="$SIBLING_HINT" BRANCH="$BRANCH" python3 -c '
import json, os
out = {"mode": os.environ["REVIEW_MODE"], "sibling_hint": os.environ.get("SIBLING_HINT", "")}
branch = os.environ["BRANCH"]
with open(f".map/{branch}/review-mode.json", "w") as f:
    json.dump(out, f)
'
```

Mode semantics:
- **`full`** (default): five-reviewer fan-out in total — monitor, predictor,
  evaluator + the two role passes (`user_experience`, `maintainer`), all four
  sections. The complexity lens is advisory and extra.
- **`lightweight`**: monitor only, diff-only, two sections (Code Quality +
  Tests), every finding must carry `reach_evidence`. Bundle is empty so
  reviewers have nothing to synthesize from — staying minimal prevents
  speculative findings.
- **`sibling-aware`**: BEFORE reviewer fan-out, identify the sibling
  (operator-supplied path or `$SIBLING_HINT` grep). Read the sibling's
  diff for the same file family. Reviewer prompts MUST receive the
  sibling text as a comparison baseline — findings that exist in sibling
  AND PR are pre-existing, not new (set `was_present_before_pr=true`).

## Flag Parsing

```bash
DETACHED_FLAG=false
if printf '%s' "$ARGUMENTS" | grep -q -- '--detached'; then
  DETACHED_FLAG=true
  ARGUMENTS=$(printf '%s' "$ARGUMENTS" | sed 's/--detached//g' | xargs)
fi

REVERSE_FLAG=false
if printf '%s' "$ARGUMENTS" | grep -q -- '--reverse-sections'; then
  REVERSE_FLAG=true
fi

SHUFFLE_FLAG=false
if printf '%s' "$ARGUMENTS" | grep -q -- '--shuffle-sections'; then
  SHUFFLE_FLAG=true
fi

SEED_RAW=""
if printf '%s' "$ARGUMENTS" | grep -qE -- '--seed[ =][0-9]+'; then
  SEED_RAW=$(printf '%s' "$ARGUMENTS" | sed -nE 's/.*--seed[ =]([0-9]+).*/\1/p')
fi

COMPARE_FLAG=false
if printf '%s' "$ARGUMENTS" | grep -q -- '--compare-orderings'; then
  COMPARE_FLAG=true
fi

if [ "$COMPARE_FLAG" = "true" ] && [ "$SHUFFLE_FLAG" = "true" ]; then
  echo '{"status":"error","reason":"--compare-orderings always uses default+reverse; cannot combine with --shuffle-sections (EC-1/EC-17)"}'
  exit 1
fi

QUICK_FLAG=false
SHOW_RAW_FLAG=false
if printf '%s' "$ARGUMENTS" | grep -q -- '--quick'; then
  QUICK_FLAG=true
fi
if printf '%s' "$ARGUMENTS" | grep -q -- '--show-raw-findings'; then
  SHOW_RAW_FLAG=true
fi

MODE_FLAG="default"
if [ "$REVERSE_FLAG" = "true" ]; then
  MODE_FLAG="reverse-sections"
elif [ "$SHUFFLE_FLAG" = "true" ]; then
  MODE_FLAG="shuffle-sections"
fi
```

## Dispatch

Extract each role's prompt from `REVIEW_PROMPTS_JSON`, then dispatch with
`spawn_agent(agent_type=...)`:

```bash
MONITOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["monitor"]["prompt"])')
PREDICTOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["predictor"]["prompt"])')
EVALUATOR_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["evaluator"]["prompt"])')
COMPLEXITY_LENS_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("prompts",{}).get("complexity_lens",{}).get("prompt", ""))')
COMPLEXITY_LENS_ENABLED=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); print("true" if data.get("prompts",{}).get("complexity_lens") else "false")')
USER_EXPERIENCE_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["user_experience"]["prompt"])')
MAINTAINER_PROMPT=$(printf '%s' "$REVIEW_PROMPTS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["prompts"]["maintainer"]["prompt"])')
```

```text
spawn_agent(agent_type="monitor", task_name="review_monitor", message=MONITOR_PROMPT)
# Full mode only — skip in lightweight mode (monitor-only):
spawn_agent(agent_type="predictor", task_name="review_predictor", message=PREDICTOR_PROMPT)
# Full mode only — skip in lightweight mode (monitor-only):
spawn_agent(agent_type="evaluator", task_name="review_evaluator", message=EVALUATOR_PROMPT)
# Full mode only — role reviewers. Isolated means: no other reviewer's
# output. They DO get read-only repo access on top of diff + bundle —
# both roles must run `git show <default-branch>:<file>` and grep the base.
spawn_agent(agent_type="predictor", task_name="review_user_experience", message=USER_EXPERIENCE_PROMPT)
spawn_agent(agent_type="documentation-reviewer", task_name="review_maintainer", message=MAINTAINER_PROMPT)
# When COMPLEXITY_LENS_ENABLED=true only:
spawn_agent(agent_type="evaluator", task_name="review_complexity", message=COMPLEXITY_LENS_PROMPT)
```

Full mode runs monitor + predictor + evaluator + both role reviewers;
lightweight mode runs monitor only. Role reviewers use the closest configured
Codex roles: `predictor` for user impact and `documentation-reviewer` for
maintainability and documentation consistency. Reviewer prompts reference `review-bundle.json`,
`review-bundle.md`, the raw diff as secondary context, and the expected
output schema (Monitor evidence/valid/verdict/issues,
Predictor evidence/risk_assessment/landmine_evidence, Evaluator
evidence/scores/monitor_severity_audit — same contract as Claude
`$map-review`; see `AGENT_OUTPUT_SCHEMAS` in `map_step_runner.py` for the
generated source of truth).

## Truncation Gate

After each reviewer returns, validate its output via stdin-piped
`detect_truncated_agent_output --agent <kind>` using the role-specific
kind — never pass agent output as an argv positional (control characters
in a multi-line response break argv parsing):

```bash
printf '%s' "$MONITOR_RESPONSE" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent review-monitor
printf '%s' "$PREDICTOR_RESPONSE" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent predictor
printf '%s' "$EVALUATOR_RESPONSE" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent evaluator
printf '%s' "$USER_EXPERIENCE_RESPONSE" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent user_experience
printf '%s' "$MAINTAINER_RESPONSE" | \
  python3 .map/scripts/map_step_runner.py detect_truncated_agent_output --agent maintainer
```

On truncation: log via
`log_agent_failure --agent <role> --phase post-invoke --failure-label truncated --reasons '<reasons>'`
and re-invoke that reviewer ONCE using the prompt piped from
`build_json_retry_prompt --agent <role> --errors '<reasons>'`; if still
malformed, stop with CLARIFICATION_NEEDED.

The optional complexity lens returns plain text, not JSON. Do not run the
JSON truncation gate on it; if it is empty or visibly cut off, rerun only
that lens prompt once.

## Verification Gate

For EVERY monitor / predictor finding, verify BEFORE listing it as a
walkthrough item:

1. **Evidence check.** Severity >= MEDIUM must carry `reach_evidence`
   (grep proving path is reached, failing test name, or linter line). No
   evidence => downgrade to `needs_investigation`, do NOT publish.
2. **Pre-existing check.** If `was_present_before_pr=true`, route to
   backlog/follow-up file, NOT to the walkthrough's REVISE list. PR review
   covers what the PR introduces.
3. **Sibling check (mode=sibling-aware).** If the same finding holds for
   the sibling reference, set `was_present_before_pr=true` and route to
   backlog. The PR can't be blocked on behavior that already shipped in
   the twin.
4. **Precheck duplication check.** If the finding matches a precheck error
   line, cite the precheck and stop — do NOT raise a second instance.
4b. **Role contract check.** A `user_experience` / `maintainer` finding is
   published only with all five contract parts filled (`problem`,
   `current_code`, `proposed_code`, `why_better`, `cost`). An incomplete
   one is not softened into an advisory: the ledger tombstones it as
   `contract_incomplete` and names it in `not_verified` — and above `minor`
   it escalates, so PROCEED is unavailable until a human rules on it.
5. **Reachability check** (defensive branches): guard-branch patterns
   usually exist by convention and their absence of tests is not a
   "missing test" finding unless the surrounding logic actually depends
   on the guard for correctness.
6. **Cross-agent challenge** (full mode only). If monitor's verdict
   disagrees with evaluator's `recommendation` by more than one tier,
   force a second pass: re-invoke monitor with evaluator's audit
   attached, asking it to defend or downgrade its verdict. Record the
   resolution in the bundle.

### Hard Stop Check

If monitor returns `valid=false` AND at least one issue survives the
verification gate above with `was_present_before_pr=false` and valid
`reach_evidence`, report ONLY the surviving issues immediately and skip
Phase B. Record `REVISE` or `BLOCK` as appropriate. Bare `valid=false`
without surviving evidence-backed issues is a "verification failed at
Step A.3" — proceed to Phase B (lightweight mode skips presentation) with
a verification note instead of publishing the bare verdict.

## Sections

Section rubrics:

- **Architecture**: boundaries, lifecycle, coupling, public API behavior,
  stage consumption.
- **Code Quality**: simplicity, naming, duplication, error handling,
  maintainability.
- **Tests**: changed behavior, failure cases, fixtures, coverage of
  acceptance tags.
- **Performance**: hot paths, large artifacts, prompt budgets, avoid
  speculative micro-optimizations.

Section presentation order comes from the shuffle-sections helper:

```bash
SECTIONS_JSON=$(python3 .map/scripts/map_step_runner.py shuffle-sections "$MODE_FLAG" "$SEED_RAW")
```

`'shuffle-sections'` randomizes order with a branch+commit derived seed
(or the explicit `--seed` override); `'reverse-sections'` presents in
reverse canonical order; `'default'` presents Architecture, Code Quality,
Tests, Performance in that order.

## What-To-Delete Lens

When `.map/config.yaml` sets `minimality` to `lite`, `full`, or `ultra`,
`build_review_prompts` emits an additional advisory `complexity_lens`
prompt. It is deliberately not emitted for `minimality: off` or missing
config.

The lens hunts only over-engineering in the current diff and reports one
line per finding:

```text
L<line>: <tag> <what>. <replacement>.
net: -<N> lines possible.
```

Allowed tags:
- `delete:` dead code, unused flexibility, or speculative feature;
  replacement is nothing.
- `stdlib:` hand-rolled behavior the standard library already ships; name
  the function.
- `native:` dependency or code doing what the platform already does; name
  the feature.
- `yagni:` abstraction with one implementation, config nobody sets, or a
  layer with one caller.
- `shrink:` same logic in fewer clear lines; show the shorter form.

If nothing should be cut, the entire output is:

```text
Lean already. Ship.
```

Boundaries: complexity only. Correctness, security, and performance
findings stay in the normal monitor/evaluator pass. A single smoke test or
assert-based self-check is the minimum and must not be flagged for
deletion. The lens samples and verifies `map:simplification:` marker
claims; the marker is evidence, not an exemption. `net: -N` is post-hoc
and advisory only: do not feed it into Actor retry context, do not use it
for PROCEED/REVISE/BLOCK, and do not let it incentivize deleting necessary
code.

## Compare Orderings

When `--compare-orderings` is set, collect one run with
`ordering_label='default'`, collect one with `ordering_label='reverse'`,
aggregate with `compare-review-runs`, then persist with
`record-review-ordering`. Treat verdict drift as review evidence.

## Role Reviewers

Two perspective roles run in BOTH review paths — the normal fan-out and
`--adversarial`. They answer questions nobody else in the fan-out is asked.

**`user_experience` — the person or script that CALLS this.** One question: did
the change make the ALREADY SHIPPED functionality harder or less convenient?

- Convenience regression: do the pre-diff scenarios still take the same number
  of steps? Did the old path gain a mandatory flag, field, or ordering rule?
- Distinguishability: two confusable flags/options/fields (`--release` vs
  `--from-release`)? Does the name alone say what it does?
- Explicit input beats a default: an explicitly supplied value that is
  incompatible with the new mode must be REJECTED with a clear error, never
  silently overridden. Where defaults and overrides are layered, the
  established priority contract must survive the change.
- The current flag set is not a given — propose the final one for the real
  goal when it confuses, even if that renames or splits flags.
- Judged from two sub-roles: a human in a terminal, and a CI script.

**`maintainer` — the person extending this a quarter from now.** One question:
can I extend this without re-reading every line, and without inheriting
temporary decisions tied to the current task? Checks:

| Class | What it hunts |
|---|---|
| A1 | Branch-scoped litter in comments (plan/tracker IDs, `.map/` paths, "step N") — it rots after merge |
| A2 | Implementation vocabulary leaking into help/error/log/doc text and generated surfaces (CRD descriptions, API schemas, CLI help) |
| A3 | Undiagnosable errors: a failure the user cannot explain from one run — no field name, data source, expected vs actual, safe value fragment, cause, or object id |
| B | Copy-paste: near-identical logic in 2+ places that must change in sync |
| C | Single source of truth: one decision computed in more than one place (not the sequential defaults/overrides chain) |
| D | Overcomplication: twisted booleans, deep nesting, mixed responsibilities, hops that unify nothing |
| E | Order of logic: validation / defaults / overrides / execution readable top to bottom; refusal before side effects |
| F | Dead or idle work: built-but-unused structures, calls for disabled subsystems, duplicated guards, data prepared then overwritten |
| G | Extensibility: how many places the next similar case touches — exact N before and after |
| H | Version/capability predicates: one module (H1), named by capability not number (H2), one comparison style (H3) — found by whole-base grep, not in the diff |
| I | Embedded shell/YAML/SQL/HCL inside string literals — unreviewable, untestable |
| J | Setting applied too low: a value carried through layers that only pass it on when the existing object-assembly point could apply it (J1–J6: trace, split use from transit, find the assembly point, justify late application, prove equivalence, count transit before/after) |
| K | Name vs contract: `ensure`/`sync`/`validate`/`get` that only disables, only creates, mutates, or writes; a one-sided switch named as two-sided |
| L | Mechanism named after its first application (`certification_controls` for feature toggles); files grouped by task rather than responsibility |
| M | File structure vs the local convention (M1 establish it from ≥2 neighbours, M2 find mixing, M3 language rule vs project rule, M4 the complete move with every reference) |

For B, C and H one site is not a finding: the finding is the number of sites and
the point where they collapse. The maintainer makes four separate passes —
correctness/completeness; setting propagation and decision sources; names and
boundaries (K, L); file structure (M) — and always records in
`checks_performed` which modules served as the structure baseline and whether
conventions are mixed, even with no findings.

Both roles review an attached plan as well as the code: matching the plan does
not prove the implementation is a good one. Existing signatures, names, fields,
the responsibility split and the places settings are applied are all under
review. Neither role modifies the working tree.

### The output contract

Every role finding carries five parts, or it is not reported:

| Part | Requirement |
|---|---|
| `problem` | one line: role, priority, exact `file:line` (every site when there are several), the concrete scenario or maintenance cost |
| `current_code` | the lines as they are, copied verbatim |
| `proposed_code` | applicable as a patch — signatures, bodies, imports, every call site, source→destination for moves; the helper itself, not "extract a helper" |
| `why_better` | checkable delta ("3 edit sites -> 1", "-1 responsibility", "3 transit params -> 0"); for names, the exact discrepancy removed — no invented metrics; bare "cleaner" is rejected |
| `cost` | the downside of the fix, or `none` |

Proposed patches are checked by reading only — the reviewer never applies
them, never builds a worktree for them, never compiles, lints or tests them —
and the presentation says so once, above both groups. Each finding also names
its `verified_by` tier: `read`, `test_run`, or `needs_environment`.

A finding missing any part is NOT softened into an advisory, but where it
lands depends on the path that ran: on the normal fan-out the ledger
tombstones it with `transition_reason: contract_incomplete` — at ANY
severity, and when that severity is above `minor` it also sets
`escalation_required`, so a CRITICAL dropped for a missing `cost` costs the
run its PROCEED instead of vanishing; under `--adversarial` the aggregator
removes it first, so it appears only under `contract_incomplete` in the
report and the ledger never sees it. Either way it cannot gate the change,
and it cannot disappear either.

Standalone prompt build (the normal fan-out builds these automatically):

```bash
python3 .map/scripts/map_step_runner.py build_role_review_prompts \
  [--roles user_experience,maintainer]
```

## Cross-AI

See the "Phase B: Cross-AI Peer Review" section in [SKILL.md](SKILL.md) for
the full Codex dispatch, status branching, and self-review edge case — the
authoritative cross-AI content for this port lives there (ported and
extended from ST-005), not duplicated here.

## Handoff Artifacts

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
SUMMARY=$(printf '%s' "$BUNDLE" | jq -r '.summary')
VALIDATION=$(printf '%s' "$BUNDLE" | jq -r '.validation')
RISKS=$(printf '%s' "$BUNDLE" | jq -r '.risks_follow_up')
python3 .map/scripts/map_step_runner.py write_pr_draft "$SUMMARY" "$VALIDATION" "$RISKS"

python3 .map/scripts/map_step_runner.py write_learning_handoff \
  map-review \
  "$ARGUMENTS" \
  "<PROCEED|REVISE|BLOCK>" \
  "<next action based on the verdict>" \
  "<brief note about the most reusable review lesson>"
```

This preserves `active-issues`, `pr-draft`, and `learning-handoff` flows.

If edits are needed (REVISE/BLOCK), write the stage gate so the owning
workflow can continue. Positional arguments are
`<stage> <verdict> <source_artifact> <notes>` — the summary is the FOURTH
argument, not the third. The runner normalizes `PROCEED` -> `ready`,
`REVISE` -> `needs-revision`, `BLOCK` -> `blocked`:

```bash
python3 .map/scripts/map_step_runner.py write_stage_gate \
  review \
  "$FINAL_VERDICT" \
  code-review-001.md \
  "$REVIEW_SUMMARY"
```

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

This writes `.map/<branch>/run_health_report.json` and updates the
`run_health` manifest stage.

## Examples

Plain review:
```text
$map-review correctness first
```

Cross-AI second opinion (requires `review.cross_ai.enabled: true`):
```text
$map-review --cross-ai codex
```

Detached review:
```text
$map-review --detached
```

CI review:
```text
$map-review --ci
```

Ordering drift check:
```text
$map-review --compare-orderings
```

## Troubleshooting

- Detached prep unavailable: continue from the in-place review bundle; do
  not mutate the source branch.
- Missing bundle: rerun `create_review_bundle` before agents.
- Oversized reviewer prompt: nothing is clipped and no `token_budget.json`
  entry is written for review — `MAP_REVIEW_PROMPT_BUDGET_TOKENS` is
  reported, not enforced. Reduce the input yourself (compact the session,
  or split the change); raising the variable changes nothing.
- Monitor invalid: treat as hard stop and record `REVISE` or `BLOCK`.
