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
- **Eval-set validation error on `--dry-run`** — check that each case has a non-empty `id`, a `prompt`, and at least one `assertions` entry with a valid `type`.
- **Run log not found for `--resume`** — `--resume` looks for the latest `.map/eval-runs/<skill>/<timestamp>.jsonl`. If no prior run exists, omit `--resume` to start fresh.
- **All cases report `not_trigger` unexpectedly** — verify the skill name matches exactly (e.g. `map-plan`, not `map_plan`) and that `.claude/` was seeded correctly in the temp cwd.

## Related Commands

- `/map-plan` — plan and decompose tasks.
- `/map-efficient` — full MAP workflow execution.
- `/map-check` — run quality gates and verify MAP workflow completion.
