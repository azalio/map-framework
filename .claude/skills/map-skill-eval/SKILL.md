---
name: map-skill-eval
description: |
  Evaluate a /map-* skill's trigger accuracy and cost. Use when asked to measure skill trigger accuracy, run an eval-set, or check token/duration cost via `mapify skill-eval`. Do NOT use to plan or implement; use map-plan or map-efficient.
effort: medium
disable-model-invocation: true
argument-hint: "[skill] [--eval-set PATH]"
---
# /map-skill-eval — Skill Trigger Accuracy & Cost Evaluation

Purpose: measure whether a `/map-*` skill fires on the right prompts and what it costs in tokens and time. Do not plan or implement from this skill.

Requires the `claude` CLI (installed and on `$PATH`). The skill is skipped at install time on hosts without `claude`.

## Constraints (NEVER)

- **NEVER** plan or implement from this skill — it only measures trigger accuracy and cost. For work, use `/map-plan` or `/map-efficient`.
- **NEVER** launch a non-dry-run `run`/`optimize` when the eval-set size or quota cost is unknown — run `--dry-run` first to see the call budget (each case spends a real `claude -p` call).
- **NEVER** hand-edit the durable run log (`.map/eval-runs/<skill>/*.jsonl`) or `*-optimize.json` results — `--resume` and `view` depend on their integrity.
- **NEVER** auto-commit an `--apply` change — `--apply` only stages the re-rendered description; review the diff, and patch `skill-rules.json` `description` by hand (it is not auto-patched).

## Before reporting (self-check)

- Confirm the run completed (not interrupted) — if it was, re-run with `--resume`; do not report a partial pass-rate.
- Confirm the reported pass-rate equals passed/total and every case has a verdict.

## Invocation

```bash
mapify skill-eval run <skill> --eval-set PATH [--dry-run] [--resume] [--max-concurrency N]
```

- `<skill>` — the skill name to evaluate (e.g. `map-plan`).
- `--eval-set PATH` — path to a JSON eval-set file defining prompt cases and expected assertions.
- `--dry-run` — validate the eval-set and print the planned run count without spending any quota.
- `--resume` — continue an interrupted run from the last durable checkpoint.
- `--max-concurrency N` — max parallel `claude -p` workers (default: 1).

## What It Does

1. **Prompts × runs matrix** — for each case in the eval-set, invokes `claude -p` in an isolated temporary working directory seeded with `.claude/` (skills, settings). Runs are independent; no shared state leaks between cases.
2. **Transcript-parse trigger detection** — parses each `claude -p` transcript to determine whether the target skill fired (trigger) or did not fire (not_trigger).
3. **Deterministic assertions** — each eval case may specify one or more assertion types:
   - `contains` / `not_contains` — substring presence in the response.
   - `regex` — pattern match against the response.
   - `valid_json` — response parses as JSON.
   - `trigger` / `not_trigger` — skill fired / did not fire.
4. **Durable resumable run log** — results are appended to `.map/eval-runs/<skill>/<timestamp>.jsonl` as each case completes, so a partial run is recoverable via `--resume`.
5. **Summary report** — after all cases complete, prints pass-rate (passed/total) plus per-case token usage, duration, and cache-hit stats.

## Eval-Set Format

A JSON object with an `entries` array. Each entry has a `prompt`, optional
`should_trigger` / `should_not_trigger` skill names (the runner turns these into
`trigger` / `not_trigger` assertions), and an optional `assertions` array.
Assertion types: `contains`, `not_contains`, `regex`, `valid_json`, `trigger`,
`not_trigger`.

```json
{
  "entries": [
    {
      "prompt": "Decompose this feature into subtasks",
      "should_trigger": "map-plan",
      "assertions": [
        { "type": "contains", "value": "subtask" }
      ]
    },
    {
      "prompt": "Run quality gates",
      "should_not_trigger": "map-plan",
      "assertions": []
    }
  ]
}
```

## --dry-run

`--dry-run` validates the eval-set schema and prints the planned case count with estimated quota usage. No `claude -p` calls are made; no `.jsonl` is written.

## Examples

```bash
# Validate eval-set without spending quota
mapify skill-eval run map-plan --eval-set .map/evals/map-plan.json --dry-run

# Run full eval with up to 8 parallel workers
mapify skill-eval run map-plan --eval-set .map/evals/map-plan.json --max-concurrency 8

# Resume an interrupted run
mapify skill-eval run map-plan --eval-set .map/evals/map-plan.json --resume
```

## Troubleshooting

- **`claude` not found** — `map-skill-eval` requires the `claude` CLI on `$PATH`. Install it and re-run `mapify init` to activate the skill.
- **Eval-set validation error on `--dry-run`** — check that each case has a non-empty `prompt` (the only required field); that `should_trigger` / `should_not_trigger`, if present, are strings; and that every `assertions` entry has a valid `type`. Cases carry no user-supplied `id` — `cell_id`s like `p0-v1-r2` are derived automatically.
- **Run log not found for `--resume`** — `--resume` looks for the latest `.map/eval-runs/<skill>/<timestamp>.jsonl`. If no prior run exists, omit `--resume` to start fresh.
- **All cases report `not_trigger` unexpectedly** — verify the skill name matches exactly (e.g. `map-plan`, not `map_plan`) and that `.claude/` was seeded correctly in the temp cwd.

## Optimize a skill description

Anti-overfit description optimizer: deterministic 60/40 train/test split, up to N iterations (iteration 0 = baseline = current description). Selects the candidate with the highest held-out TEST pass-rate; an overfit candidate (train pass-rate up, test pass-rate down) is flagged and never selected.

```bash
mapify skill-eval optimize <skill> --eval-set PATH [--iterations N] [--apply] [--open] [--dry-run]
```

- `<skill>` — skill to optimize (e.g. `map-plan`).
- `--eval-set PATH` — eval-set JSON with `>= 5` entries (a 60/40 split needs `n_test >= 3`; a smaller set exits with code 2, spending zero quota).
- `--iterations N` — maximum optimization iterations (default: 5). Iteration 0 is the baseline.
- `--apply` — patch the winning description into the SKILL.md frontmatter `description:` of `templates_src/skills/<skill>/SKILL.md.jinja` and re-render so generated trees stay byte-identical; the change is staged, not committed. `skill-rules.json` `description` is NOT auto-patched (update it by hand). Two no-op cases: "No improvement found" (baseline already optimal) and "Winner identical to current".
- `--open` — open the HTML report in the browser after the run (best-effort; never errors the run).
- `--dry-run` — print the planned call budget (iterations × (n_train + n_test) dispatch calls + iterations proposer calls) and `model: default (resolved by claude CLI)`, then exit 0 spending zero quota.

Writes a durable `OptimizeResult` JSON and an HTML report to `.map/eval-runs/<skill>/<timestamp>-optimize.json` and `<timestamp>-optimize.html`.

Default mode is propose-only: nothing outside `.map/` is modified.

### Examples

```bash
# Preview quota usage without spending any
mapify skill-eval optimize map-plan --eval-set .map/evals/map-plan.json --dry-run

# Run 3 optimization iterations and open the HTML report
mapify skill-eval optimize map-plan --eval-set .map/evals/map-plan.json --iterations 3 --open

# Run, then auto-apply the winning description if improvement found
mapify skill-eval optimize map-plan --eval-set .map/evals/map-plan.json --apply
```

## View an optimization report

Renders the latest (or a specified `--result`) stored `OptimizeResult` JSON as an HTML report.

```bash
mapify skill-eval view <skill> [--result PATH] [--open]
```

- `<skill>` — skill whose optimization results to view.
- `--result PATH` — path to a specific `*-optimize.json` result file; defaults to the latest in `.map/eval-runs/<skill>/`.
- `--open` — open the rendered HTML report in the browser.

### Examples

```bash
# View the latest optimization report for map-plan
mapify skill-eval view map-plan

# Open a specific result file in the browser
mapify skill-eval view map-plan --result .map/eval-runs/map-plan/20260601T120000-optimize.json --open
```

## Optimizing the whole skill (BODY/logic), not just the description

`mapify skill-eval optimize` tunes only the trigger **`description:`** (does the skill fire on the
right prompt?). To improve a skill's **body/logic** by OUTCOME quality (does it do its job well once
it runs?), do NOT start from scratch — there is a worked, reusable flow and harness:

- **Flow (start here):** `docs/whole-skill-optimization-flow.md` — measure outcome quality on golden
  fixtures with a hybrid metric (deterministic gates + a trace-cited LLM judge), then human-edit the
  body and re-measure (Approach B). Includes the fixture recipe, the measure→edit loop, and gotchas.
- **Working log + findings:** `docs/whole-skill-optimization-notes.md`.
- **Harness:** `tests/skills_eval/whole_skill/spike_runner.py` (`--degrade {body,actor,monitor}`),
  fixtures under `tests/skills_eval/fixtures/whole_skill/`.

**Key finding (don't re-derive):** for thin-orchestration skills (e.g. `map-task`), prose scope/
correctness discipline — in the SKILL.md body OR the shared agent prompts — is **low-leverage**
(ablations showed body-good == body-bad). The real levers are the **`affected_files` contract** and
the **mechanical validators** (`validate_mutation_boundary` + test-gate + the MONITOR warn→feedback
gates). Prose optimization pays off where behavior is genuinely prose-governed: the final **report
format** and the **trigger description** (this skill). Spend effort accordingly.

## Related Commands

- `/map-plan` — plan and decompose tasks.
- `/map-efficient` — full MAP workflow execution.
- `/map-check` — run quality gates and verify MAP workflow completion.
