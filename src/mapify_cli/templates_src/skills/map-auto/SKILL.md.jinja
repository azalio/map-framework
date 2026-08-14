---
name: map-auto
description: |
  Single-entry autonomous autopilot: routes a task through the existing MAP workflows via `route_task`, then drives the selected chain (map-plan -> map-efficient -> map-check -> map-review, as routed) end-to-end to a committed feature branch in one session, auto-approving routine workflow-control holds and hard-stopping on dangerous_action/safety_guardrail holds. Use when you want the whole pipeline to run unattended from a single task description, without babysitting phase-by-phase invocation. Do NOT use when you want to review or edit the plan before execution (run /map-plan then /map-efficient yourself instead), when the task is trivial (use /map-fast directly), or when you need a PR opened or merged -- the autopilot always stops at a committed branch and never creates or merges a PR.
disable-model-invocation: true
argument-hint: "[task description]"
effort: high
---
# /map-auto — Single-Entry Autonomous Autopilot

Purpose: run `/map-auto <task>` once and let it route the task through the existing MAP workflows, then drive the selected chain end-to-end to a committed feature branch in the same session, without per-phase babysitting. `/map-auto` runs autonomously by default the moment it is invoked -- there is no shadow mode, no calibration period, and no opt-in flag to turn this behavior on.

Contrast with `/map-plan` and `/map-efficient`: those workflows expect you to drive each phase yourself. `/map-auto` is a thin router plus chain driver on top of them -- it never reimplements their logic, it only decides which one(s) to run and calls them unmodified, one after another, in the same session.

## Effort and Parallelism Policy

```yaml
thinking_policy: high/adaptive
parallel_tool_policy: sequential_by_default
```

- Use deeper reasoning for the routing decision and for judging whether a phase genuinely failed (worth a bounded re-entry) or is truly stuck (worth aborting to `/map-resume`) -- a wrong call here compounds across an entire unattended chain.
- Keep routing, hold-decision, phase-record, and phase-invocation calls strictly sequential; a chain driver has no independent work to parallelize across phases.
- Within a chained phase (e.g. `/map-efficient`), defer to that phase's own parallelism policy -- `/map-auto` does not override it.

## Determinism boundary

All routing and phase-ledger state lives in `.map/<branch>/auto-route.json` and is mutated ONLY through two runner subcommands below: `route_task` (routing decision) and `record_auto_phase` (phase ledger). `auto_decide_holds` (approval-hold triage) mutates `approval_holds.json` separately — its approvals surface in the `approval_hold` manifest stage, not in `auto-route.json`. Never hand-edit `auto-route.json`. Every command prints a JSON result; a non-success `status` means stop and read the message before continuing.

## Step 1: Route the Task

```bash
python3 .map/scripts/map_step_runner.py route_task "$ARGUMENTS"
```

To inspect the recommendation without committing to it (no write beyond the routing artifact itself, no phase started):

```bash
python3 .map/scripts/map_step_runner.py route_task "$ARGUMENTS" --dry-run
```

`route_task` writes `.map/<branch>/auto-route.json` (schema-validated) and selects exactly one of `map-resume`, `map-check`, `map-fast`, `map-plan`, `map-efficient` via a five-tier precedence engine you do not need to re-derive -- read `selected_route` and `next_command` from the result and act on those fields.

- `status: "refused"` -- an in-progress chain already exists for this branch; follow the returned `next_command` (`/map-resume`) instead of re-routing.
- `status: "blocked"` -- a hard-stop hold or a `goal_mismatch` verdict blocks the chain; `blocked_by[]` names the pending hold ids, `block_reason` explains why. STOP -- see Hard Stops below.
- `status: "success"` -- `chain_status` is `"in_progress"` (normal run) or `"recommended_only"` (`--dry-run`); proceed to Step 2 for the selected route.

## Step 2: Decide Holds Around Each Chained Phase

Poll `auto_decide_holds` before invoking each chained workflow AND again immediately after it concludes, before recording its outcome in Step 3 -- the second poll catches a hold that was created while the phase was running instead of leaving it for a later, unscheduled check:

```bash
python3 .map/scripts/map_step_runner.py auto_decide_holds
```

`auto_decide_holds` approves every pending `autonomy_posture`, `plan_approval`, and `template_overwrite` hold on your behalf and returns them in `auto_approved[]`. Any pending `dangerous_action` or `safety_guardrail` hold is returned in `hard_stops[]` and is left untouched -- these two kinds are never auto-decided by any code path this skill invokes.

### Hard Stops (dangerous_action / safety_guardrail)

If `route_task` reports `status: "blocked"` with entries in `blocked_by[]`, or either `auto_decide_holds` poll returns a non-empty `hard_stops[]`, STOP the autopilot. Do not retry, do not reinterpret the hold as auto-approvable, and do not proceed to the next phase. A hard stop found by the POST-phase poll means it appeared while the phase was running -- record that before stopping: `record_auto_phase "<phase>" aborted --reason "hard-stop hold pending: <ids>"`. A hard stop found via `route_task`'s `blocked_by[]` or the PRE-phase poll has no phase entry to record yet -- just stop. Either way, surface the hold's reason to the user and wait for an explicit human decision before resuming (`/map-resume` once it is decided).

## Step 3: Record Each Phase Boundary

Record every phase transition so `auto-route.json` stays the single source of truth for chain progress:

```bash
python3 .map/scripts/map_step_runner.py record_auto_phase "<phase>" "<status>" \
  --evidence-refs "<comma-separated auto-approved hold ids>" \
  --reason "<why this status>"
```

`<phase>` is the workflow name being entered/exited (`map-plan`, `map-efficient`, `map-check`, or `map-review`). `<status>` follows the phase's own vocabulary -- use `completed` on a clean phase close and `aborted`/`failed` on a phase you cannot recover; anything else leaves the chain `in_progress`. Pass every hold id that `auto_decide_holds` auto-approved for this phase in `--evidence-refs`, so the approval is recorded twice: once in the hold's own audit note, once in the phase ledger.

**At most one re-entry per phase (HC-2):** `record_auto_phase` mechanically enforces this -- the first record of a phase name is `attempt: 1`, a re-entry is `attempt: 2`, and a third call for the SAME phase name is refused and force-aborts the chain (`chain_status: "aborted"`). Before spending the single permitted re-entry, inspect ground truth -- `git status`/`git diff` and the phase's own `step_state.json` (or equivalent phase artifacts, test output, Monitor verdict) -- to confirm the phase genuinely needs a fresh attempt rather than a partial success being misread as a failure. A second failure of the same phase means STOP and hand off to `/map-resume` -- never attempt a third call for that phase. A chain already `chain_status: "aborted"` or `"blocked"` refuses every further `record_auto_phase` call regardless of phase name; a new `route_task` call is the ONLY legitimate way to continue.

## Chain

Once routed, drive the selected chain by invoking the existing slash workflows exactly as written, one after another in the same session:

```
route_task -> [map-plan] -> [map-efficient] -> [map-check] -> [map-review]
```

- `map-resume`, `map-check`, and `map-fast` routes are single-phase: run the one workflow, record its result with `record_auto_phase`, and finish.
- `map-plan` and `map-efficient` routes continue the chain: `map-plan` produces the task plan that `map-efficient` consumes, `map-efficient` implements it, and the chain then continues to `map-check` and `map-review` to close the loop.
- Invoke each phase by reading and following its own `SKILL.md` in full, exactly as if the user had typed the corresponding slash command -- do not summarize, skip, or reimplement its internal steps. `/map-auto` never shells out to a separate Claude process, a new Python execution engine, or any other new phase-driving mechanism to do this -- phases are driven ONLY by invoking the existing slash workflows above and the three runner subcommands from Steps 1-3.
- A `valid=false` Monitor verdict INSIDE a phase is that phase's own hard stop: its owning workflow's existing retry/escalation rules apply unchanged. `/map-auto` never overrides, suppresses, or re-runs past a Monitor rejection on the phase's behalf -- a phase that cannot get past Monitor is a failed phase for the purposes of Step 3's re-entry bound.
- The autopilot run ends at a committed feature branch. `/map-auto` never opens a pull request, never merges, and never polls CI -- report the committed branch, the phases recorded, and stop.

For the full CLI flag reference, a worked chain walkthrough, the failure-mode table, and recovery procedures, see [auto-reference.md](auto-reference.md).

## Examples

```
/map-auto add a --verbose flag to the status command
/map-auto refactor the checkout flow to support partial refunds
```

## Troubleshooting

- **Issue:** `route_task` returns `status: "refused"`. **Fix:** A chain is already `in_progress` on this branch; run `/map-resume` instead of re-routing.
- **Issue:** `route_task` or `auto_decide_holds` reports a pending `dangerous_action`/`safety_guardrail` hold. **Fix:** This is a hard stop by design -- surface the reason and wait for an explicit human decision; do not attempt to auto-approve it.
- **Issue:** `record_auto_phase` returns `status: "refused"` with `chain_status: "aborted"` or `"blocked"`. **Fix:** The chain is terminal; only a new `route_task` call can re-route it explicitly.
- **Issue:** A chained phase (e.g. `/map-efficient`) fails Monitor repeatedly. **Fix:** Let that phase's own retry/escalation rules run their course; record the outcome via `record_auto_phase` and stop after the single permitted re-entry rather than forcing a third attempt.
