# MAP Framework Roadmap

This document turns the [improvement-plan](./improvement-plan.md) into an implementation roadmap for `map-framework`.

It is based on four source documents:

- [Improvement Plan](./improvement-plan.md) — the full list of ideas and rationale
- [Architecture](./ARCHITECTURE.md) — how MAP is structured today
- [Usage](./USAGE.md) — how MAP is currently presented to users
- [MAP philosophy / DevOpsConf draft](./devopsconf_2026_ai_operator_presentation_rewrite-v2.md) — the target philosophy: `SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN`

## Fixed Product Decisions

- For non-trivial tasks, MAP should require `SPEC + PLAN` as the mandatory minimum.
- For serious changes, `REVIEW` should remain a mandatory stage.
- `LEARN` is mandatory in MAP philosophy, but it should not be a hard runtime gate because users optimize for token cost.
- Trivial tasks need an explicit off-ramp: not every piece of work should trigger MAP orchestration.
- First align the runtime with the process philosophy, and only then aggressively refine prompts, skills, and advanced orchestration.

## What To Do First

The main conclusion from the [improvement-plan](./improvement-plan.md) is that improvements should not happen everywhere at once, but in this order:

1. Make MAP a faithful implementation of its process philosophy.
2. Then modernize the command layer for Claude 4.6.
3. Then clean up skills and command/skill drift.
4. Only after that move on to expensive orchestration R&D.

## Iteration 1: Runtime Alignment With MAP Philosophy

**Why this comes first:** the main risk in MAP today is not wording, but the fact that the runtime still diverges in places from the philosophy `SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN`.

**Improvement-plan items:** `2604.038`, `2604.039`, `2604.036`

### Scope

- Introduce a workflow-fit classifier and an explicit off-ramp for trivial tasks.
- Make the artifact pipeline explicit: `spec`, `plan`, `test contract`, `implementation`, `review`, `verification`, `learn handoff`.
- Strengthen the separation between `TEST` and `CODE`: use a persisted handoff instead of a merged “one session does everything” flow.

### Main deliverables

- Preflight decision matrix: `direct edit` vs `/map-fast` vs `/map-efficient` vs `/map-tdd`
- Branch-scoped `artifact_manifest`
- `test_contract_<branch>.md` / `test_handoff_<subtask>.json` or an equivalent persisted handoff
- Updated docs that describe one canonical artifact pipeline for serious work

### Primary files

- [README.md](../README.md)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)

### Exit criteria

- Non-trivial tasks no longer jump straight into implementation.
- Complex and TDD flows have an explicit persisted contract between planning, tests, and code.
- MAP can honestly say: “this task does not need orchestration.”

### How We Will Achieve It

#### Step 1. Add a workflow-fit preflight

Introduce a simple classifier before the full MAP flow.

It should answer:
- whether MAP is needed at all
- if it is needed, which surface should run: `/map-fast`, `/map-efficient`, or `/map-tdd`

This should not be a black box. It should be a short decision gate based on:
- blast radius
- expected diff size
- whether new models or invariants are introduced
- whether independent review is needed
- whether acceptance criteria are already clear

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [README.md](../README.md)
- [docs/USAGE.md](./USAGE.md)

**Expected result:**
- trivial work can exit with `direct edit / no MAP orchestration recommended`
- non-trivial work is routed into `SPEC + PLAN` before implementation

#### Step 2. Make the artifact pipeline explicit

MAP already has `spec_<branch>.md`, `task_plan_<branch>.md`, `step_state.json`, and verification/state artifacts, but they are not yet presented as one stage contract.

Add an explicit workflow-level `artifact_manifest` that tracks:
- `spec`
- `plan`
- `test_contract`
- `implementation`
- `review`
- `verification`
- `learn_handoff`

This manifest must be updated by the orchestrator/runtime layer, not by the user.

**Implementation surfaces:**
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)

**Expected result:**
- MAP knows which stage artifact is produced and consumed at each step
- review and later stages stop reconstructing intent from the raw diff alone

#### Step 3. Split TEST and CODE with a persisted handoff

This is the key runtime change in Iteration 1.

Today `/map-tdd` correctly runs `TEST_WRITER -> TEST_FAIL_GATE -> ACTOR`, but it still does so inside one orchestration stream. That is not enough for a clean-session testing philosophy.

Add a persisted handoff between TEST and CODE:
- after `TEST_FAIL_GATE`, the run can stop in `contract_ready`
- `test_contract_<branch>.md` and `test_handoff_<subtask>.json` (or equivalent artifacts) are created
- the next implementation run reads only:
  - spec
  - plan
  - failing tests
  - compact test handoff

The implementation stage should work from the contract, not from the full test-authoring deliberation.

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)

**Expected result:**
- tests become real reviewable artifacts
- implementation no longer continues inside the same context that authored the tests
- MAP gets closer to `TEST -> CODE in separate sessions` without forcing awkward manual ceremony

#### Step 4. Add guardrails for contract-sized subtasks

Once the artifact pipeline exists, MAP can add process guardrails through runtime data rather than rhetoric.

Add these fields to planning and decomposition:
- `expected_diff_size`
- `concern_type`
- one-logical-step expectations per subtask

Then use them in Monitor and final verification to warn or block when:
- a subtask diff is too large to review comfortably
- one subtask mixes too many concern types without justification

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)

**Expected result:**
- smaller, more reviewable subtasks
- less scope creep inside a single execution step

#### Step 5. Lock the change set down with tests

Iteration 1 is not complete if it exists only in docs and prompts. It needs runtime and artifact tests.

**Primary test surfaces:**
- [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py)
- [tests/test_map_step_runner.py](../tests/test_map_step_runner.py)
- [tests/test_workflow_state.py](../tests/test_workflow_state.py)
- [tests/test_verification_recorder.py](../tests/test_verification_recorder.py)

**Tests to add:**
- workflow-fit classifier routes trivial vs non-trivial tasks correctly
- artifact manifest is created and updated through stage transitions
- TDD flow can stop after `TEST_FAIL_GATE` and resume implementation from a persisted contract
- resuming from a persisted test contract survives context reset and restart
- oversized or mixed-concern subtasks are surfaced as warnings or blocked states according to the chosen policy

#### Recommended PR sequence

To avoid turning this into one large refactor, implement it in this order:

1. workflow-fit classifier + docs routing
2. artifact manifest schema + runtime updates
3. split TEST/CODE handoff for TDD
4. contract-sized subtask guardrails
5. tests + template sync + docs cleanup

## Iteration 2: Review Independence And Soft LEARN Ergonomics

**Why this comes next:** once task-fit and artifact flow are aligned, the next priority is to make review truly independent and to put `LEARN` back in the right place without hard enforcement.

**Improvement-plan items:** `2604.037`, `2604.035`

### Scope

- Detached review context: review bundle, optional detached/worktree mode
- Cheap closeout path for `LEARN`: handoff artifact, prefilled invocation, batch learning

### Main deliverables

- Canonical `review_bundle` artifact that consumes spec + tests + diff + verification context
- Optional detached review mode for serious changes
- `learning_handoff_<branch>.md` or `.json`
- Docs that say `LEARN` is philosophically required, but runtime leaves token spend to the user

### Primary files

- [src/mapify_cli/templates/commands/map-review.md](../src/mapify_cli/templates/commands/map-review.md)
- [src/mapify_cli/templates/commands/map-check.md](../src/mapify_cli/templates/commands/map-check.md)
- [src/mapify_cli/templates/skills/map-learn/SKILL.md](../src/mapify_cli/templates/skills/map-learn/SKILL.md)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- [README.md](../README.md)

### Exit criteria

- `/map-review` no longer depends primarily on implementer context
- `LEARN` no longer looks like a random optional hint at the end
- users can defer learning without losing context or manually rebuilding the summary

## Iteration 3: Command Layer Modernization For Claude 4.6

**Why only after that:** prompt tuning is useful, but it should not mask structural issues in the runtime.

**Improvement-plan items:** `2604.025`, `2604.026`, `2604.027`, `2604.028`, `2604.029`

### Scope

- Soften overbearing guardrails and calibrate command tone
- Standardize XML/context envelopes
- Add few-shot examples and evidence-first output contracts
- Convert lightweight flows to action-first tool use
- Introduce command-specific thinking and parallelism policies

### Main deliverables

- Shared prompt envelope for `.claude/commands/map-*.md`
- Shared examples library for the most common JSON contracts
- Updated `/map-fast` and `/map-debug` without “return full file content”
- Explicit `thinking_policy` and `parallel_tool_policy` blocks per command

### Primary files

- [src/mapify_cli/templates/commands/map-fast.md](../src/mapify_cli/templates/commands/map-fast.md)
- [src/mapify_cli/templates/commands/map-debug.md](../src/mapify_cli/templates/commands/map-debug.md)
- [src/mapify_cli/templates/commands/map-review.md](../src/mapify_cli/templates/commands/map-review.md)
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/hooks/workflow-context-injector.py](../src/mapify_cli/templates/hooks/workflow-context-injector.py)
- [docs/USAGE.md](./USAGE.md)

### Exit criteria

- Commands stop sounding like they are compensating for older model behavior
- Lightweight workflows write code via tools instead of serialized full-file payloads
- Long-context commands share one readable, repeatable prompt structure

## Iteration 4: Skills Consolidation And Catalog Hygiene

**Why after the command layer:** skills matter, but right now they are not the largest source of product drift.

**Improvement-plan items:** `2604.030`, `2604.031`, `2604.032`, `2604.033`, `2604.034`

### Scope

- Eliminate command/skill drift
- Fix metadata quality and frontmatter hygiene
- Explicitly define `reference` vs `task` skills
- Move heavy content into supporting files
- Add trigger/invocation regression tests

### Main deliverables

- One canonical source of truth for overlapping command/skill surfaces
- Clean descriptions and invocation metadata
- Honest skill taxonomy docs
- Better skill tests, including negative-trigger cases

### Primary files

- [src/mapify_cli/templates/skills/README.md](../src/mapify_cli/templates/skills/README.md)
- [src/mapify_cli/templates/skills/skill-rules.json](../src/mapify_cli/templates/skills/skill-rules.json)
- [src/mapify_cli/templates/skills/map-planning/SKILL.md](../src/mapify_cli/templates/skills/map-planning/SKILL.md)
- [src/mapify_cli/templates/skills/map-learn/SKILL.md](../src/mapify_cli/templates/skills/map-learn/SKILL.md)
- [tests/test_skills.py](../tests/test_skills.py)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)

### Exit criteria

- MAP no longer has a confusing duality between command and skill surfaces
- skills documentation matches runtime reality
- skill triggering and invocation regressions are caught by tests instead of users

## Iteration 5: Orchestrator R&D And Deep Optimization

**Why this is last:** advanced orchestration only pays off after the product model is already stable.

**Improvement-plan items:** `2604.019`, `2604.020`, `2604.021`, `2604.022`, `2604.023`, `2604.024`, `2604.014`, `2604.017`

### Scope

- `REGISTRY/FOCUS`
- steering requests and preemption
- deterministic token budgets
- agent registry snapshots
- multi-phase evaluation harness
- family-specific model scaling analysis
- deeper resiliency and health reporting

### Main deliverables

- Feature-flagged orchestrator experiments
- Better metrics and health reports
- Controlled A/B evaluation instead of intuition-based tuning

### Primary files

- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)
- [src/mapify_cli/templates/hooks/workflow-context-injector.py](../src/mapify_cli/templates/hooks/workflow-context-injector.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)
- [src/mapify_cli/verification_recorder.py](../src/mapify_cli/verification_recorder.py)
- [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py)
- [tests/test_map_step_runner.py](../tests/test_map_step_runner.py)
- [tests/test_workflow_state.py](../tests/test_workflow_state.py)
- [tests/test_verification_recorder.py](../tests/test_verification_recorder.py)

### Exit criteria

- Advanced context and orchestration ideas are measured, not just described
- MAP can prove which orchestration mechanisms actually improve approval rate, latency, and context discipline

## What Not To Do First

- Do not start with `REGISTRY/FOCUS` while artifact pipeline and workflow-fit are still not aligned
- Do not start with skills cleanup while the product/runtime still violates the main philosophy
- Do not try to “fix MAP” only through wording changes in prompts
- Do not make `LEARN` hard-gated

## Practical Execution Notes

- If `.claude/commands/`, `.claude/hooks/`, or `.claude/skills/` change, keep them synchronized with `src/mapify_cli/templates/`
- The preferred sync path is `make sync-templates`
- Agent template sync already has a guard: [tests/test_template_sync.py](../tests/test_template_sync.py)
- For command, skill, and runtime changes, this roadmap assumes new tests will live next to the existing suites:
  [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py),
  [tests/test_map_step_runner.py](../tests/test_map_step_runner.py),
  [tests/test_workflow_state.py](../tests/test_workflow_state.py),
  [tests/test_verification_recorder.py](../tests/test_verification_recorder.py),
  [tests/test_skills.py](../tests/test_skills.py)

## Short Version

If you compress the roadmap to one sentence:

**First make MAP process-correct and artifact-first, then modernize commands, then clean up skills, and only after that invest in advanced orchestration research.**
