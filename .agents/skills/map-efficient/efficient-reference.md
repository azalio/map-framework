# $map-efficient Supporting Reference

This file holds lower-frequency details for the Codex `$map-efficient` skill.
Load only the section needed by the active phase.

## Approval-Hold Preflight

Resolve any pending approval hold BEFORE Step 0's `resume_from_plan`
bootstraps execution state. A ready plan itself needs no approval —
`$map-plan` no longer opens a hold.

```bash
python3 .map/scripts/map_step_runner.py list_approval_holds --state pending
```

Each pending hold's `kind` decides the branch:

- **`plan_approval`** (left by an older `$map-plan`) — not a gate. Do not
  ask the operator; close it and continue:
  ```bash
  python3 .map/scripts/map_step_runner.py decide_approval_hold \
    <hold-id> approved --note "plan_approval no longer gates execution"
  ```
- **`dangerous_action` / `safety_guardrail`** (hard stops) — never decide
  these from inside the preflight. Refuse to proceed: surface the hold's
  `reason` and `request_summary`, and stop. The operator resolves the
  underlying issue out of band and decides the hold via `decide_approval_hold`
  before retrying.

If the operator already decided a hold manually (CLI) before starting
`$map-efficient`, the preflight finds nothing pending and proceeds.

## Pre-Monitor Gates

Before Monitor, verify that Actor output and repository state agree.

```bash
python3 .map/scripts/map_step_runner.py detect_actor_files_changed_mismatch \
  "$BRANCH" "$SUBTASK_ID" --declared "$FILES_CSV"
python3 .map/scripts/map_step_runner.py detect_symbol_blast_radius \
  "$BRANCH" "$SUBTASK_ID"
```

If `detect_actor_files_changed_mismatch` reports `status_mismatch=true`, finish
the missing edits before Monitor. If `detect_symbol_blast_radius` recommends
`validate_callers`, include external callers in Monitor's review context.

## Cross-Subtask Regression Gate

Before committing or recording a clean Monitor result, ask whether a scoped test
run is safe:

```bash
python3 .map/scripts/map_step_runner.py detect_cross_subtask_regression_risk \
  "$BRANCH" "$SUBTASK_ID"
```

If `recommended_gate == "full_suite"`, run the full suite. A focused run is
allowed only when the detector returns `scoped` and the subtask contract does
not require broader validation.

## Flaky-Test Triage

If a test/check fails inconsistently, repeat the exact failing command with the
runner and record the outcomes before acting on the failure:

```bash
python3 .map/scripts/map_step_runner.py run_flaky_test_triage \
  --check-id "pytest::test_name" \
  --runs 3 \
  --timeout 120 \
  -- python -m pytest tests/test_file.py::test_name
python3 .map/scripts/map_step_runner.py validate_flaky_test_triage
# Preferred close — the verdict path. Monitor emits valid:false plus
# disposition {kind: deferred_nondeterministic, check_id: ...}; close 2.4 with
# the same disposition piped through (see "Verdict-path route" below).
printf '%s' "$MONITOR_JSON" | python3 .map/scripts/map_orchestrator.py \
  validate_step 2.4 --disposition deferred_nondeterministic \
  --check-id "pytest::test_name" --monitor-envelope -
```

The runner executes argv with `shell=False`; shell syntax is not interpreted. If
shell behavior is intentionally needed, pass a shell explicitly as argv, for
example `-- bash -lc 'python -m pytest tests/unit && echo done'`.

Manual evidence remains available when repeated runs were already collected:

```bash
python3 .map/scripts/map_step_runner.py record_flaky_test_triage \
  "pytest::test_name" \
  '[{"run":1,"exit_code":1,"summary":"AssertionError"},{"run":2,"exit_code":0,"summary":"passed"}]' \
  --command "pytest tests/test_file.py::test_name" \
  --reason "Mixed pass/fail outcomes across repeated runs."
python3 .map/scripts/map_step_runner.py validate_flaky_test_triage
```

Mixed pass/fail evidence writes `.map/<branch>/flaky_test_triage.json`, updates
the `flaky_test_triage` manifest stage, and returns
`disposition=deferred_nondeterministic`. This disposition is not a passing
gate: do not weaken, skip, or delete the check, and do not return a silent
green. Monitor must include the recorded defer evidence and
`monitor_verdict_policy=not_valid_without_explicit_triage` in its finding.

**Verdict-path route (preferred).** The third Monitor outcome is wired into the
2.4 close: `validate_step 2.4 --disposition deferred_nondeterministic --check-id
<id> --monitor-envelope -`. The deferral is honored ONLY when (a) the Monitor
envelope is `valid:false` with a non-empty `failed_checks` and a structured
`disposition` matching the flags, and (b) the sidecar holds mixed pass/fail
evidence for that `check_id` — so a deterministic failure or a green check can
never be deferred. A deferred run returns `valid:false` + `deferred:true`
(non-green, exit 0, not a hard-stop), records `status=deferred_nondeterministic`
with evidence metadata, and advances without requeueing Actor. `recommendation`
may be omitted or `needs_investigation`; `revise`/`block` are rejected as
contradictory.

**Lower-level command.** `defer_flaky_subtask "$SUBTASK_ID" --check-id <id>`
performs the same close+advance directly (e.g. an operator deferral with no
Monitor envelope); the verdict-path route calls it internally after the
envelope/anti-gaming checks.

## Wave Execution

### Execution strategy decision table

`select_execution_strategy` picks between the legacy sequential walker and the
wave-loop on every run. The wave-loop engages **only when ALL THREE hold**
(otherwise the legacy sequential walker `get_next_step` runs):

1. `execution.wave_mode` ∈ {`auto`, `on`}, **AND**
2. `worktree.isolation` ≠ `off`, **AND**
3. at least one color group has ≥2 members.

| `execution.wave_mode` | `worktree.isolation` | Color group ≥2? | Dispatcher selected |
|---|---|---|---|
| any | `off` (opt-out) | any | Legacy sequential walker (`get_next_step`) |
| `off` | any | any | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | no (all groups size 1) | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | yes | Wave-loop (`get_wave_step` / `validate_wave_step` / `advance_wave`) |

**Defaults (canonical MapConfig):** `execution.wave_mode=auto`,
`worktree.isolation=auto`, `execution.concurrent_dispatch=true`.
Parallel-ready plans select the wave-loop by default; concurrent dispatch is
selected only for an eligible current wave with ≥2 members. A width-1 current
wave remains sequential even if a later wave is parallel. Follow `get_wave_step`'s
`dispatch_mode`, not the defaults alone.

**Sequential off-ramps and degraded fallback:**
- `MAP_EFFICIENT_SEQUENTIAL_ONLY=1` forces the full legacy sequential path.
- `execution.wave_mode: off`, no parallel color groups, or `worktree.isolation: off`
  select the sequential walker. If disabling isolation, also set
  `execution.concurrent_dispatch: false`: concurrent dispatch with isolation off
  is a configuration contradiction (`DispatchGateError`), not a silent fallback.
- `execution.concurrent_dispatch: false` disables concurrent fan-out; an eligible
  isolated wave can still use the sequential worktree flow (Slice 5a).
- `resolve_worktree_isolation` checks git availability, worktree support, and a
  clean merge target. In `auto` mode a failed check returns `degraded:true` and
  `decision:sequential` with a warning: follow that sequential fallback, never
  dispatch concurrent Actors into the shared tree. In `required` mode the same
  failure aborts. Other structured worktree errors remain hard stops.

### Sequential walker

Use `get_next_step` only when `select_execution_strategy` selects the legacy
sequential walker. `dispatch_mode=sequential` alone does not switch cursors:
an active wave retains `get_wave_step`, `validate_wave_step`, and `advance_wave`,
dispatching one Actor at a time. If `degraded=true` and `isolation_active=false`,
execute the wave sequentially without creating or merging worktrees and without
`run_concurrent_wave`. Do not switch to the legacy cursor without an explicit
supported cursor transition.

### Wave-loop commands

```bash
python3 .map/scripts/map_orchestrator.py set_waves --blueprint ".map/${BRANCH}/blueprint.json"
python3 .map/scripts/map_orchestrator.py get_wave_step
python3 .map/scripts/map_orchestrator.py validate_wave_step "$STEP_ID"
python3 .map/scripts/map_orchestrator.py advance_wave
```

Do not mix wave APIs with the sequential `get_next_step` cursor for the same
wave unless the orchestrator response explicitly tells you to fall back.

Use wave APIs only when the blueprint has multiple ready subtasks whose writes
are low-risk and disjoint, or when the user explicitly requests parallel
execution.

When `isolation_active=True`, inspect `dispatch_mode` first: `concurrent` uses
`run_concurrent_wave` below. Only when `dispatch_mode` is `sequential`, execute
the **Slice 5a sequential worktree flow**:

1. **Create** a worktree per wave member via `create_subtask_worktree`.
2. **Dispatch actor subagents sequentially** — one per turn (`HC-3`), each
   pinned to its own worktree path. Do NOT dispatch all in one turn (that is
   Slice 5b / `dispatch_mode==concurrent`).
3. **Verify** all member worktrees with `concurrency_ready` before merge.
4. **Accept atomically** — never merge one at a time (the first merge advances
   HEAD and the next trips `BASE_DIVERGED`):

```bash
python3 .map/scripts/map_step_runner.py merge_wave_worktrees "$ST_A" "$ST_B"
```

It runs the post-wave gate inside the transaction and rolls the whole wave back
to base on any conflict or gate failure (worktrees kept for retry). On a single
subtask's Monitor failure, `discard_subtask_worktree` that subtask and retry it
before calling `merge_wave_worktrees`.

### Concurrent actor dispatch — **Slice 5b** (`dispatch_mode == 'concurrent'`) — **default-ON, gate-controlled**

> **IMPORTANT — read before using this section.**
> Concurrent fan-out (actor subagents in a single turn) is **default-ON, gate-controlled**
> via `execution.concurrent_dispatch=true`. Act on this section **only** when
> `get_wave_step` returns `dispatch_mode == 'concurrent'`. With an explicit
> `execution.concurrent_dispatch: false`, isolated waves dispatch sequentially
> (Slice 5a), one Actor per turn. A sequential fallback is not concurrent fan-out.
> Use your runtime's own parallel actor-subagent dispatch mechanism — this is
> the provider-neutral shape, not a literal API call.

**Runtime wiring:** when `get_wave_step` returns `dispatch_mode == 'concurrent'`,
call `run_concurrent_wave` (runner), which batch-splits the wave by `max_actors`
and merges each sub-batch atomically via `merge_wave_worktrees`. For each sub-batch,
dispatch all N actor subagents **in one turn** — not one per turn:

```text
# CORRECT (dispatch_mode=='concurrent' only) — N actor subagents in one turn:
dispatch actor subagent -> ST-003 (pinned to its own worktree)
dispatch actor subagent -> ST-004 (pinned to its own worktree)

# INCORRECT — one actor per turn (serial, defeats the wave):
# Turn 1: actor -> ST-003
# Turn 2: actor -> ST-004
```

**Self-audit before dispatch:** "I will dispatch {n} actor subagents in one turn."

**`max_actors` cap:** Default 4–8 per wave. Groups larger than `max_actors` are
pre-split into sequential batches before dispatch.

**Retry-discard on failure:** on any actor failure, timeout, or Monitor-reject
within a concurrent group, the runner calls `abort_wave_group`, which discards
the **entire group** (cancels siblings, resets all worktrees to base SHA, removes
group branches) and reruns from base. Retries are bounded by `max_wave_retries`
(default 3); on exhaustion the runner escalates to a human and does **not**
auto-restart. Never merges a successful subset — discard-all-or-merge-all (HC-4).

### Anti-patterns — Slice 5b concurrent dispatch only

> These apply **only** under Slice 5b concurrent dispatch (`dispatch_mode == 'concurrent'`). In Slice 5a and the legacy sequential walker, one actor dispatch per turn **is** the correct behavior.

- One actor dispatch per turn across N turns — serial loop, no concurrency. (Slice 5b only — expected, correct behavior in 5a.)
- Writing between dispatches (TodoWrite, etc.) — serializes the batch. (Slice 5b only.)
- Waiting for one actor result before dispatching the next. (Correct for 5a, wrong for 5b.)
- Mixing `get_next_step` and `get_wave_step` for the same wave. (Applies to both 5a and 5b.)

## TDD Mode

`--tdd` inserts `TEST_WRITER` and `TEST_FAIL_GATE` before `ACTOR`.

Rules:

- Write tests before production code.
- Run the new tests and confirm they fail for the intended reason.
- Treat tests that pass before implementation as weak tests; revise them before
  Actor work.
- Do not edit production code in `TEST_WRITER`.

## Monitor Retry Loop

Every Monitor failure needs durable evidence:

1. Write `.map/<branch>/code-review-N.md` with the exact issue, file path, and
   required fix.
2. Run `monitor_failed --feedback "$MONITOR_FEEDBACK"`.
3. Fix only the current subtask.
4. Re-run Monitor.

If retries start repeating, check the orchestrator response for retry isolation
or circuit-breaker guidance before another Actor attempt.

## Acceptance proof completion (MANDATORY)

For single, batch and wave execution, freeze owned AC proofs after independent TEST_WRITER/RED and before Actor. Use the exact spec IDs and the contract/revision protocol in `../map-plan/plan-reference.md#runner-witnessed-acceptance-proofs`. Never silently re-freeze Actor edits. `implementation_complete` is not accepted completion: when the orchestrator returns `FINAL_VERIFICATION`, finish intended code changes/commit, run `run_acceptance_proofs`, consume `evaluate_acceptance`, generate `write_verification_summary`, then call `mark_workflow_complete`. Existing gates still apply. Do not skip the proof attempt just because explicit completion can allow warn-first `unproven`; list those ACs honestly. Failed/stale or integrity/unresolved-execution errors block; new commits/local changes require fresh proofs.

## Per-Subtask Commit Policy

After a clean Monitor pass, a per-subtask commit is allowed and usually
preferred when the repository is in a reviewable state. Stage named files only.

```bash
git add <files from Monitor files_changed>
git commit -m "ST-NNN: <one-line summary>"
SHA=$(git log -1 --format=%H)
python3 .map/scripts/map_orchestrator.py record_subtask_result \
  "$SUBTASK_ID" valid --files "$FILES_CSV" --summary "$ONE_LINE" \
  --commit-sha "$SHA"
```

Do not use `git add .`. Do not amend a published commit. Do not bypass hooks.
If the user requested one bundled commit or the intermediate state cannot pass
hooks, document the deferral and record the subtask result without committing.

## Final Verification

Final verification must prove the full plan:

- Read `.map/<branch>/task_plan_<branch>.md`.
- Read `.map/<branch>/step_state.json`.
- Inspect the final diff.
- Run the verification commands required by the plan.
- Confirm Monitor artifacts do not contain unresolved valid=false findings.
- Write `run_health_report.json` with `write_run_health_report`.

## Approved baseline gate deferrals

Only an exact user decision in the current conversation may defer a verified
historical lint/type/test diagnostic outside the approved mutation boundary.
Save the user's words and the diagnostic identity, failing command, baseline
and current output, approved boundary, and source-versus-HEAD comparison in
`.map/<branch>/approved-baseline-gates.md`. Check that introduced-only and
scoped gates pass. Pass the exact decision and record path to Actor and Monitor;
use `[none]` if there is no approval. An agent's claim or an old-failure label
never establishes consent. Monitor independently checks the record and still
reports the full gate as failed. Unknown, changed, security, correctness, and
in-scope failures block.

With worktree isolation, a configured `verification_checks` command can still
exit nonzero after Monitor accepts the scoped result. Before either worktree
merge, save `.map/<branch>/approved-baseline-gates.json` with a `failures`
array. Each entry binds the exact `command`, `base_sha`, sorted `subtask_ids`,
nonzero `returncode`, SHA-256 digests of the complete baseline `stdout` and
`stderr` (`stdout_sha256`, `stderr_sha256`), `approval_sha256` for the Markdown
record bytes, and a nonempty `diagnostic`. Use one subtask ID for a pre-merge
worktree check and all wave IDs for a post-wave check. The runner compares the
current output and exit code byte-for-byte to this evidence; changed, missing,
or unapproved results still fail and roll back normally. Accepted output has
`status: approved_baseline_failed` and `full_gate_status: failed` in its check
evidence. Keep the full command output and source comparison in the Markdown
record; a digest is only the runner's exact-match guard, not independent proof
that the failure is harmless. Monitor must verify the user decision and scope.

## RESEARCH artifact schema (exact contract)

`save_research` persists the bytes you pipe verbatim; `validate_research` then
enforces the machine-checkable contract below before Actor consumes the artifact.
Hand-author to this exact schema so the FIRST save validates.

Top-level object — strict JSON only (no markdown, no ``` code fences, ≤ 64 KiB):

| field | type | rule |
| --- | --- | --- |
| `status` | string | exactly one of `OK`, `PARTIAL_RESULTS`, `NO_RESULTS`, `SEARCH_FAILED` (upper-case enum — NOT free text like `"complete"`/`"high"`) |
| `confidence` | number | float in `[0, 1]` (NOT a word like `"high"`) |
| `search_stats` | object | exactly `files_scanned` (int ≥ 0), `total_matches_found` (int ≥ 0), `results_truncated` (bool) — these exact field names |
| `relevant_locations` | array | ≤ 5 entries; each is `{path, lines, relevance}` |

Each `relevant_locations[]` entry:

| field | type | rule |
| --- | --- | --- |
| `path` | string | safe relative repo path (no absolute, `~`, `\`, or `..`); must exist unless the entry is marked absent (`"exists": false`, `"absent": true`, or `"status"` ∈ `absent`/`missing`/`new`/`not_found`) |
| `lines` | array | `[start, end]` — two positive ints, `start ≤ end`, span `end - start + 1 ≤ 200`, `end` within the file's line count (NOT a `"start-end"` string) |
| `relevance` | string | non-empty; explain why the range matters. Never inline `content`/`file_contents`/`raw_code` |

Copy-pasteable skeleton (a valid artifact — swap in your real values):

```json
{
  "status": "OK",
  "confidence": 0.8,
  "search_stats": {
    "files_scanned": 12,
    "total_matches_found": 4,
    "results_truncated": false
  },
  "relevant_locations": [
    {
      "path": "src/example/module.py",
      "lines": [10, 42],
      "relevance": "why this range matters to the current subtask"
    }
  ]
}
```

`validate_research` echoes this exact skeleton in its `skeleton` field on ANY
failure, so the first reject is self-correcting: copy the `skeleton`, swap your
values, re-save. Extra fields beyond the contract are allowed and ignored.

## Stale Commit Attribution Recovery

If `last_subtask_commit_sha` resolves but `git diff` fails (for example, the
commit is unavailable after history rewriting), preserve the fail-closed `status="error"`:
unknown committed changes are not an empty diff.

1. Stop and preserve the checkpoint and Actor work. Query `get_interruption_status`
   first; a non-idle result requires its reported recovery. Do not hand-edit
   `step_state.json`, reinitialize with `resume_single_subtask`/`resume_from_plan`,
   or re-snapshot scope/subtask baselines: these can erase attribution or hide
   Actor changes. `record_scope_baseline` cannot repair a failed diff.
2. A valid exact-subtask repair-adjusted tree takes priority over the stored
   commit SHA. Do not override the base with `HEAD` or an explicit validator
   base. If an entry is recorded but its tree object is missing/invalid, stop
   and ask the operator; re-recording a commit cannot repair it.
   If no exact-subtask adjusted-base entry is recorded, proceed to step 3.
3. Only for an ordinary commit baseline, use repository evidence to identify its
   verified rewritten counterpart and prove the boundary includes all current Actor changes.
   Use the orchestrator's `record_subtask_result` with explicit `--commit-sha`
   to re-record the same genuine completed result ID, status, files, and summary;
   do not fabricate a result or record current `HEAD` merely to move the baseline.
   If this is the current subtask's already-recorded commit, its rewritten parent
   must still bound all of that subtask's work: automatic resolution uses that parent.
   The writer replaces the result; this is not a lossless recipe for arbitrary filename lists or enriched result records.
4. Rerun `validate_mutation_boundary` for the current subtask without a base
   override, inspect its result, then rerun the current subtask's Monitor before
   normal closeout. Do not refresh `affected_files` just to conceal a violation.

If the counterpart or full Actor boundary cannot be proven, stop and ask the
operator: existing APIs provide no general lossless rebase-attribution migration.


## Troubleshooting

- `resume_from_plan` fails: inspect the returned JSON and fix missing plan,
  blueprint, or branch artifacts before continuing.
- `validate_blueprint_contract` fails: fix the blueprint before Actor work.
- `validate_step` rejects Monitor close: obey its recovery instruction; do not
  force-advance state.
- `step_state.json` disagrees with artifacts: use orchestrator commands to
  repair or resume. Do not edit the JSON manually.
- Final closeout lacks `.map/<branch>/run_health_report.json`: rerun
  `write_run_health_report` with an explicit status.
