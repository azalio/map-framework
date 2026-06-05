# Whole-Skill Optimization — Reusable Flow

> How to measure and improve the **body** of any MAP `/map-*` skill (its SKILL.md
> instructions/logic), not just the trigger `description:`. This is the generalized,
> repeatable procedure distilled from the `map-task` pilot. Working log + findings:
> `docs/whole-skill-optimization-notes.md`. Description-only tuning: `docs/SKILL-EVAL.md`.

## Mental model

- The shipped `mapify skill-eval optimize` tunes the trigger **description** (does the skill fire on
  the right prompt?). This flow is about **outcome quality** (does the skill DO ITS JOB well once it
  runs?).
- Method = **Approach B, human-in-the-loop**: a harness *measures* outcome quality on golden
  fixtures and reports weaknesses; **you edit the SKILL.md body** and re-measure. No autonomous
  rewrite.
- Metric = **hybrid**: deterministic gates (objective, scriptable) + an LLM judge (trace-cited, for
  subjective qualities). `QUALITY = gate_score · (0.5 + 0.5 · judge_score)`.

## Components (already built for the pilot)

- **Runner/scorer:** `tests/skills_eval/whole_skill/spike_runner.py`
  - Seeds a throwaway cwd with repo `.claude/` + `.map/scripts/` + the fixture repo, `git init -b main`.
  - Runs `claude -p "<invocation>" --output-format json` (env-isolated via dispatcher helpers:
    `MAP_INVOKED_BY`, `TG_STATE_DIR`), long timeout.
  - Scores: deterministic gates (scope fidelity via `git status`, task-pass via the fixture's test
    cmd) + one trace-cited LLM-judge dimension; `expected_outcome` (`complete`|`blocked`) selects the
    gate set and judge rubric.
  - Appends one JSON record per run to `<out>/results.jsonl`. Robust: per-run try/except, never raises.
  - `--variant bad` strips the named scope/blocker sections from the SEEDED body only (spike use:
    Body-Good vs Body-Bad differential test). Production templates are never touched.
- **Fixtures:** `tests/skills_eval/fixtures/whole_skill/<name>/` — `repo/` (a tiny git project with
  `src/`, `tests/`, and a committed `.map/<branch>/{task_plan_<branch>.md, blueprint.json}`) +
  `manifest.json`.

## Step-by-step

### 1. Build golden fixtures (the difficulty is in the GOVERNANCE TRAP, not the code)
The code task must be trivially solvable; put the difficulty in what the BODY governs (scope,
blocker handling, sequencing, reporting). Per-fixture files:
- `repo/.map/<branch>/task_plan_<branch>.md` with `### ST-001 …` headers (orchestrator regex
  `###\s+(ST-\d+)`), `repo/.map/<branch>/blueprint.json` (`subtasks[]` with `affected_files`,
  `validation_criteria`, `aag_contract`, `dependencies`), `repo/src/…`, `repo/tests/test_*.py`.
- `manifest.json`: `invocation`, `branch`, `subtask_id`, `allowed_files`, `trap_files`, `test_cmd`,
  `expected_outcome` (`complete`|`blocked`), `expected{}`.
- Recommended set (llm-council): F1 happy-path · F2 scope-trap · F3 impossible/blocker ·
  F4 retry-then-succeed · F5 five-failures-block. Keep some **held-out** (not optimized against).

> **MANDATORY for every new fixture dir** (whole-skill fixtures are real mini-repos with
> `repo/tests/test_*.py` — they break the main toolchain otherwise; already wired for
> `tests/skills_eval/fixtures/whole_skill`): pytest `--ignore` (pytest.ini addopts),
> `[tool.ruff] extend-exclude`, `[tool.pyright] exclude`, `[tool.mypy] exclude`. Verify the main
> suite still collects 0 errors and `ruff check src/ tests/` is clean.

### 2. Verify the fixture (no quota)
Seed a temp and run `python3 .map/scripts/map_orchestrator.py resume_single_subtask ST-001` +
`get_next_step` — expect `status=success`, `next_phase=RESEARCH`. Confirm the fixture test fails (or
errors) as designed. Only then spend `claude -p` quota.

### 3. Measure (each run = a real, multi-minute `claude -p` execution)
```bash
# OPS: disable the telegram-bridge plugin first (see docs/SKILL-EVAL.md §Operational notes),
# 1h timeout per run, monitor for hangs, re-enable telegram when done.
python3 tests/skills_eval/whole_skill/spike_runner.py \
  --fixture tests/skills_eval/fixtures/whole_skill/<name> \
  --variant good --runs 3 --out .map/eval-runs/whole-skill/<skill>/<tag> \
  --timeout 1800 --judge-timeout 300
```
Aggregate per fixture: **median** QUALITY across runs (not mean); track hard-pass `k/n`; headline =
**worst-fixture median**.

### 4. Validate the metric can discriminate BEFORE trusting it (Body-Good vs Body-Bad)
Run `--variant good` and `--variant bad` (bad = body with the relevant rules stripped) on a fixture
designed to exercise those rules. The metric is trustworthy for that behavior only if
`median(good) − median(bad) ≥ 0.15`, driven by the right signal. **If the gap is ~0, the body is NOT
the lever for that behavior on that fixture** (the shared agents/orchestrator dominate, or the trap
is too weak) — fix the fixture or conclude body-only optimization won't move it.

### 5. Optimize (only where the current body measurably underperforms)
1. Baseline the CURRENT body across fixtures; find the **lowest-scoring** one.
2. Make **ONE conceptual body edit** targeting that weakness (edit the `.jinja` source
   `src/mapify_cli/templates_src/skills/<skill>/SKILL.md.jinja`, then `make render-templates`; or
   iterate faster with a candidate body file and only render once a winner is found).
3. **3-run spot-check** on the targeted fixture; revert if it doesn't improve.
4. Full regression: reject the edit if ANY fixture's median QUALITY drops > 0.10.
5. Held-out check every ~3 iterations (overfit alarm if held-out drops > 0.15). Tag accepted body
   versions; save per-fixture score JSON + a one-line hypothesis.

## Generalizing to other skills
- The runner is skill-agnostic (manifest-driven `invocation`); point it at a new skill's fixtures.
- `--variant bad` section names are pilot-specific; for the generalized harness, parameterize the
  stripped sections per skill (or drop the bad-variant once a skill's metric is validated).
- Skills whose output is prose (e.g. `map-explain`, `map-review`) are judge-heavy (few deterministic
  gates); workflow skills (`map-task`, `map-efficient`) are gate-rich. Choose gates/rubric per skill.

## Findings & leverage (filled from the pilot)

From the `map-task` pilot (2 fixtures, 12 runs, + 2 llm-council consults):

- **Generic policy PROSE in a thin-orchestration body is low-leverage.** Deleting the scope-discipline
  and blocker-handling sections changed NOTHING (Body-Good == Body-Bad == QUALITY 1.0 on both the
  scope-trap and the impossible/blocker fixtures). Those behaviors are enforced by the shared
  `actor`/`monitor` agents + base model, not the body.
- **Where the body IS the lever (test these, not scope/blocker prose):** state-machine
  sequencing/loop-exit, **context relay** between phases, **retry/termination** governance, and the
  **final report schema**. A fixture is body-sensitive only if correct behavior needs a global
  decision no single sub-agent has locally. Use targeted Body-BAD degradations (remove the specific
  mechanism), a NO-BODY ablation (raw-actor passes ⇒ fixture is body-insensitive, discard it), and
  ≥5 runs.
- **Honest deliverable when constrained to body-only:** harden the body-owned interfaces (report
  schema, retry/exit, context relay) and/or a regression-proved cleanup (fix dead refs, placeholders,
  formalize reporting). Do NOT claim coding-quality gains without a body-sensitive benchmark.
- **To move the big outcomes (scope/correctness) you must widen scope to the shared agent prompts**
  (`.claude/agents/{actor,monitor,research-agent}.md`) — that's the real lever; revisit the
  "body-only" constraint with the user for those.
