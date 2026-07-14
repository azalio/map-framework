# Skill-Eval — Trigger Accuracy & Description Tuning

> Repeatable guide for the `mapify skill-eval` engine (Phase F). Read this instead of
> re-deriving the workflow from source each time.

## What it is

`skill-eval` measures and improves how reliably a `/map-*` skill **fires on the right
prompts** (trigger accuracy) and what it **costs** (tokens / wall-clock). It has two jobs:

1. **`run`** — score a skill against an eval-set: pass-rate + per-case token/duration/cache stats.
2. **`optimize`** — anti-overfit tuner that rewrites the skill's `description:` frontmatter to
   maximise held-out trigger accuracy, then (optionally) applies the winner to the template source.

A third command, **`view`**, re-renders a stored optimize result as an HTML report.

A fourth command, **`trajectory`**, scores the OUTCOME of a full run (not just
the trigger) — it is documented separately in [TRAJECTORY-EVAL.md](TRAJECTORY-EVAL.md).

The lever it tunes is the **`description:` field** of a skill — the text Claude Code reads to
decide whether a prompt should activate that skill. Better description = fewer false triggers
(skill fires when it shouldn't) and fewer misses (skill stays silent when it should fire). It does
**not** touch the skill body / logic.

## Requirements

- The **`claude` CLI** must be on `$PATH`. The skill is skipped at install time on hosts without it.
- Auth is via the **Claude.ai subscription** — no `ANTHROPIC_API_KEY`. A failed `claude -p` is
  never an API-key problem.
- Each eval case spawns a real `claude -p` in an isolated temp cwd seeded with `.claude/`. Runs are
  independent — no state leaks between cases.

## Commands

```bash
# Score a skill against an eval-set (accuracy + cost)
mapify skill-eval run <skill> --eval-set PATH [--dry-run] [--resume] [--max-concurrency N]

# Tune the skill's description for trigger accuracy (anti-overfit 60/40 split)
mapify skill-eval optimize <skill> --eval-set PATH [--iterations N] [--apply] [--open] [--dry-run]

# Render the latest (or a specific) optimize result as HTML
mapify skill-eval view <skill> [--result PATH] [--open]
```

### `run` flags
| Flag | Meaning |
|---|---|
| `--eval-set PATH` | **Required.** JSON eval-set (see format below). |
| `--dry-run` | Validate the eval-set + print planned case count. Spends **zero** quota; writes no `.jsonl`. |
| `--resume` | Continue an interrupted run from the latest `.map/eval-runs/<skill>/<ts>.jsonl`. |
| `--max-concurrency N` | Parallel `claude -p` workers. Default **1**. |

### `optimize` flags
| Flag | Meaning |
|---|---|
| `--eval-set PATH` | **Required.** Needs enough entries that `n_test >= 3` (see sizing). |
| `--iterations N` | Max iterations. Default **5**. Iteration 0 = baseline (current description). |
| `--apply` | Patch the winning description into `templates_src/skills/<skill>/SKILL.md.jinja` and re-render. **Staged, not committed.** `skill-rules.json` is **not** auto-patched. |
| `--open` | Open the HTML report after the run (best-effort). |
| `--dry-run` | Print the call budget and exit 0 spending zero quota. |

### `view` flags
| Flag | Meaning |
|---|---|
| `--result PATH` | A specific `*-optimize.json`. Defaults to the latest in `.map/eval-runs/<skill>/`. |
| `--open` | Open the rendered HTML in the browser. |

## Eval-set format

A JSON object with an `entries` array. Each entry:

```json
{
  "entries": [
    {
      "prompt": "Decompose the new auth feature into atomic subtasks.",
      "should_trigger": "map-plan",
      "assertions": [{ "type": "contains", "value": "decompose" }]
    },
    {
      "prompt": "What is 2 + 2?",
      "should_not_trigger": "map-plan"
    }
  ]
}
```

- **`prompt`** — required on every entry.
- **`should_trigger` XOR `should_not_trigger`** — at most one per entry (or neither). The runner
  turns these into `trigger` / `not_trigger` assertions automatically.
- **`assertions`** — optional list. Types:
  - `contains` / `not_contains` — substring in the response.
  - `regex` — pattern match against the response.
  - `valid_json` — response parses as JSON.
  - `trigger` / `not_trigger` — target skill fired / did not fire.
- Include **1–2 `should_not_trigger` negatives** so the rejection path is exercised.
- `contains` values should be lowercase substrings that genuinely appear in the prompt/response.

### Sizing — why ≥ 8 entries for `optimize`

The optimizer uses a deterministic 60/40 train/test split: `n_test = max(1, round(n * 0.4))`.
The held-out signal is only meaningful when **`n_test >= 3`**, i.e. **n ≥ 8** (target **8–10** entries).

- Code hard-floor: `optimize` exits **code 2** (zero quota) if the set is too small to reach `n_test >= 3`.
- `run` has no such floor — any non-empty valid set works.
- Note: the `map-skill-eval` SKILL.md mentions "≥ 5 entries"; the real binding constraint is
  `n_test >= 3`, so author **≥ 8** to be safe.

> Smoke fixture caveat: `tests/skills_eval/fixtures/map_debug_eval_set.json` is a pinned **3-entry**
> smoke set for unit tests — do **not** add entries or rename it. Optimizer fixtures are the
> `*_optimize_eval_set.json` files.

## Budget math (read before spending quota)

`optimize` dispatch budget:

```
iterations × (n_train + n_test) dispatch calls  +  iterations proposer calls
```

Example — `map-plan`, 9-entry set, default 5 iterations: `5 × (5 + 4) = 45` dispatch + `5`
proposer = **50 `claude -p` calls**. Sequentially (default `--max-concurrency 1`) that is minutes
per skill. **Always run `--dry-run` first** to see the exact count, and lower `--iterations` (e.g.
2–3) to cut cost when sweeping many skills.

## Anti-overfit logic

- Iteration 0 scores the **current** description as baseline.
- Each iteration the proposer suggests a new description; it is scored on **train** and **test**.
- The winner is the candidate with the highest **held-out TEST** pass-rate.
- A candidate whose **train ↑ but test ↓** is flagged as overfit and **never selected** (the HTML
  report highlights it red).
- Two no-op outcomes: **"No improvement found"** (baseline already optimal) and **"Winner identical
  to current"**.

## Output artifacts

- `run`: `.map/eval-runs/<skill>/<timestamp>.jsonl` — one line appended per completed case
  (durable, `--resume`-able).
- `optimize`: `.map/eval-runs/<skill>/<timestamp>-optimize.json` (the `OptimizeResult`) **and**
  `<timestamp>-optimize.html` (report).
- Default `optimize` mode is **propose-only**: nothing outside `.map/` changes until `--apply`.

## `--apply` and the single-source render invariant

`--apply` patches the description into the **template source**
`src/mapify_cli/templates_src/skills/<skill>/SKILL.md.jinja` and re-renders so every generated tree
(`.claude/`, `.codex/`, `src/mapify_cli/templates/`, `.agents/skills/`) stays byte-identical.
**Never edit a generated `SKILL.md` directly.** The change is **staged, not committed** — review it.

`skill-rules.json` `description` is **not** auto-patched. If the skill's trigger description also
lives there, update it by hand (in `templates_src/skills/skill-rules.json.jinja`) and
`make render-templates`.

## Repeatable workflow — optimize one skill

```bash
# 0. Author / locate an eval-set (>= 8 entries, mix of trigger + not_trigger).
#    Keep reusable fixtures under tests/skills_eval/fixtures/<skill>_optimize_eval_set.json

# 1. Validate the set + see the budget (zero quota):
uv run mapify skill-eval optimize <skill> \
  --eval-set tests/skills_eval/fixtures/<skill>_optimize_eval_set.json --dry-run

# 2. Real run, propose-only, open the report:
uv run mapify skill-eval optimize <skill> \
  --eval-set tests/skills_eval/fixtures/<skill>_optimize_eval_set.json \
  --iterations 3 --open

# 3. Inspect the HTML / JSON. If the winner beats baseline on TEST, apply it:
uv run mapify skill-eval optimize <skill> \
  --eval-set tests/skills_eval/fixtures/<skill>_optimize_eval_set.json \
  --iterations 3 --apply

# 4. Verify generated trees stayed consistent, then review the staged diff:
make check-render
git diff --staged

# 5. If skill-rules.json carries the same description, hand-edit the .jinja and re-render:
make render-templates
```

## Operational notes — running a real sweep (READ THIS)

Each `run`/`optimize` spawns real `claude -p` subprocesses. When you sweep many skills these
gotchas bite — they are the reason a sweep "hangs":

### 1. Disable the Telegram hook during `claude -p` runs

Every `claude -p` subprocess starts a fresh Claude session, which fires the **telegram-bridge
plugin's `SessionStart` hook**. That hook launches a `tg listen` listener which contends on the
shared Telegram file lock — concurrent/seeded sessions can **hang** waiting on it.

- skill-eval already ships a built-in mitigation: `dispatcher._eval_subprocess_env` sets
  `TG_STATE_DIR` to a config-less path inside the throwaway cwd, so the listener finds no
  `config.json` and exits. But it still **creates stale lock files** (`~/.claude/telegram/listen.*mapeval*.lock`).
- **Belt-and-suspenders for a big sweep:** temporarily disable the plugin globally and restore it
  after:
  ```bash
  # before the sweep — disable
  python3 - <<'PY'
  import json, pathlib
  p = pathlib.Path.home()/".claude"/"settings.json"
  d = json.loads(p.read_text())
  d.setdefault("enabledPlugins", d.get("enabledPlugins", {}))["telegram-bridge@azalio"] = False
  p.write_text(json.dumps(d, indent=2))
  PY
  # ... run the sweep ...
  # after the sweep — re-enable (do this in a finally/always step; don't leave it off)
  ```
- `tg send` (pushing progress to the user) still works while the plugin is disabled — it is a
  standalone script, independent of the SessionStart auto-listen hook.

### 2. Timeout per run — 1 hour

A single skill's `optimize` (5 iter × ~9 = ~45 serial `claude -p` calls) can run ~30 min; a stuck
`claude -p` can hang indefinitely. **Wrap every run in a hard 1-hour timeout** and continue the
sweep on failure (a timed-out skill simply isn't applied):

```bash
for skill in <small...large>; do
  timeout 3600 uv run mapify skill-eval optimize "$skill" \
    --eval-set "tests/skills_eval/fixtures/${skill//-/_}_optimize_eval_set.json" \
    --iterations 5 --apply >> /tmp/skilleval-sweep.log 2>&1 || \
    echo "SKILL $skill FAILED/TIMED OUT" >> /tmp/skilleval-sweep.log
done
```

### 3. Monitor the run — it can hang

Run the sweep in the background and **poll its log**; do not assume progress. Watch for: a skill
with no new log lines for many minutes (stuck `claude -p` → let the 1h timeout kill it), or repeated
`not_trigger` (eval-set / skill-name problem). Push per-skill progress to Telegram with `tg send`.

### 4. `--apply` serially, never overlap with another run

`--apply` re-renders all generated trees (`.claude/`, `.codex/`, `templates/`) and `git add`s them.
If a second skill's `optimize` is seeding its temp cwd from `.claude/` at that moment, it can copy a
half-rendered tree. **Keep the sweep serial** (one skill fully done — including apply — before the
next starts). `optimize --apply` does a **single** eval run then applies from the in-memory result —
no double-spend.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `claude not found` | `claude` CLI not on `$PATH`. Install it, re-run `mapify init` to re-activate the skill. |
| Validation error on `--dry-run` | Each entry needs a non-empty `prompt`; assertions need a valid `type`. |
| `optimize` exits code 2 | Eval-set too small — needs `n_test >= 3` (≥ 8 entries). |
| `--resume` finds no log | No prior `.jsonl` for that skill — omit `--resume` to start fresh. |
| Every case reports `not_trigger` | Skill name must match exactly (`map-plan`, not `map_plan`); confirm `.claude/` seeded in temp cwd. |
| Optimize "No improvement found" | Baseline description already optimal for this eval-set — not an error. |

## Source map

- Skill: `.claude/skills/map-skill-eval/SKILL.md`
- CLI: `src/mapify_cli/__init__.py` (`skill_eval_app`: `run` / `optimize` / `view`)
- Engine: `src/mapify_cli/skills_eval/` — `eval_schema.py`, `runner.py`, `dispatcher.py`,
  `aggregator.py`, `assertions.py`, `proposer.py`, `description_optimizer.py`, `apply_patcher.py`,
  `viewer.py`
- Fixtures: `tests/skills_eval/fixtures/` (+ `README.md` on authoring)
- Tests: `tests/test_skills_eval_*.py`
