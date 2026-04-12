# map-framework Improvement Plan

> Note: This file is the active product/runtime backlog for MAP philosophy alignment. For the separate research note about self-execution simulation in Monitor, see [docs/improvements-plan.md](./improvements-plan.md).

## Dual-Mode Orchestrator with REGISTRY/FOCUS States [2604.019]

**Benefit Hypothesis**: For workflows with ≥3 concurrent/parallel agent prompts (e.g., `/map-review` launches Monitor+Predictor+Evaluator in parallel) or workflows with conditional research + self-audit, REGISTRY/FOCUS context isolation will reduce step/tool mis-steering and invalid agent sequencing events by at least 30% relative to the current Phase 1.2 “best-effort” context injection, measurable via fewer orchestrator guardrail triggers (“Infinite loop detection at orchestrator level” and “no step skipping” enforcement) and a reduction in average tokens entering tool calls without reducing Monitor approval rate (target remains >80% first try per Success Metrics).
**Confidence**: 0.58
**Reasoning**: The pre-approved idea targets context pollution in multi-agent orchestration: it proposes a finite-state orchestrator with `REGISTRY/FOCUS` and a `STEERING_REQUEST` protocol. This aligns directly with MAP’s existing pain points and mitigations around context window dilution. The architecture evidence states: (1) command files used to be long and caused “attention dilution → Claude skips critical workflow steps like research and self-audit (20% compliance rate)” and this was improved by hook-based constant reminders and a state machine; (2) Phase 1.2 already attempts context management but explicitly uses a “best-effort” `<map_context>` block targeting “≤4 000 tokens”; (3) orchestration is already implemented via `.map/scripts/map_orchestrator.py` with sequential enforcement and state persisted in `.map/<branch>/step_state.json`, but the context injection approach is not formally a `REGISTRY/FOCUS` mode switch; (4) MAP does have parallel multi-agent review behavior (“/map-review … [Monitor + Predictor + Evaluator] (all 3 parallel)”), where cross-agent context contamination could plausibly be most harmful. Therefore, implementing explicit REGISTRY/FOCUS mode transitions and strict token budgets before every tool/LLM call should strengthen the already-present context engineering foundation.
**Why Not Already Tried**: No completed ideas are listed (“Already Tried / Completed Ideas: (none)”), and the architecture evidence shows Phase 1.2 implemented a best-effort active window injection and hook-based reminders, not a formal dual-mode `REGISTRY/FOCUS` orchestrator with an explicit steering protocol. The current design improves compliance but does not explicitly enforce “only one agent gets full context” as a deterministic mode at every call boundary; this gap motivates a more rigorous stateful context isolation strategy.

### Proposed Changes

- Add a new orchestrator mode layer inside `.map/scripts/map_orchestrator.py` that explicitly maintains two context modes: `REGISTRY` (lightweight summaries) and `FOCUS` (full context for exactly one agent step). Currently, the architecture describes state-machine orchestration in `.map/scripts/map_orchestrator.py` and context injection via `workflow-context-injector.py`; extend this to enforce a deterministically built `REGISTRY/FOCUS` context budget per tool call.
- Implement a `STEERING_REQUEST` protocol between agents and the orchestrator: when an agent determines a next step requires deeper context (e.g., research-agent conditional step or Actor phase), have it emit a steering request with `urgency` (LOW/MEDIUM/HIGH) and `target_agent` (e.g., `actor`, `monitor`, `predictor`). The orchestrator then transitions REGISTRY→FOCUS for that target only. This builds directly on the existing “Orchestrator enforces strict agent ordering” and “State file: `.map/<branch>/step_state.json` … Enforces sequential execution, no step skipping”.
- Refactor context building into a single budgeted function, replacing today’s best-effort context block insertion described under “Context-Aware Step Injection (Phase 1.2)”. Evidence states the Actor prompt layer injects a structured `<map_context>` block “best-effort (target: ≤4 000 tokens, best-effort)”. Change this to a strict token-budget algorithm shared by both `workflow-context-injector.py` and the Actor prompt layer: before every LLM/tool call, compute the final token budget and truncate/omit non-target agent artifacts. (The idea explicitly says “Enforce hard token budget T deterministically before every LLM call” and to “Log every token entering each LLM call for experimental observability”; implement token logging alongside existing `.map/workflow_logs/` and `.claude/metrics/agent_metrics.jsonl` usage.)
- Extend `.map/workflow_logs/` JSON schema to record the mode used for each tool/agent call (`REGISTRY` vs `FOCUS`) and the context sources included (e.g., `goal`, `current_subtask`, `upstream_results`, `repo_delta`). This aligns with the existing workflow logging (“Structured logging with workflow context in `.map/workflow_logs/`”) and metrics tracking (“Metrics tracked in `.claude/metrics/agent_metrics.jsonl`”).
- Add an automated regression test harness that compares completion rate and “research skip rate/self-audit skip rate” when running the same workflow with (A) current injection and (B) REGISTRY/FOCUS injection. The architecture already provides measured outcomes for hook-based context injection: step compliance increased to ~85% and research skip rate predicted from 80% to ~5%, self-audit predicted from 90% to ~10%. Use these as baselines and add new KPIs specific to multi-step/multi-agent contamination (e.g., track incorrect-step execution and token counts per LLM call).
- Gate the new mode behind a feature flag in `.map/scripts/map_orchestrator.py` (e.g., `MAP_CONTEXT_MODE=registry_focus`) so existing workflows remain unchanged until validated. Evidence supports safe evolution because orchestration is command/prompt-driven (“Orchestration logic implemented in slash command prompts (`.claude/commands/map-*.md`)”) and there is already a v1→v2 migration capability via `mapify init`.


## Per-Agent Registry with Compact Status Snapshots [2604.021]

**Benefit Hypothesis**: When running a multi-subtask workflow (e.g., /map-efficient on 5+ subtasks) with a forced multi-agent context view (REGISTRY/FOCUS), the injected prompt context size for non-focused agents decreases by >=30% versus the current approach, while maintaining Monitor approval rate (target >=80% first try as stated in “Success Metrics”).
**Confidence**: 0.66
**Reasoning**: The architecture already uses file-based state and step injection to avoid attention dilution and token bloat (“Hook Output Example… injected into system prompt before EVERY tool call”; “Context-Aware Step Injection… only relevant context” and “active window”). However, the brief does not describe any lightweight mechanism to represent other agents beyond step_state/progress/task_plan injection. The proposed per-agent registry directly complements the existing FOCUS context concept by turning “other agents” into <=200-token snapshots, aligning with the brief’s goals of reducing context size on long workflows (“attention dilution… attention dilution → Claude skips critical workflow steps like research and self-audit… command file tokens… down…; Recitation Pattern; Context-Aware Step Injection”).
**Why Not Already Tried**: The brief covers recitation, active-window injection, compaction resilience, and structured workflow logging, but it does not mention an explicit per-agent registry artifact or heartbeat snapshot mechanism. The existing step_state.json/progress.md approach tracks workflow progress, yet it is not described as an agent-by-agent compact status registry usable as a sub-linear context representation in REGISTRY/FOCUS modes.

### Proposed Changes

- Add a new on-disk artifact for compact monitoring snapshots: `.map/<branch>/agent_registry.json` (or `.map/workflow_logs/registry_<task_id>.jsonl`). Each entry must be <=200 tokens per the idea and include: `agent_id`, `current_step` (string), `state` (RUNNING/BLOCKED/WAITING/COMPLETE), `last_output_summary`, `urgency` (derived from risk escalation + current orchestrator gate).
- Extend the orchestrator/state-machine described in `State Machine (.map/scripts/map_orchestrator.py)` to update the registry after every phase transition (e.g., after `DECOMPOSE`, after `RESEARCH` conditional, after `ACTOR`, after `MONITOR`, after `PREDICTOR` when called). Use the existing checkpointing mechanisms already described: `.map/progress.md` and `.map/<branch>/step_state.json` as the source of truth, but write the registry as a compact derivative for fast monitoring.
- Add heartbeat writes inside the per-step runner used by `workflow-context-injector.py`-driven hook injections: ensure the PreToolUse hook can inject a compact “registry view” alongside the existing step reminder before EVERY tool call (the brief says injected reminders happen before EVERY tool call).
- Implement REGISTRY/FOCUS context modes by adding a context builder hook alongside the existing context injection described in “Context-Aware Step Injection (Phase 1.2)”: in FOCUS mode include full context only for the current agent, and for other agents include only their registry entries (compressed).
- Wire registry updates into `MapWorkflowLogger` since the brief already has structured logging in `.map/workflow_logs/` (“Workflow Logging (Phase 1.2)” includes a JSON log format). Specifically, add registry snapshots as a new top-level field in the per-subtask log, and also log the registry token size for regression detection.
- Add deterministic tests for size control: unit test that generated registry context stays under a target token budget for N agents (e.g., <= (base_focus_tokens + 25*N tokens, aligning with the idea’s stated efficiency goal). Use the existing token-economy/efficiency emphasis (“Token Economics” and attention focus results).


## Agent-Triggered Asymmetric Context Isolation [2604.020]

**Benefit Hypothesis**: In scenarios where the workflow currently would include multi-agent context or plan-wide context, the next tool call after a steering interaction will show reduced context size and improved decision accuracy: specifically, for /map-review verdict generation, the rate of incorrect “PROCEED” decisions (where Monitor/Evaluator should trigger REVISE/BLOCK per the brief’s verdict logic) drops by >=10% in an A/B run across 20 review tasks.
**Confidence**: 0.61
**Reasoning**: The architecture already implements context engineering via “Context-Aware Step Injection” with an “active window” that injects a structured map_context block for the current Actor and upstream results from dependencies (“Upstream Results — only results from dependency subtasks”). It also describes a desire to avoid skipping research/self-audit and to reduce token bloat. However, the brief’s context strategy is still primarily goal/progress/subtask-based, not agent-triggered asymmetric isolation. The proposed STEERING_REQUEST mechanism is directly aligned with the brief’s existing conditional orchestration behavior (e.g., Predictor called only if risk/escalation is triggered) and with the need to keep only the most relevant context (“no step skipping” enforced by state machine; strict ordering in Orchestration Model).
**Why Not Already Tried**: The brief describes sequential orchestration with strict agent ordering and conditional routing (e.g., conditional Predictor) but does not describe an agent-emitted steering interaction that dynamically changes context composition mid-workflow. Existing FOCUS logic is described at a high level (“Two-layer ‘active window’ injection”) but not as agent-triggered asymmetric isolation driven by a steering request event.

### Proposed Changes

- Define a new orchestrator “STEERING_REQUEST” event contract (JSON schema) that any agent (primarily Actor/Monitor/Predictor/Evaluator/Synthesizer) can emit at deterministic decision points when it cannot proceed autonomously. Include: `requesting_agent_id`, `requested_agent_type` (e.g., predictor/security auditor), `question`, `urgency`, and `blocking` boolean plus an excerpt (the idea’s “context excerpt”).
- Implement asymmetric context routing in the orchestrator by adding a FOCUS/REGISTRY composition function that matches the idea’s rule: on STEERING_REQUEST, transition immediately to a FOCUS mode containing full requesting-agent context (F(ai)) and compressed registry entries for other agents (R-i). This should be implemented alongside the existing context injection described in “Context-Aware Step Injection (Phase 1.2)” where hooks and Actor prompt layers already build context blocks.
- Connect steering triggers to existing orchestration conditions already described: (a) Predictor is called conditionally in /map-efficient when `risk_level` is high/medium or Monitor sets `escalation_required=true`; (b) /map-debug requires full pipeline; (c) /map-review parallel agents + verdict logic includes BLOCK/REVISE/PROCEED thresholds. Use these as entry points to emit STEERING_REQUEST rather than always relying on pre-defined fixed sequences.
- Add a deterministic “no cross-agent contamination” guard: ensure that while in FOCUS mode the orchestrator does not include raw outputs for other agents—only registry entries (from idea 2604.021) or existing minimal summaries. This satisfies the brief’s stated intent of avoiding token waste and attention dilution (“active window injection that shows only relevant context” and “dependency results passed explicitly”).
- Update the step_state.json schema (or create a parallel file under `.map/<branch>/`) to store the last steering target and the mode used so resumption works after compaction (the brief emphasizes recovery persistence via `.map/progress.md` and automatic resume).
- Add integration tests: simulate a steering request and assert that the next tool call’s injected context contains: (1) full requesting-agent focus block; (2) only compact registry entries for non-requesting agents; and (3) does not exceed the deterministic token budget you enforce (see idea 2604.023) before every LLM call.


## Deterministic Token Budget Enforcement [2604.023]

**Benefit Hypothesis**: Across workflows with >=10 subtasks, the framework will never exceed the configured prompt/token budget before LLM calls (measured by the deterministic counter), reducing context-window truncation-related failures by >=20% (operationally: fewer Monitor rejections attributed to missing context/dependency info) while keeping iteration count <3 per subtask as targeted.
**Confidence**: 0.68
**Reasoning**: The brief highlights token economics and context-window problems: long command files cause attention dilution, and the system relies on context injection to keep goals fresh (“Hook Output Example… reminder before EVERY tool call”; “command file tokens… down from ~5.4K to ~1.75K”; “Recitation Pattern… -20–30% token usage”; “active window injection… only relevant context”). However, the brief also describes best-effort context blocks (“best-effort” target <=4000 tokens in Context-Aware Step Injection) and does not state a hard, deterministic enforcement that guarantees `|C| ≤ T` prior to every tool call. Deterministic token budget enforcement directly operationalizes the architecture’s token-management intent.
**Why Not Already Tried**: The current architecture already implements token reductions through step-aware injection, recitation, compaction resilience, and template optimization, but it does not explicitly guarantee an invariant via deterministic counting before each tool call. The described mechanisms are optimizations; deterministic enforcement is a stricter missing layer.

### Proposed Changes

- Implement a deterministic token-budget enforcer in the context builder path that runs before every LLM/agent tool call (the architecture already emphasizes structured state, hook injection, and pre-tool-call reminders; this adds a hard constraint). Integrate it into the place where map_step_runner.py builds map_context blocks (“Built by build_context_block() in map_step_runner.py”).
- Create a utility (e.g., `src/mapify_cli/token_budget.py`) with functions: `count_tokens(text, model)` (use the provider’s tokenizer if available; otherwise a calibrated estimator), and `enforce_budget(focus_context, registry_entries, budget_tokens)` with the rule from the idea: never truncate F(ai) (focus context), progressively truncate lower-urgency registry entries first until within budget.
- Add a “token budget manifest” that is stored per workflow in `.map/<branch>/token_budget.json` including the configured budgets per agent/tool and the last measured token counts for each call. This supports observability since the brief already logs workflow metrics to `.claude/metrics/agent_metrics.jsonl` and stores structured workflow logs.
- Extend the PreToolUse hook `workflow-context-injector.py` to include the deterministic token budget decision outcome (e.g., `budget_action: truncated_registry` or `budget_action: none`) in the injected reminder block so that step compliance and context completeness can be audited.
- Add unit tests and property-based tests ensuring the invariant from the idea: `|C| ≤ T` before every LLM call “without exception.” Also test that truncation does not occur in the focus context and only affects registry/non-focused entries.
- Add end-to-end test harness: run a known multi-subtask workflow with increasing N (e.g., 3, 5, 10 subtasks) and verify (a) the deterministic budget never exceeds the configured T, and (b) Monitor approval rates remain near baseline target (>80% first try as stated in “Success Metrics”).

## High-Urgency Preemption Protocol for Focus Sessions [2604.022]

**Benefit Hypothesis**: Interrupt handling latency for HIGH-urgency steering will drop from ‘wait-until-current-focus-completes’ to ‘immediate transition within one orchestration cycle’ (measurable via timestamps in `.map/workflow_logs/*.json`), while maintaining state continuity (the resumed session reaches the same next step id and does not violate the step sequencing enforced by `.map/<branch>/step_state.json`).
**Confidence**: 0.62
**Reasoning**: This idea is directly motivated by the architecture’s reliance on strict orchestration and state continuity: orchestration is defined in command prompts (`.claude/commands/map-*.md`) with strict agent ordering, while workflow checkpointing is file-based (`.map/progress.md`, `.map/<branch>/task_plan_*.md`) to survive context compaction. The architecture also emphasizes “no step skipping” enforced by a state machine (`.map/scripts/map_orchestrator.py` with `step_state.json`) and provides an explicit resume pattern (`/map-resume` parsing `.map/progress.md`). A preemption protocol fits naturally: it can reuse the same persistence and resume primitives to interrupt only on HIGH urgency without breaking the step sequencing guarantees.
**Why Not Already Tried**: The tried/completed ideas list contains `2604.019`, `2604.020`, `2604.021`, `2604.023`, but the architecture brief provided does not mention any interrupt/preemption mechanism or a steering-request registry/queue. Given the existing focus on reducing context dilution with PreToolUse hooks and state-machine step enforcement (and the current assumption that orchestration flows sequentially with controlled step skipping), preemption likely wasn’t implemented yet because it requires additional orchestration-layer concurrency/interrupt handling beyond the current sequential workflow design.

### Proposed Changes

- Introduce an explicit ORCHESTRATOR session state machine with three urgency levels (LOW/MEDIUM/HIGH), and wire it into the existing state persistence design under `.map/` (e.g., checkpoint interrupted sessions via `.map/progress.md` + an additional `.map/focus_sessions/<id>/preempt_state.json`). This should align with the architecture’s existing checkpointing approach: `.map/progress.md` for workflow checkpointing and `.map/<branch>/task_plan_*.md` for plan persistence.
- Define the exact interrupt hook/entrypoint to listen for `STEERING_REQUEST` during active FOCUS mode, and implement queue semantics per architecture brief: HIGH preempts immediately; MEDIUM queue; LOW batch. This should be implemented alongside current “session start must always succeed” behavior described for hooks (hooks must not block session start; they “always succeed” and return continue).
- When HIGH urgency steering arrives during FOCUS, persist the current partial steering state for the interrupted focus agent (required by the idea) and transition to a new FOCUS context for the preempting agent. Reuse the existing file-based persistence principle (“Conversation memory clears on compaction; file system persists forever”) by storing the interrupted agent’s state to disk so it can survive compaction and long tool sessions.
- After the HIGH steering completes, explicitly resume the interrupted session if it is still pending. Use the existing resume UX concept from `/map-resume` (“detects `.map/progress.md` checkpoint and offers to resume incomplete workflow with a Y/n prompt”) but apply it internally for FOCUS sessions: auto-resume if pending; otherwise mark superseded using the same terminal status vocabulary already defined in state artifacts (`superseded`).
- Add logging and testability for preemption: extend the existing structured workflow logging under `.map/workflow_logs/` (e.g., `MapWorkflowLogger`) to record preemption events (interrupt time, urgency level, interrupted session id, resumed/not resumed reason). Then add integration tests to simulate: (1) HIGH steering during an active Actor/Monitor loop, (2) MEDIUM queued steering, (3) LOW batched steering, and verify no step skipping occurs (consistent with the architecture’s “Enforces Sequential execution, no step skipping” via `step_state.json`).


## Multi-Phase Evaluation for Context Management Mechanisms [2604.024]

**Benefit Hypothesis**: Hypothesis: a multi-phase, agent-scaling evaluation that uses MAP’s existing workflow logging artifacts will identify which context-management mechanism(s) drive improvements in compliance and approval rates, and will quantify whether step-compliance gains (reported from hook injection: ~20%→~85% predicted) generalize across N∈{3,5,10} and varying dependency/risk structures.
**Confidence**: 0.72
**Reasoning**: The architecture explicitly highlights context-management mechanisms and claims measurable improvements: (1) constant reminder hook injection “injects: ~150 token reminder before EVERY tool call” with predicted step compliance “~85% (predicted)” versus “~20%” before, (2) Recitation Pattern updating “.map/progress.md … updated before each step,” and (3) Context-Aware Step Injection that limits injected context via “active window” for token savings. The pre-approved idea’s methodology (multi-phase scaling with agent counts N, heterogeneity, decision density D, and LLM-as-judge) directly matches these stated variables and ensures the claimed robustness of context mechanisms is validated using existing artifacts like “.map/workflow_logs/” and “Metrics tracked in .claude/metrics/agent_metrics.jsonl.”
**Why Not Already Tried**: The provided architecture evidence describes the mechanisms (hook injection, recitation, step injection, compaction resilience) and reports initial token/accuracy outcomes, but there is no evidence of a structured, four-phase experimental harness that systematically varies N, heterogeneity/adversarial dependency graphs, and decision density up to D=15, nor evidence of an LLM-as-judge independent validation pipeline. Existing scripts mention template linting and metrics analysis, but not a dedicated multi-phase evaluation framework tailored to context mechanisms.

### Proposed Changes

- Create an automated evaluation harness that runs synthetic workflow scenarios targeting MAP’s context-management mechanisms: (a) v2 pre-tool hook constant reminders, (b) Recitation Pattern (.map/progress.md updates), (c) Context-Aware Step Injection (Actor prompt + active window), and (d) Compaction resilience + /map-resume. Use the architecture’s own logging artifacts as ground truth ("Workflow logs in .map/workflow_logs/" and the detailed log format under Phase 1.2).
- Implement a 4-phase experiment runner exactly as proposed: Phase 1 scaling with N ∈ {3,5,10} agents where the runner executes MAP workflows in variants that correspond to the architecture’s distinct pipelines (e.g., /map-fast has 3 agents, /map-efficient has 4–6, /map-debug has 5 agents, /map-review has 3 parallel reviewer agents plus orchestration). Phase 2 add heterogeneity and adversarial dependency structures by generating TaskDecomposer plans with varying dependency graphs (explicitly leverage “dependency tracking” from TaskDecomposer) and by introducing risky subtasks to trigger conditional Predictor (“Only called if … risk_level='high'/'medium' OR monitor_output.escalation_required”). Phase 3 scale decision density D up to 15 by inserting additional step gating prompts in the orchestration layer (tie to “PreToolUse hook injects ~150 token reminder before EVERY tool call” and the step_state enforced sequencing in “State file: .map/<branch>/step_state.json”). Phase 4 run LLM-as-judge independent metric validation by adding a “judge” job that parses the JSON workflow logs and compares measured outcomes with judge-rated correctness/compliance (architecture already has “Metrics tracked in .claude/metrics/agent_metrics.jsonl” and “FinalVerifier … verifies the ENTIRE task goal is achieved”).
- Define and implement measurable KPIs directly from the architecture’s stated success metrics and artifacts: Monitor approval rate (>80%), Evaluator scores average (>7.0/10), iteration count (<3 per subtask), knowledge growth (increase in high-quality patterns), and Step compliance (architecture reports “Step compliance ~20% before … ~85% predicted after”). Record per-run outputs to the existing metrics pipeline and artifacts: state_<branch>.json, verification_results_<branch>.json, repo_insight_<branch>.json, and especially .map/workflow_logs/*.json. Ensure each run produces a machine-readable summary for the judge.
- Add a regression-test gate for the context system: wire the evaluation harness into the existing template validation + CI integration points (there is an explicit linter script “python scripts/lint-agent-templates.py” and template pre-commit hook; additionally, MAP already persists machine-readable verification results for CI/CD via verification_results_<branch>.json). Fail the evaluation job if step compliance drops below a threshold (e.g., <80% for reminder/hook mechanisms) or if Monitor approval rate drops below baseline by a fixed margin.
- Document a single command (e.g., `make eval-context`) that runs all four phases and emits a results report: per-phase metric tables, confidence intervals, and a diff against previous runs. Use the architecture’s JSON logging schema examples and “scripts/analyze-metrics.py” as the reporting foundation.


## Family-specific scaling analysis for LLM evaluation [2604.014]

**Benefit Hypothesis**: For at least one agent role (e.g., Predictor or Evaluator), family-specific analysis will reduce the average number of Actor→Monitor iterations per subtask by >=10% (or increase Monitor approval rate by >=5 percentage points) compared to decisions made using cross-family/general heuristics, evaluated over the same set of workflows and compared via `python scripts/analyze-metrics.py` outputs.
**Confidence**: 0.62
**Reasoning**: This project explicitly relies on per-agent model selection and quality/cost tradeoffs: it lists current model assignments (TaskDecomposer/Actor/Monitor/Predictor/Evaluator/Reflector etc.) and the ability to downgrade models (“Safe to downgrade to Haiku: Predictor, Evaluator…”). It also defines KPI targets and tracking via `python scripts/analyze-metrics.py` and mentions metrics stored in `.claude/metrics/agent_metrics.jsonl` plus workflow logs in `.map/workflow_logs/`. However, the architecture brief does not describe any method for analyzing scaling behavior by model family; the pre-approved idea argues parameter count/family effects matter more than size alone. Therefore, adding family-specific scaling analysis aligns with the architecture’s existing metrics/selection mechanisms and improves the model-choice loop that drives token/performance tradeoffs.
**Why Not Already Tried**: The brief provides a roadmap for context engineering (checkpointing, MCP caching, search, pattern variation) and template maintenance, but it does not mention any prior analytics that segment performance by model family. The only analytics mentioned are general KPI tracking (`scripts/analyze-metrics.py`) without family-stratified scaling curves, so this family-specific scaling approach has not yet been implemented.

### Proposed Changes

- Add a per-agent, per-model-family evaluation mode to `scripts/analyze-metrics.py` that groups metrics by the agent’s configured model (from `.claude/agents/{agent}.md` frontmatter) and by a “model family” label (derived from model IDs).
- Extend the logged metrics schema inputs (from the existing `.claude/metrics/agent_metrics.jsonl` and the workflow logs in `.map/workflow_logs/*.json`) to include `model_id`, `model_family`, and `agent_name` for each agent run; ensure these values are captured at orchestration time (where the architecture already tracks metrics under `.claude/metrics/agent_metrics.jsonl`).
- Introduce a new report command: `python scripts/scale_analysis.py --metric monitor_approval_rate --group-by model_family --workflow map-efficient` that outputs family-specific curves such as (a) first-try Monitor approval rate vs. model_family/model_id, and (b) “iterations per subtask” vs. model_family/model_id, using the existing KPIs: Monitor approval rate >80%, Evaluator >7.0/10, iterations <3 per subtask.
- Update model selection guidance in `Customization Guide`/`USAGE` so that when choosing between models for Predictors/Evaluators (already described as `Sonnet` with `Opus` for `DebateArbiter` and the ability to downgrade to `Haiku`), the decision is based on family-specific baselines rather than general parameter-count assumptions; the selection heuristic should use the new family reports to decide “downgrade within same family is safe” vs “cross-family downgrade is risky.”
- Add regression tests for the analytics tooling (not the agents) that validate the grouping logic and curve output determinism using a small fixture dataset that mimics `.claude/metrics/agent_metrics.jsonl` records and workflow-log JSON structure from `.map/workflow_logs/`.json.


## Address observability and resiliency as critical API NFRs [2604.017]

**Benefit Hypothesis**: By making observability/resiliency signals machine-readable in a new run_health_report artifact and extending existing logging, the system will reduce mean time to diagnose failed workflows and increase successful resumption rates after compaction by enabling consistent, testable detection of where resiliency degraded (e.g., hook injection skipped, Predictor skipped, Monitor retry counts). Testable by: (a) adding unit/integration tests that check artifact presence and fields for multiple terminal_status paths, and (b) running scripts/analyze-metrics.py to verify failure post-mortem time decreases when comparing pre/post changes using the new JSON logs.
**Confidence**: 0.66
**Reasoning**: The architecture already treats resiliency/observability as important but primarily as implementation detail: workflows persist state to disk via .map/progress.md and state_<branch>.json (State Artifact + terminal_status table), hooks are explicitly non-blocking and security validated with a 4-layer approach (path traversal/size/UTF-8/control chars) and "Session start must always succeed" in the bash hook section, and structured workflow logging exists via MapWorkflowLogger with workflow context in .map/workflow_logs/. However, the brief does not define a single first-class, end-to-end "health report" artifact nor a schema that ties these signals together per run. This limits the ability to reliably assert resiliency behavior across workflows and to automate diagnosis. The proposed changes directly build on the existing artifacts (state_<branch>.json; verification_results_<branch>.json) and the documented hook resiliency behavior (skip injection but continue; exit 0; validation constraints) to make it measurable and enforceable in CI.
**Why Not Already Tried**: Completed/attempted ideas listed (2604.019, 2604.020, 2604.021, 2604.023) do not include a gap that consolidates resiliency/observability into a single standardized, CI-validated artifact. The architecture evidence shows logging and hook resiliency exist, but they are scattered across .map/progress.md, state_<branch>.json, and .map/workflow_logs/ without a unified health report schema. The missing piece is an explicit cross-workflow contract and CI checks that validate resiliency behavior end-to-end; that integration appears absent from the provided evidence of already completed ideas.

### Proposed Changes

- Add a first-class "run_health_report_<branch>.json" artifact generated at workflow end (or on early termination) containing: terminal_status from STATE_ARTIFACT_SCHEMA, hook-injection outcomes, number of tool calls, max iteration reached (Actor↔Monitor loop cap is 3–5 per architecture brief), and whether FinalVerifier was executed (FinalVerifier is mandatory in /map-efficient). Store under .map/workflow_logs/ alongside existing MapWorkflowLogger outputs.
- Extend MapWorkflowLogger (scripts/utils/map_workflow_logger.py) to record per-subtask "resiliency signals": whether Predictor was called (conditional in /map-efficient based on risk_level/escalation_required), number of validation retries (Monitor retry up to 5 times in architecture brief), and whether Predictor/Evaluator were skipped (explicitly stated skip rules for /map-fast and /map-efficient).
- Introduce a fault-tolerance "graceful degradation contract" for hook injection in workflow-context-injector.py: instead of only non-blocking behavior (exit 0; skip injection on validator failures), explicitly emit a structured per-tool-call status field into step_state.json (e.g., research_agent_called=true/false, injection_status=skipped|injected|sanitized) derived from the hook’s existing 4-layer validation (path traversal, size bomb, UTF-8, content sanitization).
- Add CI assertions that the resiliency artifacts are always produced: for workflows using AI agents (/map-efficient, /map-debug, /map-review, /map-learn), validate the health report JSON exists and includes terminal_status values (pending/complete/blocked/won't_do/superseded) exactly as specified in the state artifact section.
- Create a small set of resiliency regression tests: (1) simulate compaction/no checkpoint and confirm hook injection continues without blocking session start (architecture explicitly says session start must always succeed), (2) simulate oversized checkpoint file >256KB and confirm injection is skipped but workflow proceeds, (3) simulate invalid UTF-8 and confirm injection is rejected but session continues, using the existing security validation rules and stated performance characteristics (e.g., <0.5s total hook time).


## Claude 4.6 command simplification and verb calibration [2604.025]

**Benefit Hypothesis**: Rewriting MAP slash-command prompts to use targeted, high-signal guardrails instead of blanket prohibitions will reduce unnecessary subagent/tool overtriggering and lower median workflow latency without hurting sequencing compliance. A reasonable target is a 10-15% reduction in average tool calls for `/map-fast`, `/map-debug`, and `/map-review` while preserving the current hard-stop guarantees for Monitor failures and irreversible release actions.
**Confidence**: 0.76
**Reasoning**: Anthropic’s prompting guidance for Claude 4.6 explicitly warns that prompts written to fight under-triggering in older models can now cause overtriggering. MAP’s command set still leans heavily on that older style: a quick audit of `.claude/commands/*.md` found 40 occurrences of `CRITICAL`, `MUST`, `ABSOLUTELY FORBIDDEN`, or `STRICTLY PROHIBITED`. This is especially visible in `/map-debug`, `/map-release`, `/map-efficient`, and `/map-tdd`, where large “forbidden” blocks are mixed with command semantics that are not actually high-risk. Some hard constraints are valid, but the current wording likely amplifies Claude 4.6’s tendency to over-explore, over-call agents, and spend tokens policing itself instead of executing.
**Why Not Already Tried**: These command prompts appear to have been tuned around earlier MAP pain points such as skipped steps, skipped research, and missing Monitor passes. The architecture solved those failures with state machines and hooks, but the prompt language remained maximally forceful. The missing adaptation is recalibrating prompt tone now that orchestration safety is enforced elsewhere.

### Proposed Changes

- Create a shared “command guardrail baseline” snippet used by all slash commands, with normal language such as “Use the required agent when…” and “Ask before irreversible actions…”, and reserve all-caps hard-stop phrasing for true hard-stop cases only: `Monitor.valid=false`, tag push/release, destructive state resets, and user-confirmation gates.
- Rewrite command intros to replace negative framing (“ABSOLUTELY FORBIDDEN”, “NO ADDITIONAL OPTIMIZATION ALLOWED”) with positive, contextual instructions that explain why the rule exists. Anthropic’s guidance explicitly recommends motivation/context over bare prohibitions.
- Split each command’s safety policy into two tiers: `non_negotiable_rules` and `default_behavior`. This keeps truly critical constraints visible without making every instruction look equally severe.
- Add a targeted “when not to do extra work” clause to `/map-fast`, `/map-check`, `/map-resume`, and `/map-task`, so the model does not over-research or over-decompose simple requests just because a long prompt exists.
- Add prompt-lint checks that fail if command files exceed a configurable threshold of blanket modal language (`MUST`, `NEVER`, `ALWAYS`) without being under a whitelisted section such as release safety or workflow gate enforcement.


## Context-first XML envelopes for slash commands [2604.026]

**Benefit Hypothesis**: Standardizing MAP command prompts around a shared XML envelope and moving long-form context above instructions will improve requirement retention and reduce ambiguous agent output on long-context tasks such as `/map-plan`, `/map-review`, `/map-debug`, and `/map-efficient`. The success metric is fewer dropped acceptance criteria in decompositions and fewer review/debug outputs that miss the primary artifact set.
**Confidence**: 0.79
**Reasoning**: Anthropic’s guide is explicit on two points: for long contexts, put documents/data first and put the query at the end; and structure mixed prompt content with consistent XML tags. MAP only applies that pattern partially today. `/map-efficient` and `/map-tdd` use some XML blocks (`<MAP_Contract>`, `<map_context>`, `<MAP_Written>`), but most commands still rely on ad hoc prose and markdown. `/map-review`, `/map-debug`, `/map-fast`, and large parts of `/map-plan` pass instructions, policies, and data in inconsistent layouts, which increases prompt ambiguity exactly in the commands that carry the most context.
**Why Not Already Tried**: MAP already invested in state injection and context-window management, so the next iteration naturally focused on orchestration and hooks rather than prompt formatting. The remaining gap is not “more context”, but a more consistent and parseable arrangement of the context that already exists.

### Proposed Changes

- Introduce a shared slash-command prompt envelope with tags such as `<task>`, `<workflow_policy>`, `<artifacts>`, `<constraints>`, `<expected_output>`, and `<decision_rule>`, and apply it consistently across all `.claude/commands/map-*.md`.
- For any prompt that includes large artifacts, move those artifacts to the top of the actual subagent prompt. For example, wrap plan specs, diffs, findings files, and prior review handoffs in `<documents>` or `<artifacts>` blocks before the instructions and query.
- Refactor `/map-review` so the canonical handoff, diff, and review preferences are passed as separate tagged sections rather than inline prose. Do the same for `/map-plan` when passing spec + findings + architecture graph to the decomposer.
- Replace ad hoc markdown headings like “**Context:**” or “**Task:**” inside quoted subagent prompts with explicit machine-readable tags. This aligns with Anthropic’s guidance that XML reduces misinterpretation when instructions and variable input are mixed.
- Centralize the common envelope in a small template helper or generator so the structure is maintained in one place and synced into `src/mapify_cli/templates/commands/`.


## Few-shot command examples and evidence-quoted outputs [2604.027]

**Benefit Hypothesis**: Adding a compact library of few-shot examples and making evidence extraction explicit before judgment will reduce malformed JSON, unsupported verdicts, and vague decomposition/review outputs. A practical target is fewer schema-correction retries and a measurable increase in outputs that include concrete file/line grounding on the first pass.
**Confidence**: 0.83
**Reasoning**: Anthropic’s guide recommends 3-5 examples for reliability and suggests asking the model to quote relevant source material before reasoning on long documents. MAP currently uses neither pattern consistently. A command audit found zero `<example>` or `<examples>` tags across `.claude/commands/*.md`, `.claude/settings.json`, and `.claude/workflow-rules.json`, despite at least 12 separate places where commands say “Output JSON with …”. That means most agent contracts depend on schema prose alone. At the same time, review, debug, and planning prompts often ask for judgments without first requiring quoted evidence from files, diffs, or specs.
**Why Not Already Tried**: MAP already has extensive schema descriptions and relies on agent specialization, which may have seemed sufficient. Claude 4.6’s prompting guidance changes the tradeoff: examples are now a relatively cheap way to stabilize both structure and tone, especially for tool-heavy agent systems.

### Proposed Changes

- Add a shared examples section for the most reused contracts: TaskDecomposer output, Monitor verdicts, Predictor risk outputs, Evaluator scorecards, and Reflector lessons. Keep each example short and diverse rather than exhaustive.
- For `/map-review`, require each agent to emit an `evidence` or `quotes` array before any verdict fields. Each item should include `file_path`, `line_range` or diff hunk reference, and a short note explaining relevance.
- For `/map-debug` investigation steps, require the actor to quote the exact error/log/code fragments that support the proposed root cause before proposing the fix path.
- For `/map-plan`, require the spec-review Monitor to cite spec sections or lines for every HIGH-severity gap so the user resolves concrete contradictions rather than generic warnings.
- Extend template linting so command files that define a new JSON contract without either a reusable schema reference or at least one compact example are flagged for review.


## Action-first tool use in lightweight workflows [2604.028]

**Benefit Hypothesis**: Converting `/map-fast` and `/map-debug` from “serialize full file contents into JSON” workflows to direct tool-using workflows will reduce prompt size, reduce patch drift on large files, and make lightweight workflows more consistent with Claude 4.6’s stronger tool-use behavior. The expected result is lower token usage per iteration and fewer failures caused by stale file snapshots between Actor and Apply steps.
**Confidence**: 0.81
**Reasoning**: Anthropic’s guidance explicitly says that if you want Claude to act, tell it to act; otherwise it may suggest instead of implementing. MAP applies that principle inconsistently. `/map-efficient` already instructs the actor to “Implement and APPLY CODE with Edit/Write tools”, but `/map-fast` and `/map-debug` still ask the actor to return `code_changes` plus full file contents, after which another step applies them. That is an older, serialization-heavy workflow style. It wastes context, scales poorly with large files, and creates opportunities for the filesystem to diverge between generation and application.
**Why Not Already Tried**: The lighter workflows were likely created as low-overhead variants before tool-acting reliability improved. MAP later evolved `/map-efficient` toward direct tool use, but the smaller workflows did not receive the same modernization pass.

### Proposed Changes

- Update `/map-fast` and `/map-debug` so write-capable Actor steps read relevant files, edit them directly with tools, and return only a compact execution summary: `approach`, `files_changed`, `tests_run`, `remaining_risks`.
- Remove “Provide FULL file content” requirements from lightweight command prompts. Retain structured summaries, but do not force the model to serialize entire file bodies when the tool layer can edit safely.
- Align Monitor prompts in those workflows with the `written files + contract + validation` pattern already used in `/map-efficient`, so the validator reads actual repo state instead of pasted Actor JSON.
- Keep planning-only and analysis-only phases explicitly read-only. The goal is not “always edit”, but consistent action-first behavior whenever the phase is supposed to modify code.
- Add regression cases for files that change between Actor proposal and application, and confirm that the action-first flow eliminates those stale-snapshot failures.


## Command-specific thinking and parallelism profiles [2604.029]

**Benefit Hypothesis**: Adding explicit thinking/effort and parallelism guidance per workflow will reduce latency and wasted reasoning on simple commands while preserving deeper reasoning for plan/review/release flows. Success would show up as lower runtime for `/map-fast`, `/map-check`, and `/map-resume` without lowering verification quality, plus fewer unstable parallel execution paths in commands that mix sequential and parallel logic.
**Confidence**: 0.74
**Reasoning**: Anthropic’s guide recommends adaptive thinking with explicit effort calibration, and it also warns that Claude 4.6 can both overthink and over-parallelize if prompted too aggressively. MAP’s command layer currently lacks a consistent command-specific thinking policy. It also mixes several parallelism styles: `/map-review` requires three agent calls in one message; `/map-release` says validation gates should run in parallel where possible; `/map-efficient` has both sequential-by-default language and elaborate parallel-wave exceptions. The missing piece is a stable per-command policy that says when to think more, when to answer directly, and when parallelism is worth the complexity.
**Why Not Already Tried**: Existing MAP work focused on orchestrator correctness and state continuity, not on prompt-level effort calibration. Earlier Claude generations also had less nuanced adaptive-thinking behavior, so explicit effort profiles were less relevant than they are now.

### Proposed Changes

- Add a short `thinking_policy` block to each command: `low/direct` for `/map-fast`, `/map-check`, `/map-resume`; `medium/adaptive` for `/map-efficient`, `/map-task`, `/map-debug`; `high/adaptive` only for `/map-plan`, `/map-review`, and `/map-release`.
- Add explicit language mirroring Anthropic’s recommendation: use deeper reasoning only when it materially improves quality, otherwise respond directly and continue.
- Standardize a `parallel_tool_policy` block across commands: parallelize only when there are no dependencies, side effects are disjoint, and the result does not need immediate local integration. This should replace ad hoc wording like “in ONE message” or “parallel where possible” with a shared rule set.
- Log per-command latency, tool-call count, and parallel fan-out in `.claude/metrics/agent_metrics.jsonl` so MAP can compare pre/post prompt changes rather than tuning by anecdote.
- Update `workflow-rules.json` and command docs to reflect that “small/simple/quick” workflows should bias toward lower effort and minimal orchestration, while planning/review/release workflows intentionally permit more reasoning depth.


## Skill-first slash command consolidation [2604.030]

**Benefit Hypothesis**: Consolidating overlapping MAP command and skill definitions into a single source of truth will reduce prompt drift and make runtime behavior match author intent. The most immediate measurable benefit is eliminating the risk that a stale command prompt is silently ignored because the same-named skill takes precedence at runtime.
**Confidence**: 0.86
**Reasoning**: The official Claude Code skills documentation states that custom commands have been merged into skills, that both `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` create `/deploy`, and that if a skill and a command share the same name, the skill takes precedence. MAP currently ships both `/map-learn` as a slash command and `map-learn` as a skill, with substantial overlap but not identical content. That creates a real maintenance hazard: authors can update the command prompt and assume behavior changed, while Claude Code will continue using the skill version.
**Why Not Already Tried**: MAP appears to have grown commands first and skills later. That was reasonable before Claude Code documented skills as the preferred superset, but now the overlap is explicit platform behavior rather than an implementation detail.

### Proposed Changes

- Designate one canonical implementation for each slash surface. For `/map-learn`, either keep the skill and generate the command from it for backwards compatibility, or drop the duplicate command file entirely.
- Add a sync/lint rule that fails when a skill and command share the same invocation name but differ semantically. This should compare frontmatter intent and core body sections, not just filenames.
- Document a migration path from “command-first” to “skill-first” in `docs/USAGE.md` and `docs/ARCHITECTURE.md`, using `/map-learn` as the first concrete conversion.
- If MAP intends to keep duplicate surfaces for compatibility, generate one from the other during template build so authors never hand-edit both.


## Official-frontmatter hygiene for MAP skills [2604.031]

**Benefit Hypothesis**: Bringing MAP skill metadata in line with the official Claude Code skill frontmatter guidance will improve discoverability, autocomplete quality, and trigger accuracy, while reducing misleading or truncated descriptions. The immediate target is more reliable manual invocation and better automatic loading decisions.
**Confidence**: 0.82
**Reasoning**: The official skills docs define a broader frontmatter surface than the older open-standard validator: `disable-model-invocation`, `allowed-tools`, `hooks`, `argument-hint`, `user-invocable`, `paths`, `model`, `effort`, and `context` are all valid Claude Code fields. That means MAP’s use of `disable-model-invocation`, `allowed-tools`, and skill-local hooks is legitimate. The real issue is metadata quality. The docs also note that descriptions longer than 250 characters are truncated in the skill listing. MAP’s `map-planning` description is currently 371 characters, which means part of its trigger guidance is likely being cut off in the UI/context. It also references `map-workflows-guide` and `map-cli-reference`, which are not actually shipped in the current skill set.
**Why Not Already Tried**: Existing MAP work focused on capability and orchestration, not on the UX and trigger behavior of the skill catalog itself. The platform guidance on description truncation and invocation-control fields is also newer than many command-era prompt patterns.

### Proposed Changes

- Shorten every skill description to front-load the core use case within the first 150-200 characters, and keep the total under the official 250-character truncation threshold.
- Remove references to non-shipped skills from frontmatter descriptions, especially in `map-planning`. If those skills are planned, reference docs or concepts instead of unresolved skill names.
- Add `argument-hint` to manually invoked task skills. For example, `map-learn` should advertise something like `[workflow-summary]` so `/map-learn` is easier to use correctly from the slash menu.
- Review whether `user-invocable` and `paths` would improve future MAP skills. Reference skills that should load automatically but not clutter the slash menu can use `user-invocable: false`, while file-scoped skills can use `paths` for more precise activation.
- Add a metadata lint pass for names, description length, missing/broken cross-skill references, and unsupported frontmatter relative to MAP’s chosen target runtime.


## Explicit reference-vs-task skill architecture [2604.032]

**Benefit Hypothesis**: Reclassifying MAP skills according to the official Claude Code split between reference content and task content will reduce conceptual confusion, improve skill authoring discipline, and make MAP’s documentation match actual runtime behavior. This should lower accidental misuse of skills and make it easier to decide when a new behavior belongs in a skill versus a subagent or command.
**Confidence**: 0.84
**Reasoning**: The official docs explicitly distinguish reference skills, which add knowledge inline, from task skills, which provide step-by-step procedures and are often manually invoked with `disable-model-invocation: true`. MAP’s current `skills/README.md` still describes skills as passive documentation modules and “NOT agents”, but `map-learn` is clearly a task skill: it has a manual workflow surface, procedural steps, file writes, and an invocation-control flag. `map-planning` is closer to a hybrid reference/task guide because it explains the file-based planning model and also defines operational behavior via scripts and hooks.
**Why Not Already Tried**: MAP’s skills system was originally documented around passive guidance and auto-suggestion. Claude Code’s official skills model is broader and now makes task-like skills a first-class concept, so the original documentation model is lagging behind the platform.

### Proposed Changes

- Update `src/mapify_cli/templates/skills/README.md` and related docs to define two supported skill classes: `reference` and `task`.
- Classify `map-learn` explicitly as a manual task skill, and explain why `disable-model-invocation: true` is appropriate for it.
- Classify `map-planning` explicitly as a reference or hybrid operational skill, and document what behavior comes from SKILL instructions versus hook/script side effects.
- Add authoring guidance for future MAP skills: use reference skills for conventions, heuristics, and domain knowledge; use task skills for deterministic procedures that should behave like slash workflows.
- Reflect this taxonomy in `skill-rules.json`, tests, and any future skill-generation helpers so the distinction is operational, not just descriptive.


## Supporting-file and lifecycle optimization for skills [2604.033]

**Benefit Hypothesis**: Restructuring MAP skills around the official skill content lifecycle and supporting-file model will keep invoked skill bodies lean, reduce compaction loss, and make long-running skills more durable across sessions. The measurable outcome is a smaller average SKILL body with equal or better task completion quality.
**Confidence**: 0.77
**Reasoning**: The official docs emphasize that invoked skill content stays in the conversation, is reattached after compaction within a token budget, and should therefore keep `SKILL.md` focused while moving detailed material into supporting files. MAP already does this reasonably well for `map-planning` and parts of `map-learn`, but the skills still contain a lot of command-like procedural detail that can drift away from supporting templates and increase retained token load. The same docs also recommend referencing supporting files explicitly so Claude knows when to load them.
**Why Not Already Tried**: MAP adopted supporting scripts and templates, but not yet a systematic skill-body minimization pass informed by Claude Code’s persistence and compaction behavior.

### Proposed Changes

- Move low-frequency sections such as long examples, troubleshooting matrices, and token budget estimates out of task-heavy SKILL bodies into supporting files where practical.
- Keep the main SKILL body focused on invocation policy, decision rules, and navigation to scripts/templates/references.
- For `map-learn`, prefer a short top-level playbook plus explicit links to rule templates and any future examples/reference files, rather than embedding all operational detail inline.
- Add a “retained after invocation” lint heuristic for skills: flag large sections that are better expressed as supporting files because they do not need to remain in-context across the whole task.
- If MAP later adds more task skills, evaluate whether some should use `context: fork` and `agent` to isolate long procedures into subagent execution, as supported by the official docs.


## Skill trigger and invocation regression testing [2604.034]

**Benefit Hypothesis**: Adding skill-specific trigger and invocation tests will prevent regressions where a skill stops loading automatically, becomes too noisy, or exposes a broken slash UX. The measurable gain is earlier detection of metadata regressions before template release.
**Confidence**: 0.8
**Reasoning**: Both the official skills docs and Anthropic’s `skill-creator` guidance emphasize realistic triggering, direct invocation, and example-based validation. MAP currently tests commands heavily but has much less explicit coverage around skill trigger quality, description ergonomics, and slash invocation metadata. Given that descriptions are the primary auto-trigger surface and skills now double as commands, this is an avoidable blind spot.
**Why Not Already Tried**: Skills appear to be a newer layer in MAP than commands, and most existing validation effort has gone into prompt-template sync and workflow correctness rather than catalog behavior.

### Proposed Changes

- Add tests that validate both automatic trigger phrasing and direct `/skill-name` invocation for each shipped skill.
- Add negative-trigger tests so `map-planning` and `map-learn` do not activate on unrelated prompts.
- Test that every skill’s documented supporting files actually exist and that intra-skill references resolve.
- Add fixture-based tests for frontmatter behavior that MAP relies on: `disable-model-invocation`, `allowed-tools`, hooks, and any future `argument-hint`, `paths`, or `user-invocable` usage.
- Add a small benchmark set of realistic user utterances, following `skill-creator` guidance, to detect undertriggering and overtriggering before release.


## LEARN as a philosophical requirement with soft runtime ergonomics [2604.035]

**Benefit Hypothesis**: Treating `LEARN` as a required part of the MAP philosophy, while keeping runtime ergonomics soft and token-aware, will preserve the long-term memory benefits of the framework without making users feel forced into extra token spend on every workflow. The measurable target is higher voluntary `/map-learn` adoption on meaningful tasks and fewer repeated Monitor findings in subsequent sessions.
**Confidence**: 0.85
**Reasoning**: The philosophy document treats `LEARN` as a first-class stage in `SPEC → PLAN → TEST → CODE → REVIEW → LEARN`, explicitly stating that reusable project memory is the output of the pipeline and that re-explaining the same gotchas a week later means `LEARN` failed. At the same time, MAP users are cost-sensitive and often skip optional post-processing when it burns extra tokens. So the gap is real, but the fix should not be hard enforcement. MAP’s runtime still treats learning as a weak afterthought: `README.md` canonical flows end at `/map-review`, `docs/ARCHITECTURE.md` repeatedly calls learning “optional via /map-learn”, and `map-efficient`, `map-debug`, `map-release`, `map-resume`, and `map-fast` all frame `/map-learn` as a generic suggestion rather than a normal, cheap closeout path.
**Why Not Already Tried**: MAP intentionally decoupled Reflector from execution to save tokens and keep implementation loops faster. That optimization was correct for token economy, but it left the system without a lightweight bridge between “LEARN matters” and “users do not want mandatory extra spend”.

**Execution note:** Do not execute this umbrella item directly. Use the child slices below.

### Proposed Changes

- Keep `LEARN` mandatory in philosophy/docs, but do not block workflow completion on `/map-learn` or require an explicit skip confirmation.
- Generate a branch-scoped `learning_handoff_<branch>.md` or `.json` artifact automatically at the end of `/map-efficient`, `/map-debug`, `/map-review`, and `/map-check`, so the expensive part becomes optional execution, not manual reconstruction of context.
- Make `/map-learn` cheap and ergonomic: support prefilled invocation from the generated handoff and encourage batched learning across several workflows instead of per-run mandatory reflection.
- Update canonical docs (`README.md`, `docs/USAGE.md`, `docs/ARCHITECTURE.md`) to say: philosophically the cycle ends with `LEARN`, but runtime leaves it to the user when to pay that cost.
- Add metrics for learn adoption, deferred learn usage, and repeated learned-rule violations, so MAP can improve uptake without turning learning into a hard gate.


## Learn adoption metrics and deferred-usage tracking [2604.035-2]

**Parent:** `2604.035`
**Benefit Hypothesis**: Once branch-scoped learning handoffs exist, MAP should measure whether they are actually improving uptake and rule reuse. Tracking deferred `/map-learn` execution, handoff generation vs consumption, and repeated Monitor findings will show whether the softer runtime ergonomics materially improve memory capture instead of just creating more files.
**Confidence**: 0.72
**Reasoning**: The runtime can only tune learning ergonomics intelligently if it can observe them. Without usage metrics, MAP cannot tell whether users are deferring learning productively, silently ignoring the handoff, or repeatedly hitting the same issues despite preserved rules. The artifact manifest already has a `learn_handoff` stage, so the remaining gap is usage instrumentation rather than artifact plumbing.

### Proposed Changes

- Record when a workflow writes `learning-handoff.md` / `.json` and whether `/map-learn` later consumes that handoff.
- Add counters for immediate learn vs deferred learn vs never-used handoff.
- Track repeated Monitor findings or review issues after related learned rules already exist, so MAP can tell whether knowledge capture is actually reducing repeated mistakes.
- Surface the metrics in `.claude/metrics/agent_metrics.jsonl` or a dedicated learning metrics artifact.


## Clean-session TEST→CODE handoff for TDD workflows [2604.036]

**Benefit Hypothesis**: Forcing test authoring and implementation to happen in separate sessions/contexts will reduce “tests that merely bless the implementation”, catch spec misunderstandings earlier, and improve contract quality on risky subtasks. The measurable target is fewer trivial/pass-without-code tests and fewer post-implementation revisions caused by weak test contracts.
**Confidence**: 0.82
**Reasoning**: The philosophy document is explicit that tests should be written in a clean session, reviewed by a human, and then implemented in another session so the model does not see its own code while inventing tests. MAP is test-first, but not context-isolated: `map-tdd` and `map-efficient --tdd` run `TEST_WRITER → TEST_FAIL_GATE → ACTOR` inside the same workflow state machine, and `map-tdd.md` explicitly says test phases should append to the same branch workspace rather than creating a separate artifact universe. That preserves convenience, but it does not preserve the clean-room property the philosophy relies on.
**Why Not Already Tried**: Current TDD design optimizes for continuity, lower friction, and fewer restarts. It assumes phase separation inside one workflow is enough, but the presentation’s claim is stronger: the value comes from separating contexts, not just labels.

### Proposed Changes

- Add a split-session TDD mode that stops after `TEST_FAIL_GATE`, writes a persisted `test_contract_<branch>.md` and `test_handoff_<subtask>.json`, and exits instead of continuing directly into implementation.
- Add a resume path for code generation (`/map-task`, `/map-efficient --resume-contract`, or equivalent) that loads only spec, plan, failing tests, and concise contract notes, not the full TEST_WRITER deliberation.
- Optionally require a commit checkpoint for generated tests before code implementation begins, so the test contract becomes a reviewable artifact instead of transient context.
- Introduce separate prompt personas and success criteria for test-authoring versus code-authoring, with explicit guarantees that the implementer step does not author or silently weaken tests.
- Add regression tests proving that split-session TDD survives context reset/compaction and still resumes deterministically from persisted test artifacts.


## Detached reviewer context and worktree-assisted review [2604.037]

**Benefit Hypothesis**: Reviewing from a fresh context or detached worktree instead of the implementer session will improve detection of semantic/API design issues, reduce self-review bias, and lower false `PROCEED` verdicts on non-trivial changes.
**Confidence**: 0.8
**Reasoning**: The philosophy document states `Reviewer ≠ Implementer` and recommends separate terminals/sessions via `git worktree`, precisely because many important review issues are semantic rather than syntactic. MAP’s `/map-review` already uses multiple reviewer agents and loads a review handoff, but it is still designed as an in-place command, with no strong support for isolated reviewer context. In practice that means the same session that planned or implemented the change can still be the session that drives review, which weakens the intended adversarial separation.
**Why Not Already Tried**: MAP prioritized reviewer diversity (Monitor/Predictor/Evaluator) and artifact reuse first. Context isolation ergonomics were left to the user, so the framework has strong review content but weak enforcement of reviewer independence.

### Proposed Changes

- Add a detached review mode (`/map-review --detached` or helper script) that creates a temporary read-only worktree or snapshot and runs review from that clean context.
- Build a canonical review bundle artifact that includes spec, plan, relevant tests, verification summary, review handoff, and diff, so review consumes the full contract instead of mostly reconstructing intent from the patch.
- Update reviewer prompts to explicitly state they are not the implementer and must challenge architectural shortcuts, API convention drift, and undocumented tradeoffs.
- Document when detached review is recommended or required: high-risk changes, new APIs, CRD/schema changes, security-sensitive code, and large diffs.
- Add integration tests that validate review bundle generation and detached review startup, so this mode does not become a paper feature.


## Workflow fit classifier and explicit off-ramp for trivial work [2604.038]

**Benefit Hypothesis**: A short suitability check at workflow entry will reduce unnecessary MAP overhead on trivial work, improve latency for simple tasks, and make the framework more credible for the complex tasks where it actually pays off. The measurable target is fewer low-value orchestrated runs and better task-to-workflow matching.
**Confidence**: 0.78
**Reasoning**: The philosophy document explicitly says not to drag the full framework onto README typos or 50-line scripts, and limits the strongest payoff to domains with clear models, invariants, and review cost: operators, platform tooling, API/CRD-driven systems, and backend work with real contracts. MAP documentation does distinguish `/map-fast` and `/map-efficient`, but it still mostly assumes some MAP workflow is appropriate. There is no first-class “do this directly, MAP is not needed” off-ramp in runtime behavior.
**Why Not Already Tried**: Product messaging has focused on demonstrating the power of the framework, not on teaching restraint. That is common for new systems, but it creates avoidable overhead and makes MAP look heavier than its philosophy intends.

### Proposed Changes

- Add a lightweight workflow-fit classifier to `/map-plan` and the workflow guide, using criteria such as blast radius, model complexity, expected diff size, need for explicit acceptance criteria, and cost of independent review.
- Introduce an explicit off-ramp outcome: `direct edit / no MAP orchestration recommended`, alongside the existing choices of `/map-fast`, `/map-efficient`, and `/map-tdd`.
- Update docs and skills with concrete examples of good MAP candidates versus bad ones, grounded in the same categories used in the presentation.
- Record when a task was intentionally routed away from MAP, so future tuning can compare overhead saved versus quality lost.
- Use this classifier to sharpen `/map-fast` guidance: it should be one option in the decision tree, not the silent default for every “smallish” task.


## Contract-sized subtasks and artifact stage gates [2604.039]

**Benefit Hypothesis**: Making artifact lineage and small-diff budgets explicit across workflows will reduce scope creep, oversized diffs, and stage skipping, leading to more reviewable changes and more reliable recovery. The measurable target is smaller median subtask diffs, fewer mixed-concern subtasks, and fewer workflows that reach review without a full contract trail.
**Confidence**: 0.84
**Reasoning**: The philosophy document treats MAP as a pipeline of artifacts: `SPEC` produces model + invariants, `PLAN` produces tasks, `TEST` produces executable contract, `CODE` produces passing implementation, `REVIEW` consumes spec + tests + diff, and `LEARN` produces reusable memory. It also emphasizes one logical step at a time and reviewable diffs, citing ~155-line median PRs and warning against mixing multiple architecture surfaces in one step. MAP already persists rich branch artifacts, but its runtime still leaves too much implicit: `docs/ARCHITECTURE.md` says there is no single standard workflow, `/map-fast` can implement without spec/test artifacts, and there is no explicit subtask diff budget or concern-mixing guard tied to stage completion.
**Why Not Already Tried**: MAP invested first in orchestration correctness, persistence, and agent specialization. Artifact contracts and diff-budget enforcement remained partially implied by author intent rather than enforced by the framework.

### Proposed Changes

- Add a branch-scoped `artifact_manifest.json` that records the status of spec, plan, test contract, implementation summary, review verdict, verification, and learn closeout for the current workflow.
- Require complex workflows to consume the prior stage artifact explicitly before proceeding; for example, review should load spec + tests + diff, and code execution should record which test/spec contract it is satisfying.
- Extend decomposition/planning artifacts with `expected_diff_size`, `concern_type`, and a one-concern-per-subtask rule, so Monitor/FinalVerifier can detect when a task has grown beyond “one logical step”.
- Add guardrails that warn or block when a subtask diff exceeds a configured reviewable budget or mixes incompatible concern types (for example schema + runtime + tests + docs in one subtask without justification).
- Update canonical docs so MAP has a visible default artifact pipeline even if individual commands still differ in internal implementation details.
