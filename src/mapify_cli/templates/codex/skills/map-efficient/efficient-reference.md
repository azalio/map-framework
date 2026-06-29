# $map-efficient Supporting Reference

This file holds lower-frequency details for the Codex `$map-efficient` skill.
Load only the section needed by the active phase.

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
echo "$MONITOR_JSON" | python3 .map/scripts/map_orchestrator.py \
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
| any | `off` (default) | any | Legacy sequential walker (`get_next_step`) |
| `off` | any | any | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | no (all groups size 1) | Legacy sequential walker (`get_next_step`) |
| `auto` / `on` | `auto` / `required` | yes | Wave-loop (`get_wave_step` / `validate_wave_step` / `advance_wave`) |

**Defaults (canonical MapConfig):** `execution.wave_mode=auto`,
`worktree.isolation=off`. The isolation gate fails by default, so a stock
`mapify init` config always runs the legacy sequential walker. Even when the
wave-loop engages, dispatch remains **sequential** in Slice 5a (`isolation_active=True`,
`dispatch_mode` from `get_wave_step` keyed to `sequential`); concurrent fan-out
is Slice 5b (`dispatch_mode==concurrent`, `concurrency_enabled=True`),
**ACTIVE when opted in** via `execution.concurrent_dispatch: true`
(gate: `dispatch_mode == 'concurrent'`).

### Sequential walker

Use `get_next_step` for all sequential (default) execution. Do not mix wave
APIs with the sequential cursor for the same workflow.

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

When `worktree.isolation` is enabled and a wave has ≥2 disjoint subtasks
(`isolation_active=True`), execute the **Slice 5a sequential worktree flow**:

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

### Concurrent actor dispatch — **Slice 5b** (`dispatch_mode == 'concurrent'`) — **ACTIVE when opted in**

> **IMPORTANT — read before using this section.**
> Concurrent fan-out (dispatching N actor subagents in a single turn) is
> **ACTIVE when opted in** via `execution.concurrent_dispatch: true`
> (gate: `dispatch_mode == 'concurrent'`). With the **default config**
> (`concurrent_dispatch=false`, Slice 5a), dispatch stays **SEQUENTIAL
> even when a wave has `mode=="parallel"`** — one actor subagent per turn, each
> pinned to its own worktree. Act on the instructions below **only** when
> `get_wave_step` returns `dispatch_mode == 'concurrent'`. Use your runtime's
> own parallel actor-subagent dispatch mechanism — this is the provider-neutral
> shape, not a literal API call.

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

> These apply **only** under Slice 5b concurrent dispatch (`dispatch_mode == 'concurrent'`). In Slice 5a and the default sequential walker, one actor dispatch per turn **is** the correct behavior.

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
