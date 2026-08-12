# Spike: Specula applicability to MAP Framework

**Source:** Qian Cheng et al., “Specula: Scaling formal specifications for
autonomous model checking of system code,” arXiv:2607.25333v1, 2026.
**Status:** source-and-repo applicability assessment; no implementation and no
Specula run.
**Captured:** 2026-07-29 against MAP Framework `main` and Specula revision
[`d45b873`](https://github.com/specula-org/Specula/tree/d45b873bc19cf51bc26fd845fce072d9b99b5cd0).

## Verdict

**ADOPT the invariant-lineage contract now; validate it with an internal opt-in
pilot; consider an external Specula adapter only after that. Do not add default
TLA+ to MAP.**

The highest-confidence transferable gap is smaller than formal model checking:
MAP names invariants and tracks their downstream tags, but it does not require
each invariant to record where it came from, under which scenario/fault model it
must hold, or how it will be verified. That lineage is useful for every MAP
workflow and can be enforced deterministically without Specula, Java, or an
extra model call.

The paper is then relevant to one high-risk MAP experiment: the
`map_orchestrator`/concurrent-wave state machine, where correctness depends on
state transitions, interleavings, rollback, and cleanup. The first pilot should
remain internal and reuse the shipped trajectory evaluator from issue #351. An
external Specula adapter becomes justified only if the lineage pilot proves
useful and state-space exploration still provides incremental value.

The broader proposal—shipping Specula, TLA+, or model checking as a standard
`mapify` dependency or a default phase—is not supported by the paper's evidence.
Specula was evaluated on concurrent and distributed systems, is resource-heavy,
and is highly sensitive to the underlying model. MAP is a low-overhead,
local-first workflow installer used against arbitrary repositories, so a
mandatory formal-methods path would violate its product boundary.

| Classification | Decision |
|---|---|
| **Adopt now** | Add mandatory, deterministic invariant lineage: provenance source kind/reference, scenario or fault model, and verification method for every `INV-*`. |
| **Experiment first** | Internal, opt-in `map_orchestrator` state-machine fixture evaluated through the already-shipped `mapify skill-eval trajectory` (#351), candidate versus anchor. |
| **Experiment later** | A thin external Specula adapter for the concurrent wave lifecycle only, conditional on the internal pilot. |
| **Reject / not applicable** | Do not add a generic `/map-specula` skill, bundle Specula MCPs/TLA+ tooling, run it for every MAP task, or treat an LLM-generated TLA+ model as proof of correctness. |

## What the paper actually establishes

Primary sources:

- [arXiv abstract and metadata](https://arxiv.org/abs/2607.25333)
- [paper PDF, version 1](https://arxiv.org/pdf/2607.25333v1)
- [official Specula repository at the inspected revision](https://github.com/specula-org/Specula/tree/d45b873bc19cf51bc26fd845fce072d9b99b5cd0)
- [official usage guide at the inspected revision](https://github.com/specula-org/Specula/blob/d45b873bc19cf51bc26fd845fce072d9b99b5cd0/docs/Usage.md)

### Method

Specula is an agentic pipeline for concurrent and distributed system code. It:

1. mines code, documentation, issue/PR history, tests, and commits for
   evidence-backed protocol- and code-level invariants;
2. creates a reference TLA+ model and scenario-specific projections at
   different abstraction levels;
3. instruments the implementation and validates real execution traces against
   the generated model;
4. model-checks the model with TLC;
5. replays each counterexample against the implementation and packages a
   successful reproduction as a test; and
6. iterates when trace validation, model checking, or reproduction exposes an
   incorrect invariant, model, or instrumentation plan.

The important mechanism is not “an LLM writes TLA+.” It is the bidirectional
feedback boundary:

- trace validation rejects models that omit observed implementation behavior;
- model checking rejects over-permissive repairs that admit invalid states; and
- code-level reproduction rejects a model-level violation that cannot be
  realized in the implementation.

The authors explicitly say that no generated artifact is assumed correct
upfront. The official tool exposes this as
`analyze → specgen → harness → validate → confirm`; `validate` checks real
traces and runs TLC, while `confirm` reproduces candidates in the implementation
([official usage, lines 273–280](https://github.com/specula-org/Specula/blob/d45b873bc19cf51bc26fd845fce072d9b99b5cd0/docs/Usage.md#L273-L280)).

### Experimental results and their boundary

The main evaluation (paper §5) used Claude Code v2.1.97 with Claude Opus-4.8,
a 1M-token context window, and maximum reasoning on a 96-core AMD EPYC VM with
384 GB RAM.

- Scope: 48 projects—36 distributed systems and 12 concurrent systems—across
  C, C#, C++, Erlang, Go, Java, and Rust, sized 2K–95K LoC.
- Findings: 249 bugs, comprising 207 new and 42 known-but-unfixed bugs.
  The authors reported 89; 68 were developer-confirmed and 24 fixed at paper
  time.
- Model-checking yield: 200/249 findings came from model checking; 187/200 were
  found by bounded breadth-first exploration. The median counterexample length
  was 9 and p90 was 18.
- Invariant mix: 99.10% safety and 0.90% liveness; liveness checking was mainly
  deadlock detection.
- Latest-version subset: only 14 of the 48 systems were checked with the latest
  Specula release. It reported 136 bugs there, reproduced 134 as tests, and
  reproduced two more without observing a severe consequence.
- Five-system comparison: with the same prompts, Specula found 62 bugs versus
  2 for a raw agent and 3 for an agent equipped with ordinary TLA+ skills/tools.
  The paper reports five and two false positives for those baselines,
  respectively.
- Cost: 1.43–9.86 hours and $19–$168 in token cost per system, with medians of
  3.69 hours and $57. On the five-system comparison, Specula was 4.8–37× more
  expensive than the raw agent and 1.8–65× more expensive than the TLA+-tool
  agent.
- Model sensitivity: on the five-system comparison, Sonnet-4.6 found 10 of the
  62 Opus findings and Haiku-4.5 found none. The weaker runs also had lower
  model conformance and more reward-hacking behavior.

These are strong bug-finding results, but they do **not** establish a general
formal-verification guarantee:

- The 48-system corpus was accumulated while Specula itself was being
  developed; most systems were not rerun on the final version because of
  budget. This is not a held-out or randomized evaluation.
- “No false positives” is grounded in the authors' code-level reproduction
  criterion for the latest subset, not independent confirmation of every
  finding. Only 68 of the 89 externally reported new bugs had been confirmed.
- The baselines are raw/ordinary-TLA+ agent configurations, not conventional
  testing, fuzzing, human TLA+ experts, or other state-of-the-art verification
  systems.
- Python is not among the evaluated implementation languages, so the paper
  does not demonstrate trace-harness effectiveness on MAP's Python runtime.
- The paper's own “Formal guarantee” discussion (§6) states that an
  agent-generated model may miss implementation behavior and generated
  invariants may miss required properties. A bug depending on such a gap can
  remain undetected.
- The official project requires Java 21+, Maven, the target toolchain, an agent
  runtime, and substantial machine resources
  ([README, lines 29–47](https://github.com/specula-org/Specula/blob/d45b873bc19cf51bc26fd845fce072d9b99b5cd0/README.md#L29-L47));
  its usage guide warns that model checking is long-running and
  memory-intensive
  ([Usage, lines 15–35](https://github.com/specula-org/Specula/blob/d45b873bc19cf51bc26fd845fce072d9b99b5cd0/docs/Usage.md#L15-L35)).

## Mapping to MAP's current implementation

### High-confidence gap: invariant lineage

MAP's plan template currently defines invariants only as “Non-negotiable system
truths” (`src/mapify_cli/templates_src/skills/map-plan/plan-reference.md.jinja:16-18`).
The authoritative Requirements Index carries only `{id, kind}`
(`src/mapify_cli/templates_src/skills/map-plan/plan-reference.md.jinja:28-49`).
Even if an author adds provenance fields to an entry,
`parse_requirements_index` projects it back to only `id` and `kind`
(`src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:3146-3171`).

The existing citation gate is valuable but insufficient for this purpose: it
scans and validates citations already present anywhere in the spec; it does not
require every `kind: invariant` entry to have provenance
(`src/mapify_cli/templates_src/map/scripts/validate_spec_citations.py.jinja:1-16`,
`src/mapify_cli/templates_src/map/scripts/validate_spec_citations.py.jinja:96-118`).
Downstream acceptance coverage is also tag-presence based: an `INV-*` is
`covered` when its tag occurs in a selected evidence artifact, without a typed
link from the invariant's source to a scenario and executable verification
(`src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:4334-4376`,
`src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:4412-4450`).

Adopt a low-cost `Invariant_Lineage_v1` contract inside each Requirements Index
`kind: invariant` entry:

```yaml
- id: INV-1
  kind: invariant
  lineage:
    sources:
      - kind: code
        ref: src/module.py:120-138
    scenario: concurrent wave abort after a partial squash merge
    fault_model: merge conflict, process interruption, or failed verification
    verification:
      method: test
      ref: tests/test_wave.py::test_abort_restores_base
```

The source-kind vocabulary should cover `code`, `test`, `issue`, `commit`,
`document`, and `user_decision`. A deterministic validator should:

1. require non-empty lineage for every indexed `INV-*`;
2. validate repo `file:line` ranges, test references, commit existence, and
   typed external/user-decision references without dereferencing secrets;
3. require a non-empty scenario, an explicit fault model (`none` allowed only
   with rationale), and a named verification method;
4. preserve the lineage through parsing, `coverage_map`, verification summary,
   and review bundle; and
5. report `missing_lineage` separately from `missing_evidence`—declaring an
   owner or repeating `[INV-1]` must not self-certify provenance.

This slice is justified without TLA+: it closes a concrete planning/verification
contract gap and supplies grounded input to any later model checker.

### Already aligned: retain these mechanisms

1. **System artifacts as ground truth.** MAP requires `file:line` evidence
   before planning and persists branch-scoped research artifacts
   (`docs/ARCHITECTURE.md:24`, `docs/ARCHITECTURE.md:93-100`). Monitor treats
   source, tests, schemas, and config as authoritative over transcripts and
   requires evidence for dismissal
   (`src/mapify_cli/templates_src/agents/monitor.md.jinja:23-39`).

2. **Executable feedback over self-report.** Monitor runs build/tests and
   traces the code path before accepting a change
   (`src/mapify_cli/templates_src/agents/monitor.md.jinja:49-74`), while
   FinalVerifier re-runs tests and checks actual file state
   (`src/mapify_cli/templates_src/agents/final-verifier.md.jinja:51-65`).

3. **Bounded self-correction.** `/map-efficient` uses state-gated
   Actor→Monitor retries, clean-retry isolation, anti-repeat evidence, and
   terminal escalation instead of accepting convergence as correctness
   (`src/mapify_cli/templates_src/skills/map-efficient/SKILL.md.jinja:320-392`;
   `docs/ARCHITECTURE.md:374-378`).

4. **Code-level reproduction.** `/map-debug` records an immutable probe only
   after the runner witnesses exit 42 and closes the gate only after the same
   snapshot flips to exit 0; the architecture explicitly says this is evidence
   of a behavioral flip, not proof that the probe captured the root cause
   (`docs/ARCHITECTURE.md:373`).

Specula therefore validates MAP's direction: independent executable oracles and
new evidence per iteration matter more than another reviewer prompt. It does
not justify adding another generic self-review loop; the missing portable
contract is typed invariant lineage.

### Real gap: no state-space exploration of the wave coordinator

The concurrent wave path is closer to Specula's demonstrated domain than the
rest of MAP:

- concurrent dispatch is enabled for parallel-ready plans and uses isolated
  worktrees (`docs/ARCHITECTURE.md:206-248`);
- a group has persistent lifecycle events and crash reconciliation
  (`docs/ARCHITECTURE.md:229-254`);
- `merge_wave_worktrees` promises all-or-nothing behavior across textual
  conflicts, commit failures, and a post-wave full verification gate
  (`docs/ARCHITECTURE.md:169-204`);
- the implementation derives a shared base SHA, rejects external HEAD
  movement, serializes coordinators, rolls back on merge/check failure, and
  cleans worktrees only after success
  (`src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:17600-17623`,
  `src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:17670-17721`,
  `src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:17753-17911`);
- abort is intended to be idempotent, preserve MAP runtime state, verify that
  rollback actually reached the base SHA, and leave a failed rollback visible
  (`src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja:18149-18257`).

The test suite has strong real-git and adversarial examples: whole-group abort,
successful atomic merge, rollback mismatch, `.map/` preservation, and an open
group blocking the next wave
(`tests/test_map_step_runner.py:14244-14294`,
`tests/test_map_step_runner.py:14398-14540`,
`tests/test_map_step_runner.py:14980-15045`,
`tests/test_governance_attack_fixtures.py:353-386`).
Those tests exercise selected schedules. They do not enumerate the transition
space across group creation, actor completion, merge phases, process
interruption, rollback, cleanup, and resume. That is the narrow incremental
value a TLA+/TLC model could test.

### Product and architecture mismatch for broad adoption

- MAP's quality goals include low overhead and a usable daily-driver golden
  path (`docs/ARCHITECTURE.md:40-47`); Specula's median hours/cost and heavy
  prerequisites do not fit a mandatory phase.
- MAP explicitly does not ship or maintain third-party MCP servers
  (`docs/ARCHITECTURE.md:34-38`). Bundling Specula's skills and three MCP tools
  would expand that boundary.
- `mapify` currently has a small Python dependency surface and no TLA+/TLC
  runtime (`pyproject.toml:7-21`). Pulling Java/Maven/TLA+ into the installer is
  not a narrow dependency addition.
- Most MAP work is ordinary application development, while Specula's evidence
  is for concurrent/distributed system behavior. A default check would add
  ceremony where its state-space advantage is absent.
- Specula itself is a complete agent workflow. Embedding its orchestration
  inside MAP would duplicate phase/state/skill ownership. External invocation
  keeps each tool's source of truth intact.

## Adoption sequence

### Phase 1 — adopt invariant lineage

Implement only the Requirements Index/template/parser/validator and downstream
artifact propagation described above. The acceptance bar is deterministic:
every `INV-*` has typed provenance, scenario/fault model, and verification
method; invalid or missing references stop planning; round-tripping never drops
lineage; tag-only downstream evidence cannot be mislabeled as complete lineage.
No agent, model, TLA+, or network dependency belongs in this slice.

### Phase 2 — internal opt-in state-machine pilot

Before integrating Specula, build one sanitized whole-skill fixture around the
`map_orchestrator`/wave state machine and reuse the shipped trajectory evaluator
from issue #351. Do **not** create another eval harness:

- `mapify skill-eval trajectory` already executes a whole skill in a throwaway
  repo, scores deterministic outcome/scope gates, stores evidence-linked
  bundles, repeats noisy runs, and compares candidate against an anchor
  (`docs/TRAJECTORY-EVAL.md:8-23`, `docs/TRAJECTORY-EVAL.md:58-104`);
- its bundle contract already carries Git state, verification, MAP artifacts,
  resiliency signals, and run metadata
  (`src/mapify_cli/skills_eval/trajectory/eval_schema.py:177-229`);
- candidate-versus-anchor reports and three-run flaky detection already exist
  (`docs/TRAJECTORY-EVAL.md:79-113`).

The fixture should exercise successful progression plus invalid/skipped
transition, Monitor rejection/retry, wave abort, and resume. Hidden deterministic
checks assert final cursor/status, main HEAD, open-group/worktree state, and
preserved runtime artifacts. The candidate uses `Invariant_Lineage_v1`; the
anchor uses current behavior. Run at least three repetitions and require:

1. all injected missing/stale/phantom lineage cases fail before Actor;
2. success/abort outcomes satisfy the lineage-linked verification methods;
3. no regression in trajectory `formal`, `end_result`, or `reporting_trust`;
4. candidate evidence points to the exact lineage record and executable result;
5. overhead is measured rather than hidden.

If this pilot cannot distinguish grounded invariants from tag repetition, fix
the lineage contract; external formal tooling would only amplify bad input.

### Phase 3 — conditional external Specula adapter

Only after Phase 2 passes, consider a thin opt-in adapter that exports validated
lineage and invokes a separately installed, pinned Specula. It must remain an
external maintainer tool: no bundled Specula MCPs, no automatic setup, and no
default workflow phase.

### Scope

Run the pinned Specula revision externally against a private copy of this
repository, with analysis restricted to the rendered wave runtime and its
canonical template source:

- `src/mapify_cli/templates_src/map/scripts/map_orchestrator.py.jinja`
- `src/mapify_cli/templates_src/map/scripts/map_step_runner.py.jinja`
- their rendered `src/mapify_cli/templates/map/scripts/*.py` counterparts
- the wave tests in `tests/test_map_orchestrator.py`,
  `tests/test_map_step_runner.py`, and
  `tests/test_governance_attack_fixtures.py`

Use Specula's `--keep-original`; the official contract says it runs on a private
copy and emits a patch without applying changes to the original checkout
([README, lines 99–112](https://github.com/specula-org/Specula/blob/d45b873bc19cf51bc26fd845fce072d9b99b5cd0/README.md#L99-L112)).
Do not install Specula skills/MCPs into MAP's shipped provider surfaces.

### Initial invariants

Every invariant must cite its implementation and test lineage before modeling:

1. **Failed wave atomicity:** after any merge conflict, commit failure, or
   post-wave gate failure, main `HEAD == wave_base_sha` and no subtask commit
   from that wave remains reachable on the working branch.
2. **Successful wave accounting:** each member is accounted for exactly once as
   `merged` or `no_changes`; success cleans its worktree/branch records only
   after the post-wave gate passes.
3. **Fail-closed dispatch:** a config contradiction, non-shared base, external
   HEAD movement, dirty target, detached HEAD, or competing coordinator cannot
   enter the merge transaction.
4. **Crash-visible lifecycle:** an open or partially terminal group cannot be
   reported clean or silently swept; a genuinely orphaned/terminal group can be
   reconciled idempotently.
5. **Abort preservation:** abort returns to the recorded base, discards every
   group worktree, preserves `.map/`, `.codex/`, and `.agents/`, and does not
   erase the group record when rollback verification fails.

### Scenarios

Bound the first model to two subtasks and one wave, then cover:

- full success;
- conflict on the second squash merge;
- post-wave verification failure after both squash merges;
- external HEAD movement before merge;
- process interruption after `begin_wave_group` and before all terminal events;
- rollback that returns without moving HEAD.

Use actual temporary Git repositories and the rendered runtime for trace
collection. Mock-only lifecycle traces are insufficient because the experiment
is specifically testing conformance between the model, Git effects, and
sidecar state.

### Acceptance criteria

The experiment is successful only if all of the following hold:

1. **Grounded model:** every modeled action and invariant cites the exact MAP
   source/test lines it represents; generic Raft/TLA+ examples are rejected.
2. **Tool validity:** generated TLA+ passes SANY/TLC syntax and runtime checks.
3. **Model-code conformance:** both a successful trace and every listed failure
   scenario replay through the trace-validation harness without weakening an
   invariant merely to make the trace pass.
4. **Bounded exploration:** TLC exhausts the two-subtask bounded state space;
   simulation-only results do not satisfy the experiment.
5. **Real confirmation:** every reported counterexample is reproduced against
   the rendered Python runtime in an isolated real Git repository. An
   unreproduced model violation is recorded as a model/harness gap, not a MAP
   bug.
6. **Incremental value:** compare findings against the existing wave tests. A
   promotion decision requires at least one previously uncovered reachable
   defect or a concrete reachable transition gap that becomes a regression
   test; restating existing tests is a negative result.
7. **Resource bound:** stop at four wall-clock hours, 32 GB TLC memory, and
   $75 equivalent model cost. Record actual time, token cost, peak memory,
   model/effort, Specula SHA, MAP SHA, and explored-state count.
8. **No product mutation:** this experiment produces a report and private
   Specula artifacts only. It does not modify shipped templates, dependencies,
   provider config, or the MAP workflow.

### Promotion / rejection gate

- **Promote to a repeatable optional maintainer check** only if the experiment
  meets all acceptance criteria and demonstrates incremental defect-finding or
  coverage value at tolerable cost.
- **Reject integration** if Python trace validation cannot establish
  conformance, the model only mirrors existing tests, counterexamples do not
  reproduce, or the run exceeds the resource bound.
- Even after a successful experiment, keep Specula external and opt-in. A
  separate decision would be required before any shipped MAP surface or
  dependency change.

## Bottom line

The transferable result is **grounded invariants plus oracle design**, not TLA+
everywhere: require lineage for inferred properties, force iterative
improvement through independent executable feedback, and require code-level
reproduction before calling a model-level violation a bug. MAP already follows
most of the oracle rule but is missing mandatory `INV-*` provenance. Its one
plausible formal-methods target is the atomic concurrent wave coordinator;
validate that with the staged internal and bounded external experiments before
considering any integration.
