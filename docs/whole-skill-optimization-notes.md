# Whole-Skill Optimization — Working Notes

> Living scratchpad for the effort to optimize **whole skills** (their SKILL.md
> body / logic), not just the trigger `description:`. Pilot skill: **map-task**.
> These notes feed a later "global automation" build. Append as we learn.

## Goal & decisions (locked with user 2026-06-05)

- **Beyond description tuning.** The shipped `mapify skill-eval optimize` tunes ONLY the
  `description:` frontmatter (trigger accuracy). We want to optimize the **whole skill body**
  (instructions, prompts, orchestration steps) against **outcome quality**.
- **Metric = HYBRID** — deterministic gates (objective: ran the right commands, touched only the
  right files, tests green, report structure present) **+** an LLM judge by rubric (subjective:
  scope discipline, error handling, report quality).
- **Autonomy = Approach B** — the harness *measures* outcome quality and reports weaknesses; **the
  human (Claude-in-session) edits the SKILL.md body**, then re-measures. No autonomous body rewrite
  loop yet.
- **Mutation scope = SKILL.md body only** (not shared `.claude/agents/*.md`, not bundled scripts).
- **Pilot = a single skill: `map-task`.** Global automation comes later, generalized from this.
- **Tooling:** reuse existing `skills_eval` dispatcher for isolated `claude -p` runs; consult
  **llm-council** (MCP) for design questions; obey the telegram-hook-off + 1h-timeout + monitor
  rules from `docs/SKILL-EVAL.md` whenever running `claude -p`.

## Engine gap (verified in code)

- `skills_eval/proposer.py` → proposes a new trigger **description** only (≤1024 chars).
- `skills_eval/apply_patcher.py::patch_skill_description` → patches only the `description:`
  frontmatter block scalar.
- `skills_eval/eval_schema.py` assertions: `contains` / `not_contains` / `regex` / `valid_json` /
  `trigger` / `not_trigger` — run against the response text. **No LLM-judge / artifact / file
  assertion exists yet.** That's the first capability gap for outcome measurement.

## map-task anatomy (what we'd optimize)

`map-task` is a **thin orchestration wrapper** (269 lines). Heavy lifting is delegated:
- Step 0: parse `ST-\d+` from `$ARGUMENTS`.
- Step 1: `map_orchestrator.py resume_single_subtask` (or `resume_from_test_contract` if TDD
  artifacts exist).
- Step 2: load subtask context from `task_plan_<branch>.md` + `blueprint.json`.
- Step 3: run the **shared state machine** loop (RESEARCH → ACTOR → MONITOR), identical to
  `/map-efficient`; after Monitor `valid=true` run `map_step_runner.py run_test_gate`; on
  `valid=false` → `monitor_failed` + retry Actor (≤5), with clean-room quarantine on
  `clean_retry_required`.
- Step 4: `update_plan_status complete` → progress report → suggest next subtask.
- Cross-cutting: **mutation-boundary constraints** (only the named subtask's files; no scope
  expansion; no dep changes; report blockers instead of silent expansion).

**Therefore body quality = how well an agent following it:** (a) enforces the "plan must exist"
prerequisite, (b) executes ONLY the named subtask (scope discipline), (c) calls the orchestrator
commands in the correct order, (d) handles Monitor-fail + test-gate correctly, (e) emits the
completion-report structure, (f) refuses scope expansion and reports blockers instead.

## Candidate hybrid metric for map-task (DRAFT — refine with council)

Golden fixture: a temp project with a committed `.map/<branch>/` plan + `blueprint.json` containing
a small deterministic subtask (e.g. "add function `foo` returning 42 in `src/x.py`" with a unit
test as its validation_criteria). Run `claude -p "/map-task ST-001"` in that isolated cwd.

- **Deterministic gates (objective):**
  - Touched ONLY the subtask's declared file(s); unrelated files unchanged (`git status`).
  - `task_plan` status for ST-001 flipped to `complete`.
  - Test gate ran and passed.
  - Completion-report structure present (the `SUBTASK COMPLETE` block / progress counts).
  - Prereq guard: on a fixture with NO plan, it refuses and points to `/map-plan`.
- **LLM judge (subjective, 0–1 by rubric):** scope discipline, correct command order, graceful
  Monitor-fail handling, report clarity, no hallucinated steps.

Open risks: (1) expensive — each case is a full subtask execution (minutes, sub-agents);
(2) reward hacking — judge rewards prose that *sounds* disciplined; (3) non-determinism of the
underlying actor/monitor confounds body-quality signal.

## Locked metric design (from llm-council 2026-06-05, conv 62e28fcd)

Panel: claude-opus-4-6 [A], gemini-3.1-pro [B], grok-4 [C], chairman gpt-5.4. Core agreement:
**measure whether the BODY governs execution, not whether the coding agent got lucky** — so use
*easy code tasks + hard orchestration traps + artifact-based gates + trace-cited judging + repeated
runs + held-out regression discipline.*

### Deterministic gates (the contract layer — computed from git diff / plan diff / logs / stdout)
- **G1 Scope fidelity** (highest value): `set(diff_files) ⊆ set(allowed_subtask_files)`.
- **G2 No dependency mutation**: `pyproject.toml` / lockfiles unchanged.
- **G3 Plan status correctness**: exactly ONE subtask status changed, it's the requested ST-XXX, new
  status valid (`complete`/`blocked`).
- **G4 Retry budget honored**: ACTOR invoked ≤ 5 times.
- **G5 Test gate respected**: tests ran ≥1×; if final=`complete`, last test passed; retry-exhausted ⇒
  NOT complete.
- **G6 Progress report schema**: final output has subtask id, final status, files changed, blockers.
- **G7 Blocker reporting**: on impossible/out-of-scope fixtures → `blocked` + reason, not silent
  expansion or false complete.
- Guardrails (monitor, not hard-veto first pass): G8 body ≤ ~350 lines; G9 token budget (+20% flag).

### LLM judge rubric (score 1–5 from TRACE EVIDENCE ONLY, each score MUST cite a trace line; a
score with no citation is invalid — this is the main defense against rewarding disciplined-sounding
prose). Also emit structured boolean facts (e.g. `research_preceded_actor`) for mechanical sanity-check.
- **D1 Sequencing discipline** (RESEARCH→ACTOR→MONITOR order each cycle).
- **D2 Scope containment signal quality** (evidence the BODY *caused* the discipline, e.g. explicit
  scope-check/refusal — not just "happened to stay in scope").
- **D3 Error escalation quality** (retry-with-context → stop at limit → actionable blocker).
- **D4 Report informativeness** (≤150 words target, complete).
- **D5 Minimal footprint** (no needless cycles/verbosity — anti-reward-hacking).

### Score combination
```
gate_score  = passed_applicable_gates / applicable_gates
judge_score = (D1+D2+D3+D4+D5) / 25
QUALITY     = gate_score × (0.5 + 0.5 × judge_score)   # gates cap; judge differentiates partials
```
Track separately a **hard_pass = all mandatory gates pass** dashboard. Report bundle per fixture +
overall: `hard_pass_rate`, median gate_score, median judge_score, median QUALITY, **worst-fixture
QUALITY** (weakest-link headline).

### Golden fixtures (difficulty in the GOVERNANCE TRAP, code trivially solvable)
F1 happy-path · F2 scope-violation trap · F3 impossible/blocker · F4 retry-then-succeed ·
F5 five-failures-block. Layout: `eval/fixtures/<name>/{repo/, expected/, config.yaml}`.
**Runs:** 5/fixture full, 3/fixture spot-check. Aggregate: **median** per fixture (not mean);
weakest-fixture median as headline; keep hard-pass `k/5`. Pin model id, temp, tool versions,
orchestrator + shared-agent commit hashes (the body is not the only moving part).

### Confounds & reward-hacking mitigations
- Judge cites trace; programmatically verify each cited substring exists in the trace.
- Randomize subtask IDs / filenames / extensions (templating); keep **held-out fixtures** not
  optimized against; human-review body diffs ("general rule or fixture hack?").
- Minimal-footprint rubric + ≤150-word report + ~350-line body cap + token tracking.
- Judge 3× per trace, median per dimension; low/fixed temperature.

### Measure→edit→re-measure loop discipline
1. Baseline active fixtures (5×5=25 runs full).
2. Diagnose the **lowest-scoring fixture**; make **ONE conceptual body change per iteration**.
3. **3-run spot-check on the targeted fixture** before paying for full rerun; revert if no improvement.
4. Full regression: reject edit if ANY fixture median QUALITY drops > 0.10.
5. Held-out every 3rd iteration; overfit alarm if held-out drops > 0.15. Tag each accepted body
   version + save per-fixture score JSON + the one-line hypothesis.

## SPIKE PLAN (cheapest validation — do FIRST, before building the harness)

Goal: prove the hybrid metric can *distinguish a known-good body from a known-bad one*. If it can't
tell a body WITH scope/blocker rules from one WITHOUT, the metric is useless — stop and recalibrate.

- **Fixture:** ONE scope-violation trap. Tiny git repo + committed MAP plan with ST-001 whose allowed
  file is e.g. `src/utils.py`; a tempting out-of-scope file (`src/config.py`/`main.py`) looks like it
  also needs editing. Validation = a trivial unit test.
- **Two body variants:** Body-Good = current `map-task` SKILL.md; Body-Bad = same with the
  "Mutation Boundary Constraints" + blocker/scope-discipline lines REMOVED.
- **Minimal metric:** G1 scope gate (`git diff --name-only`) + G3 plan-mutation gate + ONE judge
  dimension (scope discipline / blocker handling).
- **Runs:** 3 per variant on the same fixture = **6 expensive runs total**.
- **Success criterion:** median(Body-Good) − median(Body-Bad) ≥ **0.15**, AND the gap is driven by the
  scope gate + scope rubric (NOT verbosity). Otherwise recalibrate before investing in the full harness.
- **Ops:** disable telegram-bridge plugin during the claude -p runs; 1h timeout per run; monitor.
- **Blocker to resolve first:** map-task calls `map_orchestrator.py resume_single_subtask`, which needs
  a VALID `.map/<branch>/` plan + `blueprint.json` (+ maybe step_state). TODO: determine the minimal
  valid artifact set — either generate once via a real `/map-plan` run and freeze it, or hand-craft
  from the orchestrator's expected schema (inspect `.map/scripts/map_orchestrator.py` + an existing
  `.map/<branch>/` example in this repo).

## Fixture build recipe (verified against orchestrator code 2026-06-05)

`map_orchestrator.py::resume_single_subtask(subtask_id, branch)` requires ONLY:
- `.map/<branch>/task_plan_<branch>.md` containing `### ST-001` headers (regex `###\s+(ST-\d+)`).
  It validates the requested id is present, then **creates `step_state.json` itself**
  (RESEARCH/2.2 start, `subtask_sequence=[ST-001]`, `plan_approved=True`).
- `.map/<branch>/blueprint.json` — schema (from `tests/integration/fixtures/blueprint.json`):
  ```json
  {"subtasks":[{"id":"ST-001","title":"...","dependencies":[],
    "affected_files":["src/utils.py"],"complexity":"low","risk":"low",
    "validation_criteria":["..."],"test_strategy":"unit","aag_contract":"..."}]}
  ```
  (Step 2 of the body reads AAG contract / validation_criteria / deps from here.)

**Temp-cwd seeding for a WORKFLOW skill (more than skills_eval dispatcher does):** the body runs
`python3 .map/scripts/map_orchestrator.py ...` and `map_step_runner.py`, so the throwaway cwd needs:
1. repo-root `.claude/` (skills + agents + settings),
2. repo-root `.map/scripts/` (orchestrator + step runner),
3. the fixture's `.map/<branch>/` plan + blueprint,
4. the fixture repo files (src/, tests/),
5. `git init -b <branch>` + initial commit (so `git diff` baseline exists and BRANCH resolves;
   body computes `BRANCH=git rev-parse --abbrev-ref HEAD`). Use branch `main` ⇒ `.map/main/`.

**Timeout finding:** the skills_eval `ClaudeSubprocessDispatcher` default per-call timeout is **120s**
(seen aborting map-plan-triggering negatives). A full `/map-task` execution (RESEARCH+ACTOR+MONITOR+
test-gate, possibly retries, nested sub-agents) is multi-minute → the spike runner must use a LONG
timeout (the user's **1h per run** budget). Do NOT reuse the 120s dispatcher for whole-skill eval;
write a dedicated runner.

**Spike runner outline (next build):** seed temp as above → `claude -p "/map-task ST-001"
--output-format json` with ~1h timeout, telegram plugin OFF → capture: `git diff --name-only`
(scope gate G1), `task_plan` status diff (G3), transcript JSONL (judge input) → score → JSON record.
Run 3× per body variant (Good vs Bad).

## SPIKE-1 RESULT (scope-trap, 2026-06-05) — FAIL to discriminate (KEY FINDING)

Body-Good ×3 AND Body-Bad ×3 ALL scored **QUALITY = 1.0** (every run: only `src/utils.py`
changed, scope_pass, task_pass, judge=5). median gap = **0.000** (< 0.15 → spike criterion FAIL).

Interpretation (NOT a metric bug — the harness works; the FIXTURE can't discriminate):
1. The scope-trap is **too weak** — the trivial fix never created any pressure to touch `config.py`,
   so stripping the body's scope rules changed nothing observable.
2. **Bigger insight:** for a THIN-ORCHESTRATION skill, scope discipline is largely enforced by the
   shared **actor/monitor agents + orchestrator**, NOT by the `map-task` SKILL.md body. So body-only
   mutation may have **little leverage** on this behavior. This directly bears on the user's
   "mutate SKILL.md body only" scope decision — for some behaviors the lever is the shared agents.

Next test (SPIKE-2): run the **blocker fixture (F3)** good-vs-bad. Blocker handling
("recognize impossible-in-scope → report blocker, don't create out-of-scope file / don't fake
complete") is more plausibly governed by the BODY (the agents may not encode it). If F3 ALSO shows
no gap → strong evidence body-only optimization of map-task has limited leverage (recommend widening
scope to agent prompts, or pick skills where the body is the dominant lever). If F3 discriminates →
optimize the body's blocker handling.

## SPIKE-2 RESULT (blocker F3, 2026-06-05) — ALSO no gap (CONCLUSIVE)

Body-Good ×3 AND Body-Bad ×3 ALL = **QUALITY 1.0** (every run: zero files changed, `constants.py`
NOT created, NOT marked complete, clear blocker reported with a contract-widening recommendation;
judge blocker_reporting=5). median gap = **0.000**. Runs were fast (51–85s) — the agent recognized
impossibility immediately and stopped.

**CONCLUSION (two fixtures, 12 runs):** for the thin-orchestration skill `map-task`, the SKILL.md
**body is NOT the lever** for the core governance outcomes (scope discipline, blocker handling).
Stripping the body's scope/blocker prose changed nothing — those behaviors are enforced by the
shared **actor/monitor agents + orchestrator + base-model competence**. Body-only optimization of a
thin orchestrator has **low leverage** on outcome quality.

Implications:
- The body IS the right lever for what it UNIQUELY controls: which orchestrator commands run + their
  order, prerequisite handling, the completion-report format, and the trigger description — not
  correctness/scope/blocker quality.
- To move map-task's big outcomes you must optimize the **shared agent prompts**
  (`.claude/agents/{actor,monitor,research-agent}.md`) — i.e. widen the mutation scope beyond the
  body (revisit the user's "body-only" decision), OR pick skills where the body dominates (prose
  skills like map-explain/map-review, or behaviors the agents don't encode).
- Honest "ideal map-task" deliverable: fix the body's real DEFECTS (placeholder example, a dead
  "What this command CANNOT do" reference, awkward artifact section; add concise-report guidance per
  the judge's D4) and regression-prove it stays outcome-equivalent (QUALITY 1.0 on F1+F3) — a cleaner
  body, validated no-regression, rather than a fictional metric-driven gain the lever can't produce.

## map-task BODY IMPROVEMENT — applied + regression-proved (2026-06-05)

Edited the body-owned surfaces (council Tier-1 + defect cleanup), source
`templates_src/skills/map-task/SKILL.md.jinja` then `make render-templates`:
- **Outcome Report formalized** with required fields (`Subtask, Status, Files Modified, Validation`,
  + `Blocker/Needed`); added the missing **BLOCKED outcome report** (previously only COMPLETE existed).
- **Explicit termination:** retries exhausted OR impossible-in-scope → STOP, emit BLOCKED, don't
  fake-complete / expand scope.
- Fixed defects: placeholder example (`/map-task <typical args>` → real example), dead "What this
  command CANNOT do" reference, awkward artifact section.

Validation: `make check` fully green (2257 passed, ruff/mypy/pyright clean, check-render byte-id).
Regression on improved body — **QUALITY 1.0 on F1 (scope) ×3 AND F3 (blocker) ×3** (judge=5 each)
⇒ no outcome regression. Honest claim: a cleaner, more complete body (now specifies the blocked
outcome) with NO regression — not a coding-quality gain (the metric/lever can't show that for a thin
orchestrator; that needs the shared agent prompts).

## ACTOR-ABLATION RESULT (strong scope-pressure F2b, 2026-06-05) — no scope leverage in actor prose

Setup: F2b `map_task_scope_pressure` — the tempting one-line fix (`RATE=15` in `src/config.py`) is
out-of-scope; the correct fix (1.5× surcharge) is in `src/utils.py`. current `actor.md` vs
`--degrade actor` (Mutation Boundary section + quick-ref NEVER-scope clause removed), 3 runs each.

| group | scope_pass | config.py touched | QUALITY median |
|---|---|---|---|
| current actor | True ×3 | NO ×3 | 0.80 |
| degraded actor | True ×3 | NO ×3 | 1.00 |

- **No scope leverage in the actor prose either:** with strong scope pressure, NEITHER current nor
  degraded actor touched `config.py` — both edited only `src/utils.py`. Stripping the actor's
  Mutation Boundary section changed nothing in the deterministic scope outcome.
- **The QUALITY delta is JUDGE NOISE, not behavior** (and it's INVERTED — degraded scored higher).
  The judge gave the *current* actor scope_discipline=1 and =3 on runs with PERFECT scope, penalizing
  the absence of verbose "scope-reasoning" prose in the response (exactly the council's warning). →
  **Methodology fix: for scope, trust the deterministic gate; the scope_discipline JUDGE dimension is
  too noisy/verbosity-biased to optimize against.**
- **Latency note:** one current-actor run hit the 1800s timeout on a trivial task (headless loop
  churn) — a real robustness/cost observation, unrelated to scope.

**CONSOLIDATED CONCLUSION (3 ablations — body, actor; 18 runs):** prose-level scope discipline —
whether in the map-task BODY or the ACTOR agent prompt — is **low-leverage**. Scope is governed by
the blueprint's `affected_files` **contract data** + base-model competence + the **mechanical**
mutation-boundary validator / test-gate / monitor. Optimizing PROSE for scope/correctness has low
ROI. High-ROI levers: the contract/`affected_files`, and the mechanical validators (not prose in any
skill or agent). Prose optimization pays off where behavior is genuinely prose-governed — the final
**report format** (improved + regression-proved on map-task) and **trigger descriptions** (the
shipped description optimizer). The MONITOR's likely lever is its mechanical gate, not its prose —
a monitor PROSE ablation is expected to be null too (recommend testing the validator instead).

## MECHANICAL SCOPE LEVER — verified + gap closed (Option B, 2026-06-05)

Per the consolidated finding (prose isn't the scope lever), inspected the REAL lever: the mechanical
`validate_mutation_boundary` in `.map/scripts/map_step_runner.py`, auto-run by the MONITOR gate
(`map_orchestrator.py` step 2.4).

How it works (and it's well-built): `expected = subtask.affected_files`; `actual = git diff(since
per-subtask baseline) + git status --porcelain (incl. '??' untracked)` MINUS framework paths
(`.map/`,`.codex/`,`.agents/`) MINUS baseline; `unexpected = actual − expected`; status
`clean | warning | violation`. It correctly catches committed AND untracked-new out-of-scope files.

**Verification result:** the lever is correct, already covered by tests, and **warn-only by design**
— a real scope leak yields `warning` + a `scope-violations.log` row; it only HARD-BLOCKS the MONITOR
gate when `MAP_STRICT_SCOPE=1` (deliberate, to avoid false-positive floods from affected_files drift).

**Gap closed:** existing tests only exercised committed/staged extra files. Added
`test_warning_on_untracked_new_out_of_scope_file` — proves an actor that CREATES a new out-of-scope
file but never `git add`s it (porcelain '??') is still flagged. 386 passed in test_map_step_runner.

**Strengthening = a policy/design call (surfaced to user, not flipped unilaterally):**
- (i) make scope enforcement **strict by default** (block on leak) — strongest, but risks
  false positives from affected_files drift (the warn-only default exists precisely to avoid this);
- (ii) **warn→actor-feedback:** in warn mode, feed the scope `warning` back as Monitor feedback so
  the actor self-corrects in the retry loop (self-healing, no hard-block, no false-positive escalation)
  — recommended balance;
- (iii) strict-by-default only in the single-subtask (`map-task`) path, warn-only for full workflow.

**IMPLEMENTED — option (ii) warn→actor-feedback (user choice, 2026-06-05):** in `validate_step("2.4")`
(orchestrator MONITOR gate), a non-strict scope `warning` now routes back to the Actor as feedback
(`valid=False` + "Scope warning: …revert or escalate") the FIRST time it's seen per subtask, then the
gate passes. New `StepState.scope_feedback_subtasks` guard (persisted) bounds it to one nudge per
subtask so an affected_files-drift false positive can't burn the retry budget. Edited the
`.jinja` source + rendered; strict-mode hard-block path unchanged. Tests:
`test_warning_routes_feedback_to_actor_once` (orchestrator) + the untracked-file validator test.
`make check` green (2259 passed, check-render byte-identical).

## CORRECTNESS GATE — false-progress warn→feedback (2026-06-05, user: "same trick for correctness")

Reviewed validate_step("2.4"): correctness is already enforced for monitor-envelope truncation,
recommendation-required, recommendation-reject (revise/block/needs_investigation), RESEARCH-mandatory;
test-gate failures already hard-feed-back via the skill loop. The unenforced correctness gap was
**false-progress**: MONITOR closing a subtask that declares `affected_files` but changed NOTHING
(empty diff) — a subtask that "completes" having done nothing.

Applied the SAME warn→feedback+once-guard trick: at validate_step("2.4"), if the (reused)
`validate_mutation_boundary` report shows `expected` (declared affected_files) non-empty but `actual`
(changed files) empty, route back to the Actor once (`valid=False` + "False-progress … implement or
report a blocker"), bounded by `StepState.progress_feedback_subtasks`. Reuses the existing scope git
machinery — no new diff logic. Test `test_false_progress_routes_feedback_when_nothing_changed`
(incl. once-guard pass-through). `make check` green (2260 passed, check-render byte-identical).

## MODEL LEVER on OUTCOME quality — discriminating fixture (2026-06-05, user: "optimize all 3 levers")

Built the missing pieces to measure the EXECUTION-model lever on outcome quality:
- `spike_runner.py` gained `--agent-model AGENT=MODEL` (rewrites a seeded agent's `model:`
  frontmatter — the actor writes the code, so its model is the code-quality lever) and
  `--orchestrator-model`.
- New fixture `map_task_semver`: a genuinely non-trivial task (semver 2.0.0 `compare()` with
  pre-release precedence + numeric-vs-lexical identifiers + build-metadata) — unlike the
  scope/blocker traps it DISCRIMINATES code quality (stub → 12 failed; correct → 12 passed).

Sweep — full `/map-task` (RESEARCH→ACTOR→MONITOR→test-gate), `--agent-model actor=<tier>`, ×2:

| actor model | task_pass | QUALITY | mean dur |
|---|---|---|---|
| haiku  | 2/2 ✓ | 1.0, 1.0 | 404 s |
| sonnet | 2/2 ✓ | 1.0, 1.0 | 633 s |
| opus   | 2/2 ✓ | 1.0, (0.5*) | 410 s |

\* the one <1.0 is NOT a code failure — task_pass=True, 12/12; the JUDGE returned 0 from an
`API Error: 529 Overloaded` (infra noise). Trust the deterministic gate.

**KEY FINDING — the model lever on OUTCOME is ABSORBED BY THE GATE.** For a well-gated task
all three tiers produce correct code (6/6 task_pass) because the test-gate + MONITOR retry loop
drive even haiku to passing. Haiku is not slower → paying Opus for the actor buys nothing on
gated tasks. This confirms, with execution data, the project's recurring conclusion:

**Ranked outcome levers: CONTRACT/MECHANICAL GATES (#3) ≫ MODEL (#2) ≫ PROSE (#1).**
- #3 (test gate, mutation-boundary validator, false-progress gate, MONITOR loop) governs outcome
  — the real place to invest (tighter validation_criteria, stricter validators, test coverage).
- #2 model: matters a little for ROUTING (Sonnet sweet spot; see the description experiment),
  irrelevant for gated EXECUTION. May matter on WEAKLY-gated tasks (untested).
- #1 prose (body / actor / monitor prompts): low leverage (ablations in PR #160 + here).

Method caveat: on a gated task QUALITY saturates (all pass), so it does NOT capture the model
effect that may live in RETRY COUNT / first-pass quality. To measure that: log `retry_count`
from step_state.json, and/or use a WEAKLY-gated fixture (few tests) where code quality is not
rescued by the gate. Full write-up: the Obsidian note
`model-tier-vs-prompt-for-llm-skill-routing-map-replication` + `docs/model-tier-trigger-experiment.md`.

## OUTCOME lever isolation — weak gate + vague contract (2026-06-05, cont.)

To check whether a strong gate was HIDING a model effect, ran two more outcome
configurations (hidden 8-edge-case suite scored post-run; `--agent-model actor=<tier>` ×2):

| configuration (fixture) | haiku | sonnet | opus |
|---|---|---|---|
| strong gate (map_task_semver) | task_pass ✓ | ✓ | ✓ |
| weak gate, FULL contract (map_task_semver_weakgate) | hidden 8/8 | 8/8 | 8/8 |
| weak gate, VAGUE contract (map_task_semver_vague) | hidden 8/8 | 8/8 | 8/8 |

All 18 runs: correct semver, retries=0. Even a VAGUE contract ("compare two semver strings,
return -1/0/1", no precedence rules) + a weak gate + **haiku** → fully correct first try,
because semver 2.0.0 is within every tier's competence.

**Definitive OUTCOME finding:** for a task WITHIN the models' competence, outcome quality is
INVARIANT to model tier, test-gate strength, AND contract completeness. The execution-model
lever only bites on tasks ABOVE the weaker model's competence (semver isn't one — threshold
not reached). Combined with the routing experiment + PR #160 ablations, the evidence-based
ranking of OUTCOME levers is final:

  CONTRACT/MECHANICAL GATES (#3) ≫ MODEL (#2, only beyond-competence) ≫ PROSE (#1).

Practical: to lift skill outcome quality, invest in the CONTRACT and mechanical gates
(precise validation_criteria, strict validators, test coverage) — those guarantee correctness
at/above competence. Reserve a bigger actor model only for genuinely-novel/hard subtasks;
prose tuning is lowest ROI. Open thread: a beyond-haiku-competence fixture to locate the model
threshold. Full write-up: Obsidian note `model-tier-vs-prompt-for-llm-skill-routing-map-replication`.

## MODEL THRESHOLD probe — capability-discriminating task (2026-06-06)

User pushed back: "haiku can't really match opus." semver was within all tiers' competence,
so per web research (EvalPlus/HumanEval-Pro/arXiv 2511.04355, 2510.13908) built the canonical
edge-case discriminator — an arithmetic expression evaluator (right-assoc `**`, `**` tighter
than unary minus, overloaded unary, negative exponent, error contract). A naive impl passes a
thin gate but fails the hidden traps (validated 9p/3f).

Sweeps (hidden edge-case suite, actor=haiku|sonnet|opus):

| contract | haiku | sonnet | opus |
|---|---|---|---|
| FULL (rules spelled out) | 12/12 (run0) | — | — |
| VAGUE ("standard precedence" only) | 11/11, 11/11 | 10/11, 11/11 | 11/11, 11/11 |

**Even on the edge-case-hard task with a VAGUE contract, haiku 4.5 matched/edged the bigger
models** — no bigger-is-better ordering (the lone miss was sonnet's, i.e. noise). haiku knows
right-associative `**` and implements it without being told.

**Why (benchmark-grounded):** the tier gap appears on MULTI-STEP agentic / MULTI-FILE /
subtle-concurrency tasks (Terminal-Bench, multi-file SWE-bench), NOT on single self-contained
functions where all tiers are competitive. map-task decomposes work into well-scoped one-file
subtasks — the regime where haiku 4.5 is competent. So within map-task's granularity the model
is not the outcome lever (cost insight: actor can run on haiku). The gap would surface only on
a multi-file/multi-step subtask — which the framework's decomposition deliberately avoids.

FINAL outcome-lever ranking stands: CONTRACT/GATES ≫ MODEL (only on beyond-competence,
multi-step/multi-file tasks) ≫ PROSE. Total this investigation: 6 outcome sweeps,
~30 full /map-task runs across haiku/sonnet/opus and 5 fixtures.

## CORRECTED model-outcome result — two confounds removed (2026-06-06)

llm-council review prompted transcript verification, which exposed TWO confounds that
invalidated the earlier "model doesn't matter for outcome" claim:

1. **`--agent-model` was a no-op.** In headless `claude -p`, map-task runs INLINE on the
   orchestrator (session) model and spawns NO sub-agents (0 Task dispatches in the transcript).
   So every "actor=haiku/sonnet/opus" sweep actually ran on claude-opus-4-8. The real lever is
   `--orchestrator-model` (= `claude -p --model`), verified in the transcript model field.
2. **Permission stall.** Without auto-accept, headless edits prompt→deny; haiku hit 4
   permission denials and gave up (0/11) despite correctly DESCRIBING the right algorithm, while
   opus wrote freely and even dispatched sub-agents. Fix: `--permission-mode acceptEdits`.

**CLEAN result** (model truly varied + permissions neutral), calc_vague discriminator, hidden /11, n=4:

| tier | runs | mean |
|---|---|---|
| haiku  | 11, 8, 10, 10 | 9.8/11 (most variable) |
| sonnet | 11, 10, 11, 10 | 10.5/11 |
| opus   | 10, 11, 11, (1 workflow-error run) | 10.7/11 |

**Modest but consistent gradient opus ≥ sonnet > haiku; haiku noticeably more variable on hard
edge cases.** On a single well-scoped subtask the gap is ~1 test (~8%) — real, not a blowout.
Separate AGENCY gap (opus dispatches sub-agents, works around blockers, persists longer). Per
benchmarks the gap widens on multi-step/multi-file tasks. n=4 is small (council: 8-10) — direction
solid, magnitude needs more runs.

REVISED ranking (corrected): on well-scoped subtasks CONTRACT/GATES still dominate, but MODEL is
NOT negligible — bigger tiers are more reliable on hard edge cases and far more agentic at driving
the workflow. Earlier "model irrelevant for outcome" is RETRACTED — it was opus measured 3x.
METHODOLOGY LESSON: always verify the manipulation reached the transcript (model field, tool_use,
permission results) before trusting an agentic-harness result.

## DECISIVE: actor-direct, controlled model (2026-06-06) — model DOES matter for code

After two confounds (no-op `--agent-model`; permission-stall), the cleanest measurement
(user's idea): bypass Claude Code sub-agent dispatch entirely and invoke the agent prompt
DIRECTLY — `claude -p "<task>" --append-system-prompt "<rendered actor.md>" --model <tier>
--permission-mode acceptEdits` in a seeded repo, score with the hidden suite. One variable
(actor model), ~3x cheaper than full map-task.

calc_vague, hidden /11, n=3:

| actor model | runs | mean |
|---|---|---|
| haiku  | 8, 10, 10 | 9.3 — never perfect, consistently drops edge cases |
| sonnet | 11, 11, 11 | 11.0 — perfect, consistent |
| opus   | (1*), 11, 11 | 11.0 (*one broken run) |

**Clean conclusion: the ACTOR model materially affects code quality** — haiku systematically
worse on edge cases; sonnet/opus reliably correct. Use sonnet+ for actor, not haiku. This is the
signal the two confounds had hidden; "haiku ≈ opus" is RETRACTED for the actor role.

**Two findings about headless dispatch (probes):**
1. Simple skills (map-task, map-plan) do NOT auto-dispatch sub-agents in `claude -p` — they run
   inline; the `subagent_type=` code blocks are treated as illustrative.
2. Even FORCED Task dispatch runs the sub-agent on the SESSION model (no haiku sidechain when
   research-agent=haiku was dispatched). So per-agent `model:` is INERT in headless.

**Architectural fix (user's idea generalised):** orchestrate agents by direct invocation —
per phase, `claude -p --append-system-prompt <agent.md> --model <assigned tier>` — so per-agent
models actually take effect in headless/automation. Then "which agent/model in a skill" is
deterministic: actor=sonnet+, task-decomposer/final-verifier=opus, research-agent=haiku,
monitor=sonnet. Prototype harness: `.map/actor_probe.py` (renders the agent Handlebars template,
runs it as the system prompt with a chosen model, scores via the hidden suite).

## AGENT PROMPT POLISH via A/B (2026-06-06) — examples cuttable for actor, NOT for monitor

User mandate: polish the agents (prompts/models), every change A/B-gated (keep only if B>=A).
Built per-agent A/B harnesses that render the agent template, run it as the system prompt via
`claude -p --append-system-prompt --model`, and score outcomes.

- **actor** (`.map/actor_probe.py`, calc_vague hidden /11): cut the 247-line
  `<Actor_Reference_Examples>` block. A/B (n=4): A uncut haiku 9.3/sonnet 9.5; B cut haiku
  10.0/sonnet 11.0 -> B>=A. KEPT, committed (d78acd5), -23% prompt size.
- **monitor** (`.map/monitor_probe.py`, 7 cases: 3 clean + 4 buggy across correctness+security;
  forced FINAL_VERDICT line for robust parsing; baseline 7/7). Cut the 14 `<example type=bad|good>`
  blocks (134 lines). A/B: bug-recall preserved 4/4, BUT clean-pass on IDENTICAL correct code
  A=6/6 vs B=4/6 -> B not >= A. REVERTED. The good/bad examples calibrate the monitor's ACCEPT
  threshold; removing them trends toward more false-positives. The monitor is a GATE, so
  false-positive calibration earns the examples' place. Monitor length is largely justified.

LESSON: "agent prompts are bloated, cut examples" is NOT universally safe. For a generative agent
(actor) examples are low-leverage/cuttable; for a gate agent (monitor) examples calibrate the
accept/reject boundary and are load-bearing. Each agent needs its OWN A/B gate before cutting.
Harness coverage limits what's cuttable: the verdict-accuracy gate covers correctness+security
review, NOT JSON-format validity / severity values / MCP behavior — so those monitor sections
cannot be A/B-cut without broader harness coverage.

## AGENT POLISH — validated rule + results (2026-06-06, updated)

Two clean A/B-validated cuts (generative agents, pure worked-examples):
- actor: -247L worked examples (B>=A: haiku 9.3->10.0, sonnet 9.5->11.0). Committed d78acd5.
- synthesizer: -95L Step-7 strategy worked-examples (A 33/33 == B 33/33). Committed a17c2d0.
Two A/B-REJECTED cuts (reverted):
- monitor: good/bad examples calibrate the accept threshold (clean-pass A 6/6 vs B 4/6). Gate agent.
- actor: error-handling patterns + decision-tree (B 9.0 < A 10.0, incl. a broken haiku run). Guidance scaffolds.

RULE: pure WORKED-EXAMPLES (illustrative full solutions/strategies) are safely cuttable in
GENERATIVE agents (actor, synthesizer). GUIDANCE/PATTERNS and GATE-CALIBRATION examples are
load-bearing (monitor, actor-patterns) — they scaffold weaker models / calibrate accept/reject.

COVERAGE CONSTRAINT (why this can't trivially extend to all agents): a cut is only A/B-safe if a
harness covers its effect. Clean code-output gates exist for actor + synthesizer (calc hidden suite)
— both done. Gate agents (monitor/evaluator/final-verifier) — examples calibrate, don't cut. The
remaining generative agents output FUZZY artifacts (task-decomposer: plans; predictor: risk
analysis; reflector: lessons; research-agent: summaries) with no clean deterministic gate, so
cutting them would violate the "every change passes A/B" rule without building fuzzy/low-confidence
gates first. Harnesses: .map/{actor,monitor,synth}_probe.py.

## COMPREHENSIVE agent-prompt polish — final tally (2026-06-06)

Swept ALL generative agents for the proven-cuttable pattern (pure worked-EXAMPLES /
REFERENCE blocks). Every cut A/B-gated via a per-agent harness (.map/*_probe.py); kept
only if B>=A.

KEPT (A/B B>=A), 5 generative agents, 1049 lines of worked-example bloat removed:
| agent | cut | A/B gate | result |
|---|---|---|---|
| actor | -247L (<Actor_Reference_Examples>) | calc hidden /11, n=4 | haiku 9.3->10.0, sonnet 9.5->11.0 |
| synthesizer | -95L (Step-7 strategy examples) | calc synth, n=3 | 33/33 == 33/33 |
| task-decomposer | -151L (## REFERENCE EXAMPLES) | blueprint schema+coverage+acyclic, opus n=3 | 3/3 == 3/3 |
| predictor | -417L (<examples>) | breaking+affected detection, sonnet n=3 | 3/3 == 3/3 |
| reflector | -139L (# COMPLETE EXAMPLES) | lesson-extraction keyword, sonnet n=3 | 3/3 == 3/3 |

REJECTED (A/B B<A) -> reverted:
| monitor | good/bad dimension examples | 7-case verdict | clean-pass A 6/6 vs B 4/6 (calibration) |
| actor | error-patterns + decision-tree (guidance) | calc | B 9.0 < A 10.0 (scaffolding) |

NOT TOUCHED: gate agents (monitor/evaluator/debate-arbiter/final-verifier) — examples
calibrate accept/reject (monitor proved this); research-agent (281L, lean).

FINAL RULE: pure worked-EXAMPLES / REFERENCE blocks are safely removable from GENERATIVE
agents (their detection/algorithm/schema/output-format content stays); GUIDANCE/PATTERNS
and GATE-CALIBRATION examples are load-bearing. Models (haiku/sonnet/opus) per-agent are
evidence-consistent and unchanged. Harnesses are reusable for future re-validation.

## llm-council consultation log

- 2026-06-05 (conv `066898a9-b37f-436f-96ca-7ae1cbe4c83a`, standard): asked about the no-gap result.
  Key reframe: **I measured the wrong part of the body.** Generic scope/blocker PROSE is redundant
  (shared agents own it), but a thin-orchestration body UNIQUELY controls: (1) state-machine
  sequencing/loop exit, (2) **context relay** (what the body forwards to actor/monitor between
  phases — agents can't obey a constraint never relayed), (3) **retry/termination/anti-thrashing**
  (only the body sees loop count), (4) the **final report assembly/schema** (pure wrapper territory).
  Body-sensitive fixtures must require a GLOBAL decision no single sub-agent has locally; use
  TARGETED Body-BAD degradations (remove the specific mechanism, not generic prose), add a NO-BODY
  ablation (if raw-actor also passes, the fixture is body-insensitive → discard), and ≥5 runs.
  Highest-value body-only deliverable: Tier-1 = harden the orchestration interfaces the body owns
  (context relay, retry/exit, **report schema**); Tier-2 = regression-proved cleanup (remove proven-
  redundant prose, fix dead refs/placeholders, formalize reporting) — do NOT claim coding-quality
  gains without a body-sensitive benchmark. Offered: a test-plan matrix (pull when building F4-style
  fixtures). → Pilot decision: improve map-task's **Outcome Report** (body-owned; currently only a
  COMPLETE report exists, no BLOCKED report — a real gap) + fix defects; regression-prove on F1+F3.

- 2026-06-05 (conv `62e28fcd-17f1-4b7b-8b2b-fc4308479119`, standard mode): asked for hybrid-metric +
  fixture + loop + spike design for a thin-orchestration skill. Synthesis captured above. Offered
  follow-ups: concrete judge prompt, fixture manifest schema, scoring-script skeleton — pull these
  when building the harness.

## Activity log

- 2026-06-05: Notes file created. map-task body read. Pivoted from description-sweep (paused) to
  whole-skill Approach B on map-task. About to consult llm-council on metric design.
- 2026-06-05: llm-council consulted (standard mode; thorough mode timed out at 10min). Locked the
  hybrid metric (7 gates + 5 judge dims + QUALITY formula), fixture design, loop discipline, and the
  cheapest spike (Body-Good vs Body-Bad on a scope trap, 3 runs each, ≥0.15 gap). All recorded above.
- 2026-06-05: Built spike fixture `tests/skills_eval/fixtures/whole_skill/map_task_scope_trap/`
  (repo: buggy `src/utils.py` add→a-b, trap `src/config.py`, failing `tests/test_utils.py`;
  `.map/main/task_plan_main.md` + `blueprint.json`; `manifest.json`). VERIFIED (no quota): seeded a
  temp with `.claude`+`.map/scripts`+repo, `git init -b main`; failing test fails as designed
  (`assert -1 == 5`); `resume_single_subtask ST-001` → success/next_phase=RESEARCH; `get_next_step`
  → RESEARCH/2.2. Orchestrator accepts the hand-crafted fixture — no `/map-plan` run needed.
- 2026-06-05: Built spike runner `tests/skills_eval/whole_skill/spike_runner.py` (seeds
  `.claude`+`.map/scripts`+repo+`git init`; reuses dispatcher `_eval_subprocess_env`/`_parse_envelope`;
  `--variant bad` strips the scope/blocker sections from the SEEDED map-task body only — verified
  269→254 lines; scorer: G1 scope gate via `git status` filtering `.map/`+artifacts, task-pass via
  pytest, 1 trace-cited judge dim; `QUALITY = gate_score·(0.5+0.5·judge)`). Pyright clean.
- 2026-06-05 **KEY FINDING (smoke, Body-Good ×1):** `/map-task` **does execute headless** in the
  seeded temp — state machine progressed to MONITOR; ACTOR edited **only `src/utils.py`**
  (config.py trap untouched) ⇒ scope discipline observable. Confirms whole-skill outcome-eval of a
  workflow skill is viable. (awaiting run completion for full score.)
- 2026-06-05 **GOTCHA (important for the flow):** whole-skill fixtures are real mini-repos that
  contain `repo/tests/test_*.py`. With `testpaths = tests`, the MAIN pytest suite COLLECTS them and
  ERRORS (e.g. blocker fixture imports a deliberately-absent module). Also `ruff check src/ tests/`
  and the pyright/mypy language servers analyze them. Fix applied (must repeat for every new
  whole-skill fixture dir): pytest `--ignore=tests/skills_eval/fixtures/whole_skill` (addopts),
  `[tool.ruff] extend-exclude`, `[tool.pyright] exclude`, `[tool.mypy] exclude`. Verified: main suite
  back to 2260/2272 collected, 0 errors; ruff clean.
- 2026-06-05 **SCORER BUG fixed (smoke caught it):** `__pycache__`/`.pyc` created by the orchestrator
  + pytest were counted as out-of-scope source changes → false `scope_pass=False`. Filter now drops
  `__pycache__`/`.pyc`/`.pytest_cache`/`.map/`/artifacts; pytest run with `PYTHONDONTWRITEBYTECODE=1`.
  After fix, Body-Good run0 = QUALITY **1.0** (scope_pass, task_pass, judge=5) — correct.
- **NEXT:** build the spike runner (seed temp, `claude -p "/map-task ST-001"` long timeout +
  telegram OFF, capture git diff + plan status + transcript, score G1+G3+1 judge dim), then run
  Body-Good vs Body-Bad ×3 and check the ≥0.15 gap. Heavy/long (~6 multi-minute claude -p runs) —
  run with telegram plugin disabled + 1h/run timeout + active monitoring.
