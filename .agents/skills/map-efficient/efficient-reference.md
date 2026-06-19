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

## Wave Execution

Sequential execution is the default. Use wave APIs only when the blueprint has
multiple ready subtasks whose writes are low-risk and disjoint, or when the user
explicitly requests parallel execution.

Commands:

```bash
python3 .map/scripts/map_orchestrator.py set_waves --blueprint ".map/${BRANCH}/blueprint.json"
python3 .map/scripts/map_orchestrator.py get_wave_step
python3 .map/scripts/map_orchestrator.py validate_wave_step "$STEP_ID"
python3 .map/scripts/map_orchestrator.py advance_wave
```

Do not mix wave APIs with the sequential `get_next_step` cursor for the same
wave unless the orchestrator response explicitly tells you to fall back.

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
