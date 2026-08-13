# /map-auto Supporting Reference

This file holds low-frequency `/map-auto` details so `SKILL.md` stays focused on the active route -> holds -> phase-ledger loop.

## CLI Reference

Three runner subcommands back the whole autopilot; `SKILL.md` calls them in order (`route_task` once, then `auto_decide_holds` / `record_auto_phase` per chained phase). No other subcommand drives the chain.

```bash
python3 .map/scripts/map_step_runner.py route_task <task> [--branch B] [--dry-run]
python3 .map/scripts/map_step_runner.py auto_decide_holds [--branch B]
python3 .map/scripts/map_step_runner.py record_auto_phase <phase> <status> [--branch B] \
  [--evidence-refs a,b,c] [--reason "..."]
```

- `route_task <task>` -- `<task>` is the free-text task description (quote it). `--branch` defaults to the current branch. `--dry-run` recommends a route without marking the chain `in_progress` (see Dry-run usage below).
- `auto_decide_holds` -- no positional arguments; only `--branch` (defaults to current branch).
- `record_auto_phase <phase> <status>` -- `<phase>` is the workflow name (`map-plan`, `map-efficient`, `map-check`, `map-review`); `<status>` is the phase's own outcome word (`completed`, `failed`, `aborted`, or any other phase-specific status, which leaves `chain_status` at `in_progress`). `--evidence-refs` takes a comma-separated list of ids (auto-approved hold ids from the surrounding `auto_decide_holds` calls); `--reason` is a free-text note stored on the ledger entry.

## Chain Walkthrough Example

A `map-efficient` route, condensed (real output trimmed to the fields that matter):

```bash
$ python3 .map/scripts/map_step_runner.py route_task "add retry to the sync job"
{"status": "success", "selected_route": "map-efficient", "chain_status": "in_progress", ...}

$ python3 .map/scripts/map_step_runner.py auto_decide_holds
{"status": "ok", "auto_approved": [{"id": "hold-1", "kind": "plan_approval", ...}], "hard_stops": []}

# -- drive /map-efficient unmodified, in full, per its own SKILL.md --

$ python3 .map/scripts/map_step_runner.py auto_decide_holds
{"status": "ok", "auto_approved": [], "hard_stops": []}

$ python3 .map/scripts/map_step_runner.py record_auto_phase "map-efficient" "completed" \
  --evidence-refs "hold-1" --reason "all subtasks closed, make check green"
{"status": "success", "chain_status": "completed", "phase": "map-efficient", "attempt": 1, ...}

# -- chain then continues to map-check, then map-review, each following the same
#    poll -> drive -> poll -> record loop, until the last phase records "completed" --
```

The run ends there: a committed feature branch, `phases[]` in `auto-route.json` holding one entry per phase attempt, and no PR/merge/CI step of any kind.

## Failure-Mode Table

| Failure mode | Trigger | Response |
|---|---|---|
| Hard-stop hold | `dangerous_action` or `safety_guardrail` hold pending (at route time or discovered mid-phase) | STOP the autopilot; surface the hold's reason; wait for an explicit human decision; resume via `/map-resume` once it is decided. Never auto-approved by any `/map-auto` code path (INV-2). |
| Repeated phase failure (HC-2) | A third `record_auto_phase` call for the SAME phase name | Refused outright -- no entry appended; the chain is force-aborted (`chain_status: "aborted"`) with the abort reason persisted in `auto-route.json`. Recover via `/map-resume`; a fresh `route_task` on the aborted branch re-routes and preserves the prior route in `route_history[]`. |
| `goal_mismatch` | `check_plan_resume` reports the branch already hosts a plan for a DIFFERENT goal | `route_task` refuses to route: `status: "blocked"`, `chain_status: "blocked"`, `block_reason` names the mismatch. The prior spec/task_plan/blueprint artifacts are left untouched -- resolving the mismatch (archive, rename, or confirm intent) is the operator's call. |
| In-progress re-route | `route_task` called while the branch's `auto-route.json` already has `chain_status: "in_progress"` | Refused: `status: "refused"`, `next_command: "/map-resume"`; the existing artifact is left byte-identical. |
| `blueprint_unavailable` | `step_state.json` exists but `blueprint.json`'s subtask-id universe can't be read | Routes to `map-resume` rather than guessing "complete" -- recorded as `evidence: [{"signal": "step_state.json", "value": "blueprint_unavailable", ...}]`. |

## Recovery Procedures

- **`/map-resume`** -- the single recovery surface for every stop condition above: a refused re-route, an aborted chain, a hard-stop hold once it is decided, or a phase that failed Monitor past its own retry budget. It reads the branch's existing state (`step_state.json`, `auto-route.json`) and resumes from there; it never re-runs `route_task` on your behalf.
- **New `route_task` from a terminal chain** -- `chain_status` values `aborted`, `blocked`, `completed`, and `recommended_only` may all be re-routed; only `in_progress` refuses. A re-route overwrites `auto-route.json` but preserves the superseded route in `route_history[]`, so a fresh `route_task "<task>"` call is the ONLY way to move a terminal chain forward -- never hand-edit `chain_status` in the artifact.

## Dry-run Usage

`route_task "<task>" --dry-run` is the whole dry-run surface (Decision 8) -- there is no separate preview command for holds or phases, because neither runs until a real (non-dry-run) `route_task` call marks the chain `in_progress`.

```bash
python3 .map/scripts/map_step_runner.py route_task "add retry to the sync job" --dry-run
```

- Sets `executed: false` and `chain_status: "recommended_only"` -- the run is a recommendation, not a commitment.
- Performs no filesystem writes beyond `.map/<branch>/auto-route.json` and its `auto_route` manifest stage entry -- no `record_workflow_fit`, no `create_approval_hold`, nothing else on disk changes (AC-3).
- A pending hard-stop hold still surfaces: `blocked_by[]` is populated and `chain_status` becomes `"blocked"` even under `--dry-run` -- "blocked" always outranks "recommended_only".
- Re-running `route_task` (with or without `--dry-run`) after a dry-run is always allowed -- `recommended_only` is not a terminal `chain_status`.

## Troubleshooting

- **Issue:** `record_auto_phase` reports `status: "error"`. **Fix:** No `auto-route.json` exists for this branch yet -- run `route_task` first.
- **Issue:** Need to inspect the ledger without another CLI call. **Fix:** Read `.map/<branch>/auto-route.json` directly (read-only) -- `phases[]`, `chain_status`, `abort_reason`/`block_reason`, and `route_history[]` are all plain fields; never hand-edit the file.
- **Issue:** A phase's own Monitor keeps rejecting past what looks like a real fix. **Fix:** That is the chained workflow's own retry/escalation, not `/map-auto`'s -- let it run its course; `/map-auto` only records the outcome once that workflow itself stops.
