# Trajectory-Eval — Outcome Quality & Regression Detection

> Repeatable guide for `mapify skill-eval trajectory` (issue #351, AgentLens-style).
> Scores the OUTCOME of a full agent run, not just whether the skill fired.

## What it is

`skill-eval trajectory` measures whether a full interactive MAP run **did its
job well**, across six component metrics, and compares a candidate change
against an anchor run to catch trajectory regressions that pass/fail gates
miss. It is the shipped successor to the whole-skill outcome-eval spike
(`tests/skills_eval/whole_skill/spike_runner.py`).

### How it differs from the other two eval surfaces

| Surface | What it measures | Unit | Judge? |
|---|---|---|---|
| `skill-eval run`/`optimize` | **Trigger** accuracy + description cost | one `claude -p` prompt | no |
| `skill-eval trajectory` (this) | **Outcome** quality of a full run | full trajectory bundle | yes (batched) |
| governance fixtures (#350) | **Deterministic** negative-proof on gates | gate inputs | no |

`skill-eval trajectory` is the only one that runs the whole skill body and
judges process quality with evidence-linked component metrics.

## Requirements

- The **`claude` CLI** on `$PATH` (auth via Claude.ai subscription — no API key).
- A **whole-skill fixture** directory: `manifest.json` + `repo/` (a mini-repo
  with `.map/<branch>/{task_plan,blueprint}` + `tests/`). See
  `tests/skills_eval/fixtures/whole_skill/map_task_false_success/` for a
  regression-catching example.
- Each run seeds a throwaway cwd (`.claude/` + `.map/scripts/` + fixture repo)
  and executes the full skill body — minutes per run, real quota.

## Command

```bash
mapify skill-eval trajectory <skill> --fixture PATH [options]
```

### Flags

| Flag | Meaning |
|---|---|
| `--fixture PATH` | **Required.** Whole-skill fixture dir (`manifest.json` + `repo/`). |
| `--runs N` | Repeated runs per fixture (default **3**) for variance / flaky detection. |
| `--variant good\|bad` | Seed variant. `bad` degrades the SEEDED copy (Body-Bad lever). |
| `--degrade body\|actor\|monitor` | What `bad` degrades (default `body`). |
| `--timeout S` | Per-run `claude -p` timeout (default 3600s). |
| `--judge-timeout S` | Per-run batched judge timeout (default 360s). |
| `--no-judge` | Skip the LLM judge — deterministic components only. Cheapest. |
| `--anchor PATH\|latest` | Compare candidate vs a prior run; renders side-by-side HTML. |
| `--out PATH` | Output `.jsonl` path (default `.map/eval-runs/trajectory/<skill>/<ts>.jsonl`). |
| `--resume` | Skip `run_id`s already present in the output `.jsonl`. |
| `--dry-run` | Validate fixture + print planned runs; spends nothing. |
| `--open` | Open the side-by-side HTML report after the run. |

## Component metrics

Each run is scored across six components (AgentLens-aligned). Each produces
structured **evidence lines** so a reviewer can jump from a score to the exact
trajectory artifact.

| Component | Kind | Source |
|---|---|---|
| `formal` | deterministic | scope discipline (only `allowed_files` changed, no `trap_files` touched) |
| `end_result` | deterministic | task solved (test cmd) + not cheated; `blocked` fixtures invert |
| `tool_use` | deterministic | resiliency signals (retries, guard rework) from `run_health_report` |
| `instruction_compliance` | judge | followed workflow / scope / branch constraints |
| `pitfalls` | judge | process quality (loops, false progress, missing validation) |
| `reporting_trust` | judge | final claims match logs/artifacts; no hidden failures |

- Deterministic components are scored 0/1 from artifacts + git + the test cmd.
- Judge components come from **one batched `claude -p` call** (cheaper than
  N isolated calls), normalized from a 1–5 rubric to `[0,1]`.
- `composite` = `0.5·det_avg + 0.5·judge_avg`; `hard_pass` additionally
  requires `formal` AND `end_result` to pass and `composite ≥ 0.8`.

## Repeated runs & flaky detection

A single run is noisy. The evaluation unit per fixture is the **distribution**
across `--runs`:

- `composite_median`, `composite_mean`, `composite_stddev`;
- `hard_pass_count` / `hard_pass_rate`;
- **flaky** flag when stddev exceeds the threshold OR `hard_pass` is
  inconsistent across runs (mix of pass/fail).

## Side-by-side regression report

`--anchor PATH` (or `--anchor latest`) compares the candidate distribution
against a prior run for each fixture and metric. Decision buckets:

| Decision | Meaning |
|---|---|
| `improvement` | candidate beats anchor beyond `REGRESSION_DELTA` (0.10) |
| `regression` | candidate drops beyond `REGRESSION_DELTA` |
| `tie` | within `TIE_EPSILON` (0.05) — noise band |
| `small` | real but inconclusive change between the bands |
| `no_anchor` | fixture exists only in candidate |

A component-level regression (one judge dimension drops even if composite is a
tie) is flagged separately and counts toward `n_regressions`. The HTML report
(autoescaped — candidate text is untrusted) opens from the run or via `--open`.

## Output artifacts

- `.map/eval-runs/trajectory/<skill>/<ts>.jsonl` — one line per run
  (`TrajectoryEvalRecord`, `--resume`-able by `run_id`).
- `.map/eval-runs/trajectory/<skill>/<ts>-bundles/<run_id>.json` — full
  trajectory bundle per run (git + MAP artifacts + response), so the
  side-by-side comparator can re-open evidence without the throwaway cwd.
- `<ts>.html` — side-by-side report (only with `--anchor`).

## Guardrails (issue #351)

- **Judge is never the only source of truth.** Deterministic gates remain
  first-class; `hard_pass` requires the formal gate.
- **Judge caveats are recorded** on every row: model, prompt_version, ordering,
  and the known LLM-judge biases (self-preference, positional).
- **Not nightly-by-default.** Explicit, bounded, resumable; `--dry-run` and
  `--no-judge` keep smoke-tests cheap.
- **No private transcripts.** Fixtures are sanitized mini-repos; the evaluator
  reads only `.map/` artifacts the workflow itself produced.
- **Never a model leaderboard.** Scores MAP workflow quality under controlled
  fixture scenarios.

## First shipped fixture — `map_task_false_success`

`tests/skills_eval/fixtures/whole_skill/map_task_false_success/` demonstrates
the core value: the **basic visible test passes** on a naive implementation,
but the **documented contract** requires edge-case handling (empty string,
whitespace trimming, duplicate-key rejection) the basic gate never checks. A
run can claim completion while the real contract is unmet — exactly the class
final pass/fail misses and `pitfalls` / `reporting_trust` catch. The hidden
suite (`hidden/test_kvparse_full.py`) exposes the gap deterministically.

## Repeatable workflow

```bash
# 1. Validate fixture + see planned runs (zero quota):
mapify skill-eval trajectory map-task \
  --fixture tests/skills_eval/fixtures/whole_skill/map_task_false_success --dry-run

# 2. Cheapest real signal — deterministic only, no judge:
mapify skill-eval trajectory map-task \
  --fixture tests/skills_eval/fixtures/whole_skill/map_task_false_success \
  --runs 3 --no-judge

# 3. Full signal (deterministic + batched judge), then compare to an anchor:
mapify skill-eval trajectory map-task \
  --fixture tests/skills_eval/fixtures/whole_skill/map_task_false_success \
  --runs 3 --anchor latest --open
```

## Source map

- CLI: `src/mapify_cli/__init__.py` (`skill_eval_app` → `trajectory`)
- Engine: `src/mapify_cli/skills_eval/trajectory/` — `eval_schema.py`,
  `bundle.py`, `gates.py`, `judge.py`, `dispatcher.py`, `seeding.py`,
  `runner.py`, `repeated.py`, `report.py`
- Schemas: `src/mapify_cli/schemas.py` (`TRAJECTORY_BUNDLE_SCHEMA`,
  `TRAJECTORY_EVAL_SCHEMA`)
- Fixtures: `tests/skills_eval/fixtures/whole_skill/`
- Tests: `tests/test_skills_eval_trajectory_*.py`
