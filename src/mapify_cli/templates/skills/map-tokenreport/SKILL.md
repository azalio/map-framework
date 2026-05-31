---
name: map-tokenreport
description: |
  Show per-subtask/agent token accounting (input, output, cache read/creation, cost, cache-hit ratio) for the current branch. Use when asked for token usage, run cost, or a token report. Do NOT use to plan or run work; use map-efficient.
effort: low
disable-model-invocation: true
argument-hint: "[branch]"
---
# /map-tokenreport - Token Accounting Report

Purpose: surface how many tokens (and how much money) the current branch's MAP
run spent, attributed to the subtask, phase, and agent that spent them.
Read-only reporting — this skill does not plan, implement, or run quality
gates.

The numbers come from the `map-token-meter` hook (wired on `SubagentStop` and
`Stop`), which reads each Claude Code transcript's per-turn `usage` block and
appends attributed rows to `.map/<branch>/token_log.jsonl`, rolled up into
`.map/<branch>/token_accounting.json`. This skill just renders that rollup.

## What it shows

- **input / output** tokens, **cache_read** (cheap cache hits) and
  **cache_creation** (cache writes) — tracked separately because they bill at
  very different rates.
- **est_cost_usd** — priced per model via `MODEL_TOKEN_PRICES` in
  `map_step_runner.py` (estimate, not a billing source of truth).
- **cache_hit_ratio** = `cache_read / (input + cache_read)` — how well prompt
  caching is paying off.
- Breakdowns by subtask, by agent (actor / monitor / research-agent /
  orchestrator / ...), and by phase.

## Steps

### Step 1: Resolve the branch

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
```

If the user passed an explicit branch argument, use it instead of the detected
one.

### Step 2: Render the report

```bash
python3 .map/scripts/map_step_runner.py token_report "$BRANCH"
```

`token_report` re-reads `token_log.jsonl`, rebuilds `token_accounting.json`,
and prints a per-subtask table plus a TOTAL line with the cache-hit ratio and
estimated cost. It is idempotent and read-only against your code.

### Step 3: Optional — inspect the raw rollup

For the per-agent / per-phase split (the table only shows per-subtask), read
the JSON directly:

```bash
jq '{aggregate, by_agent, by_phase}' ".map/${BRANCH}/token_accounting.json"
```

### Step 4: Summarize

Report the totals (input / output / cache), the cache-hit ratio, and the
estimated cost. Call out the most expensive subtask or agent, and a low
cache-hit ratio if present (it usually means prompt-cache churn worth
investigating). Then STOP — do not change code from this skill.

## Examples

Report token usage for the current branch:

```text
/map-tokenreport
```

Report for a specific branch:

```text
/map-tokenreport feat/add-multiply
```

Typical output:

```text
Token accounting — feat-add-multiply (93 assistant turns)

subtask              input      output     cache_rd    cache_cr     $cost
-------------------------------------------------------------------------
ST-001                 183     150,879   14,085,841     792,780     47.31
-------------------------------------------------------------------------
TOTAL                  183     150,879   14,085,841     792,780     47.31

cache hit ratio: 100.0%   est cost: $47.31
```

## Troubleshooting

- **`token_accounting.json` does not exist / report is empty.** The
  `map-token-meter` hook has not fired for this branch yet. It records on
  `SubagentStop` and `Stop`, so a brand-new branch with no completed turns has
  nothing to show. Confirm the hook is wired in `.claude/settings.json`
  (`SubagentStop` and `Stop` entries) and that `.map/<branch>/token_log.jsonl`
  exists.
- **Everything is attributed to `orchestrator` / `unattributed`.** Those turns
  ran outside a MAP subtask (e.g. direct edits, or before `step_state.json` had
  a `current_subtask_id`). Per-subtask attribution appears once a
  `/map-efficient` run sets the active subtask.
- **Cost looks high relative to raw input.** That is expected when most input
  is cached: `cache_creation` is the dominant cost on cache-heavy runs. Compare
  `cache_creation` vs `cache_read` and the cache-hit ratio to see where the
  spend goes.
- **Unknown model in cost estimate.** `MODEL_TOKEN_PRICES` falls back to the
  default model price for unrecognized model ids; update that table in
  `map_step_runner.py` when a new model ships.
