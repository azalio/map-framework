# Improvements Plan: Self-Execution Simulation for MAP Framework

> Note: This file is a focused research plan for self-execution simulation. For the broader product/runtime backlog, see [docs/improvement-plan.md](./improvement-plan.md).

Based on the research paper "Self-Execution Simulation Improves Coding Models" (arXiv:2604.03253v1, April 2025).

The paper demonstrates that LLMs can be trained to mentally simulate code execution (predict stdout given code + stdin), and use this capability for **self-verification** (selecting the best solution from candidates without running code) and **self-fixing** (iteratively improving code using predicted execution output instead of real execution). Key results: up to +8 points on competitive programming via self-verification, minimal simulation gap compared to real execution.

---

## 1. Mental Execution Simulation in Monitor Agent

**Priority:** High
**Complexity:** Low (prompt-only change)
**Affected files:** `.claude/agents/monitor.md`, `src/mapify_cli/templates/agents/monitor.md`

### Current State

Monitor is a purely static validator. It reads Actor's code, checks a deterministic checklist (AAG contract compliance, security gates, error handling, test coverage), and outputs `valid: true/false`. It never reasons about what the code *does at runtime* — only about what it *looks like structurally*.

This means Monitor can miss:
- Logical errors where code structure looks correct but runtime behavior is wrong (e.g., off-by-one errors, incorrect conditional ordering, wrong variable in a return statement).
- Subtle bugs where all quality gates pass but the code produces incorrect output for edge cases.
- Semantic mismatches between the AAG contract goal and actual code behavior.

### Proposed Change

Add a new verification step to the Monitor protocol — **Mental Execution Trace** — between the existing "Verify Goal is achieved" step and the quality gates. The instruction:

```
## Step 2.5: Mental Execution Simulation

Before running quality gates, mentally simulate execution of the code on representative inputs:

1. **Identify test scenarios** from the AAG contract Goal:
   - Happy path: the most common expected input
   - Edge case: boundary values, empty inputs, null/None
   - Error path: invalid input that should trigger error handling

2. **Trace execution step by step** for each scenario:
   - Walk through the code line by line
   - Track variable states at each step
   - Predict the return value or output

3. **Compare predicted output to expected output:**
   - If predicted output matches expected → continue to quality gates
   - If predicted output diverges → `valid: false` with:
     - scenario description
     - expected vs. predicted output
     - the specific line where behavior diverges

4. **Confidence threshold:**
   - If the code is too complex to simulate reliably (deep recursion,
     large number arithmetic, complex state machines with >5 states),
     note "simulation confidence: low" and proceed to quality gates
     without blocking on simulation results alone.
```

### Why This Works

The paper shows that models already have strong code simulation ability — CWM achieves 85.0 pass@1 on output prediction, and the simulation gap (simulated vs. real execution) is small. Monitor already runs on Sonnet-class models, which are capable of this type of reasoning.

The key insight from the paper: even when test cases are *already provided* for filtering, mental simulation still improves accuracy by 2-8 points. This means the simulation provides a qualitatively different signal from static analysis.

### Risks and Mitigations

- **Risk:** Increased token usage per Monitor call (mental trace is verbose).
  **Mitigation:** Only simulate on 2-3 representative scenarios, not exhaustive test suites. Add a `{{enable_mental_simulation}}` placeholder (default: `true`) to allow users to disable it for cost optimization.

- **Risk:** False negatives on complex numerical code.
  **Mitigation:** The confidence threshold (step 4) prevents blocking on unreliable simulations. The paper explicitly acknowledges this limitation.

- **Risk:** Slowing down the Actor → Monitor feedback loop.
  **Mitigation:** Mental simulation adds ~200-500 tokens to Monitor output. At Sonnet speeds, this is <2 seconds additional latency. The bug-catching value outweighs this cost.

### Validation Plan

1. Run `make render-templates` then `pytest tests/test_template_render.py -v` after changes to ensure generated trees are up to date.
2. Create a set of 5-10 test cases where the code looks structurally correct but has a logical bug (off-by-one, wrong variable, inverted condition).
3. Compare Monitor verdicts with and without mental simulation on these cases.
4. Measure token usage increase on a typical workflow run.

---

## 2. Variant Ranking via Simulated Execution in Self-MoA

**Priority:** High
**Complexity:** Medium (prompt changes to Synthesizer + Monitor in MoA mode)
**Affected files:** `.claude/agents/synthesizer.md`, `.claude/agents/monitor.md`, `src/mapify_cli/templates/agents/synthesizer.md`, `src/mapify_cli/templates/agents/monitor.md`

### Current State

Self-MoA workflow: 3×Actor → 3×Monitor → Synthesizer → Monitor.

Currently, Monitor evaluates each variant on the same static checklist. Synthesizer receives three `MonitorAnalysis` objects with `valid/invalid` verdicts and a list of identified decisions. Synthesizer then extracts decisions, resolves conflicts using a priority policy (`correctness > security > maintainability > performance`), and generates fresh unified code.

The problem: all three variants might be `valid: true` with similar static quality, but produce different runtime behavior. Synthesizer has no signal to distinguish which variant is *more correct* — it treats them as equally valid and merges decisions somewhat arbitrarily.

### Proposed Change

Introduce a **simulated execution ranking** step in the MoA flow, between 3×Monitor and Synthesizer:

```
CURRENT:  3×Actor → 3×Monitor → Synthesizer → Monitor
PROPOSED: 3×Actor → 3×Monitor → SimRank → Synthesizer → Monitor
```

SimRank is not a new agent — it is an additional instruction block added to Monitor when operating in MoA mode. When Monitor evaluates variants in MoA mode, it additionally:

1. Defines 3-5 test scenarios from the subtask requirements.
2. For each variant, mentally simulates execution on all test scenarios.
3. Counts how many test scenarios each variant passes.
4. Outputs a `simulation_rank` field (1-3, 1 = best) alongside the existing `valid` verdict.

Synthesizer then receives `simulation_rank` as an additional input and uses it to break ties:

```
### Conflict Resolution with Simulation Rank

When resolving conflicting decisions between variants:
1. Apply priority policy (correctness > security > maintainability > performance)
2. If priority policy does not resolve: prefer the decision from the
   variant with the best simulation_rank
3. If simulation_rank is tied: prefer the decision from the variant
   with fewer Monitor warnings
```

### Why This Works

The paper's best@k simulate approach shows that ranking solutions by predicted test passage consistently outperforms both random selection and shortest-first heuristics. The simulation gap is small enough that simulated rankings closely match real execution rankings.

In MAP's Self-MoA, we already generate 3 variants and evaluate them — adding simulation-based ranking gives Synthesizer an objective behavioral signal, not just structural quality metrics.

### Validation Plan

1. Identify 3 past subtasks where Self-MoA produced suboptimal synthesis (e.g., chose a structurally clean but behaviorally wrong decision).
2. Re-run with simulation ranking and compare Synthesizer output quality.
3. Measure additional token cost per MoA cycle (expected: ~30% increase in Monitor output for MoA mode).

---

## 3. Dry-Run Simulation Mode for /map-debug

**Priority:** Medium
**Complexity:** Medium (new mode in debug workflow command)
**Affected files:** `.claude/commands/map-debug.md`, `src/mapify_cli/templates/commands/map-debug.md`

### Current State

`/map-debug` workflow: TaskDecomposer → Investigation (Actor analyze → Monitor) → Fix (Actor → Monitor → Predictor → Evaluator).

The fix phase relies on Monitor's static validation and, implicitly, on the developer running tests externally. When the sandbox environment is not set up, external APIs are unavailable, or the test suite is slow, the feedback loop stalls — the developer has to manually run tests and report back.

### Proposed Change

Add a `--dry-run` flag to `/map-debug` that activates **simulated test execution** in the fix phase:

```
/map-debug --dry-run debug why payment processing fails for amounts over $1000
```

In dry-run mode, after Actor produces a fix:

1. **Test scenario extraction:** Actor (or Monitor) extracts the specific test scenarios that reproduce the bug from the investigation phase output.

2. **Mental execution of the fix:** Monitor mentally executes the fixed code on these test scenarios, step by step.

3. **Verdict with simulation trace:** Monitor outputs:
   ```json
   {
     "valid": true,
     "simulation_verdict": "fix_likely_correct",
     "simulation_confidence": 0.85,
     "scenarios_tested": [
       {
         "description": "Payment of $1500",
         "expected": "Transaction approved",
         "simulated": "Transaction approved",
         "pass": true
       },
       {
         "description": "Payment of $999",
         "expected": "Transaction approved",
         "simulated": "Transaction approved",
         "pass": true
       }
     ],
     "caveat": "Simulation only — run real tests before merging"
   }
   ```

4. **Iteration based on simulation:** If simulation predicts test failure, the fix returns to Actor with the simulated failure as feedback — exactly like Self-RLEF from the paper.

### Connection to the Paper

This mirrors the paper's Self-RLEF (Reinforcement Learning from Execution Feedback) loop, where the model iteratively generates → simulates → fixes. The paper shows this cycle improves pass rates from 57.8% (initial solution) to 63.2% (after simulated feedback), using an average of only 3.33 turns.

The key insight: per-turn context isolation. Each fix attempt gets a fresh context with only the problem description, current code, and simulated feedback — avoiding context pollution from long debugging sessions.

### Why This is Valuable for MAP

- Many MAP users work on projects where the full test suite takes minutes to run.
- Some code interacts with external services that can't be easily mocked.
- Dry-run simulation provides a fast inner feedback loop before the slower outer loop of real test execution.
- The `simulation_confidence` field makes it explicit that this is a heuristic, not a guarantee.

### Risks

- Developers might trust dry-run too much and skip real tests. The explicit `caveat` field and `--dry-run` flag naming mitigate this — it is clearly a simulation mode, not a replacement.
- Complex bugs involving concurrency, timing, or external state will not be reliably simulated. The confidence score handles this — if Monitor can't confidently simulate, it says so.

---

## 4. Predictor Enhancement: Simulated Integration Testing

**Priority:** Medium
**Complexity:** High (significant prompt changes + new analysis mode)
**Affected files:** `.claude/agents/predictor.md`, `src/mapify_cli/templates/agents/predictor.md`

### Current State

Predictor uses grep-based static analysis to find affected components after a code change. It searches for import statements, function references, and config mentions. It outputs a structured impact report with affected files, confidence levels, and recommended actions.

Predictor works at Tier 1 (grep only, 30 sec), Tier 2 (grep + cross-validation, 1-2 min), or Tier 3 (deep analysis, 3-5 min). All tiers are purely structural — they find *where* a symbol is used, not *how* a change affects runtime behavior.

### Proposed Change

Add a **Tier 2.5: Simulated Integration** step that Predictor can optionally perform when analyzing high-impact changes (breaking API changes, shared utility modifications):

```
TIER 2.5 (Simulated Integration - 2-3 min):
  For each high-impact affected file (confidence > 0.8):
    1. Read the calling function that uses the changed API
    2. Mentally simulate the calling function with the NEW signature/behavior
    3. Predict whether the call site will:
       a) Work correctly (compatible change)
       b) Throw an error (breaking change)
       c) Produce wrong results (semantic change)
    4. Output simulation_result per call site
```

This extends the existing impact report with a `simulation_results` array:

```json
{
  "affected_files": [...],
  "simulation_results": [
    {
      "file": "src/api/handlers.py",
      "function": "handle_request",
      "line": 42,
      "call_site": "result = get_weather(city)",
      "change": "get_weather now requires region parameter",
      "simulation": "TypeError: get_weather() missing required argument: 'region'",
      "severity": "breaking",
      "confidence": 0.95
    }
  ]
}
```

### Limitations

The paper works with single-file competitive programming problems. Predictor deals with multi-file projects where full simulation is impractical. This proposal limits simulation to *individual call sites* rather than full program execution — a feasible scope for current models.

This should be gated behind a `--deep-simulation` flag or only trigger automatically for changes marked as `high_risk` by the existing Predictor analysis.

### Validation Plan

1. Identify 5 past breaking changes in the MAP framework repo itself.
2. Run Predictor with and without simulated integration on each.
3. Compare: did simulation catch call sites that grep alone missed? (Expected: few new findings for typed Python, but valuable for dynamic code patterns.)

---

## 5. Full Execution Traces as Feedback (Future Research)

**Priority:** Future / Experimental
**Complexity:** High
**Affected files:** Potentially all agents

### Paper's Future Work Section

The paper's most interesting unexplored direction: using the *full rich execution simulation* (not just the final output, but the complete trace of variable states, function calls, and intermediate results) as feedback for iterative code fixing. The authors note that this could reveal:

- Cases where a test passes *for incidental reasons* (correct output, wrong logic).
- The *underlying cause* of failures, not just the symptom (wrong output).

They report preliminary difficulties training models on rich textual feedback due to teacher forcing challenges and unclear reward definitions.

### Relevance to MAP

MAP operates in a prompt-based paradigm (not fine-tuning), which actually makes this *easier* to experiment with than in the paper's training setup. The idea:

1. **Monitor generates a rich execution trace** (not just pass/fail, but variable states at key checkpoints).
2. **Actor receives the trace as feedback** when fixing issues — giving it more signal than just "test failed" or "output was X instead of Y."
3. **Evaluator uses traces** to catch incidental passes — where the code produces the correct output but through incorrect logic.

### Concrete Experiment

Add an optional `--trace` mode to Monitor's mental simulation:

```
## Trace Mode (experimental)

When {{trace_mode}} is true, produce a step-by-step execution trace:

Line 1: x = 0           → x=0
Line 2: for i in range(n) → loop starts, n=5
Line 3:   x += i*2       → iteration 0: x=0, iteration 1: x=2, ...
Line 5: return x         → x=20

Include: variable values after each assignment, loop iteration counts,
branch decisions (which if/else path taken), function call arguments
and return values.
```

This trace is then passed to Actor as structured feedback when a simulated test fails, giving Actor much richer signal for the fix.

### Why Defer This

- Token cost is very high (traces can be 5-10x the size of the code itself).
- Value is unclear without empirical testing in MAP's specific use cases.
- The paper's authors themselves report challenges with this approach.

Recommendation: implement as an opt-in experimental flag (`--trace`), collect user feedback, evaluate token cost vs. bug-fixing accuracy improvement.

---

## 6. Context Isolation in Multi-Turn Fix Loops

**Priority:** Medium-Low
**Complexity:** Low (prompt change in orchestration commands)
**Affected files:** `.claude/commands/map-efficient.md`, `.claude/commands/map-debug.md`, `src/mapify_cli/templates/commands/map-efficient.md`, `src/mapify_cli/templates/commands/map-debug.md`

### Paper Insight

The Self-RLEF approach uses per-turn context isolation: each fix attempt starts with a fresh context containing only the problem description, current code version, and the latest execution feedback. This prevents the model from being confused by the history of failed attempts.

The paper shows models use an average of 3.33 turns, and the early-exit pattern (stopping when the model believes the solution is correct) provides a good tradeoff between accuracy and compute.

### Current MAP State

In MAP's Actor → Monitor feedback loop, Actor retains the full conversation context including all previous failed attempts and Monitor feedback. This can lead to:

- **Context pollution:** Actor tries to fix issues it already fixed, or re-introduces bugs from earlier attempts.
- **Diminishing returns:** Later iterations get worse because the context is cluttered with failed approaches.
- **No early exit:** The loop runs for a fixed max iterations (3-5) even when iteration 2 was correct but Monitor was overly strict.

### Proposed Change

Modify the orchestration commands to implement **context-isolated fix iterations**:

```
## Isolated Iteration Protocol

For Actor-Monitor feedback loops (iteration > 1):

1. Start Actor with a FRESH prompt containing only:
   - Original subtask AAG contract
   - Current state of the code (latest version only)
   - Monitor's latest feedback (structured JSON, not full conversation)
   - Iteration number (e.g., "This is fix attempt 2 of 5")

2. Do NOT include:
   - Previous Actor responses
   - Previous Monitor feedback from earlier iterations
   - The original (pre-fix) code version

3. Early exit: If Monitor returns valid=true AND no HIGH severity
   warnings, exit the loop immediately (do not use remaining iterations).
```

This mirrors the paper's finding that isolated contexts with only the latest feedback produce better fixes than accumulated conversation history.

---

## Ideas from Anthropic's "Building Effective Agents" (anthropic.com/engineering)

Based on: https://www.anthropic.com/engineering/building-effective-agents

Anthropic's engineering team distilled patterns from working with dozens of teams building production agent systems. Their core thesis: the most successful implementations use simple, composable patterns rather than complex frameworks. Below is an analysis of how MAP aligns with these recommendations and where there are gaps.

### MAP's Alignment with Anthropic's Patterns

MAP already implements several of the recommended patterns:

| Anthropic Pattern | MAP Implementation | Status |
|---|---|---|
| **Orchestrator-Workers** | TaskDecomposer dynamically breaks tasks → Actor workers | Fully aligned |
| **Evaluator-Optimizer** | Actor → Monitor feedback loop (up to 3-5 iterations) | Fully aligned |
| **Parallelization (Voting)** | Self-MoA: 3×Actor → 3×Monitor → Synthesizer | Fully aligned |
| **Prompt Chaining** | Sequential agent phases with programmatic gates (workflow-gate.py) | Fully aligned |
| **Routing** | Multiple slash commands route to different workflows (/map-efficient, /map-debug, /map-fast) | Fully aligned |
| **Tool Documentation** | Agent prompts include detailed input schemas and tool definitions | Partially aligned |

This is a strong foundation — MAP's architecture maps well onto Anthropic's recommended patterns.

---

## 7. Simplification: Reduce Agent Count for Common Paths

**Priority:** High
**Complexity:** Medium (workflow command changes, potentially removing agent calls)
**Affected files:** `.claude/commands/map-efficient.md`, `src/mapify_cli/templates/commands/map-efficient.md`

### Anthropic's Recommendation

The article's central message: "start with the simplest solution possible" and add complexity only when demonstrably needed. They specifically warn against using agentic systems when "a single optimized LLM call with retrieval" would suffice.

They also note: "agents trade latency and cost for better task performance, and you should consider when this trade-off makes sense." The implication is that multi-agent workflows should earn their complexity through measurable quality improvements.

### Current MAP State

`/map-efficient` runs: TaskDecomposer → (Actor → Monitor → [Predictor if risky]) per subtask. This is reasonable, but consider the full pipeline when including optional agents:

- TaskDecomposer → Actor → Monitor → Predictor → Evaluator → Reflector

That's 6 agent calls per subtask in the maximal case. For small changes (rename a function, fix a typo, add a log statement), this is overkill. `/map-fast` exists but is described as "minimal, low-risk only" — there is no middle ground.

### Proposed Change

Introduce **adaptive agent selection** based on subtask complexity. TaskDecomposer already estimates complexity for each subtask. Use this to select the agent pipeline:

```
## Adaptive Pipeline Selection

Based on TaskDecomposer's complexity estimate:

LOW complexity (estimated <30 LOC, single file, no API changes):
  → Actor → Monitor (2 agents, like /map-fast)
  → Skip Predictor and Evaluator entirely
  → No Reflector call

MEDIUM complexity (30-150 LOC, 2-4 files, internal API changes):
  → Actor → Monitor → Predictor (3 agents)
  → Evaluator only if Monitor flags concerns
  → Reflector optional (user's choice)

HIGH complexity (>150 LOC, 5+ files, public API changes, security-sensitive):
  → Full pipeline: Actor → Monitor → Predictor → Evaluator
  → Self-MoA mode available
  → Reflector recommended
```

This eliminates the binary choice between `/map-fast` (too minimal) and `/map-efficient` (potentially too heavy). The user runs one command, and the framework adapts.

### Why This Matters

Every additional agent call costs tokens, time, and context. Anthropic explicitly says the tradeoff must be justified. For a 10-line helper function, running Predictor (grep analysis across the repo) and Evaluator (6-dimension scoring) provides negligible value but doubles the cost and latency.

### Validation Plan

1. Audit the last 20 MAP workflow runs to categorize subtasks by actual complexity.
2. For LOW complexity subtasks, compare outcomes with and without Predictor/Evaluator.
3. Measure token savings and latency reduction.

---

## 8. Agent-Computer Interface (ACI) Investment: Tool Schema Standardization

**Priority:** High
**Complexity:** Medium (schema formalization + documentation)
**Affected files:** All agent `.md` files, potentially new `src/mapify_cli/schemas/agent_io.py`

### Anthropic's Recommendation

The article devotes significant attention to tool design, calling it "Agent-Computer Interface (ACI)" design. Key points:

- "Spend just as much time and effort on optimizing your tools and their descriptions as you would on your overall prompts."
- "Anthropic spent more time optimizing tools and tool descriptions than the overall prompts" in their SWE-bench implementation.
- Format choices matter: keep formats "close to what the model has seen naturally occurring in text on the internet."

### Current MAP State

MAP agents communicate via JSON output, but the schemas are defined informally in each agent's prompt. For example:

- Monitor outputs `{valid: true/false, issues: [...]}` — defined in monitor.md prose.
- Predictor outputs `{affected_files: [...], risk_level: ...}` — defined in predictor.md prose.
- Evaluator outputs `{scores: {...}, recommendation: "proceed"/"improve"/"reconsider"}` — defined in evaluator.md prose.

The architecture note in CLAUDE.md mentions "Contract-First Inter-Component JSON Schemas" as a learned pattern, but this hasn't been fully applied to inter-agent communication yet.

### Proposed Change

1. **Formalize agent I/O schemas** using TypedDict or dataclass in a new `src/mapify_cli/schemas/agent_io.py`:

```python
from typing import TypedDict, Literal

class MonitorOutput(TypedDict):
    valid: bool
    issues: list[MonitorIssue]
    quality_scores: QualityScores
    simulation_verdict: str | None  # from improvement #1

class PredictorOutput(TypedDict):
    affected_files: list[AffectedFile]
    risk_level: Literal["low", "medium", "high", "critical"]
    breaking_changes: list[BreakingChange]
    simulation_results: list[SimulationResult] | None  # from improvement #4

class EvaluatorOutput(TypedDict):
    scores: DimensionScores
    overall: float
    recommendation: Literal["proceed", "improve", "reconsider"]
    critical_failures: list[str]
```

2. **Generate JSON Schema from TypedDicts** and include the exact schema in each agent's prompt — replacing prose descriptions with machine-readable schemas.

3. **Add a validation step** in the orchestrator that checks agent output against the schema before passing to the next agent.

### Why This Matters

Anthropic's finding: tool/interface design matters *more* than prompt optimization. MAP's current approach — defining schemas in natural language within prompts — is fragile. Agent outputs sometimes deviate from the expected format, causing downstream agents to misparse.

Centralizing schemas in Python code (aligned with the "Contract-First" learned pattern) gives: one source of truth, IDE autocompletion for developers, automated validation, and exact JSON Schema for agent prompts.

---

## 9. Transparency: Expose Agent Planning Steps to the User

**Priority:** Medium
**Complexity:** Low-Medium (progress.md enhancement + orchestrator changes)
**Affected files:** `.claude/commands/map-efficient.md`, `.map/progress.md` format

### Anthropic's Recommendation

One of the three core principles: "Explicitly show the agent's planning steps." The article emphasizes that transparency builds user trust and enables better debugging when things go wrong.

### Current MAP State

MAP tracks workflow progress in `.map/progress.md` with YAML frontmatter, and detailed logs go to `.map/workflow_logs/`. However, this is primarily a machine-readable state file — the user experience during execution is opaque. The user sees Claude executing agents but doesn't see:

- What TaskDecomposer decided and why.
- Which subtask is being worked on and what the Actor's plan is.
- Why Monitor rejected something (the JSON feedback is internal).
- What Predictor found as high-risk dependencies.

### Proposed Change

Add a **user-facing progress stream** that emits human-readable status at each agent transition:

```
## Progress Stream Format

At each agent transition, emit a structured status block:

───────────────────────────────────────────
📋 PLAN: TaskDecomposer identified 3 subtasks
  ST-001: Add region parameter to get_weather() [LOW complexity]
  ST-002: Update all 4 callers of get_weather() [MEDIUM complexity]
  ST-003: Add region validation + tests [MEDIUM complexity]
───────────────────────────────────────────

───────────────────────────────────────────
🔨 BUILDING: ST-001 — Add region parameter [Actor]
  Pipeline: Actor → Monitor (adaptive: LOW complexity)
───────────────────────────────────────────

───────────────────────────────────────────
✅ VALIDATED: ST-001 — Monitor approved (quality: 8.2/10)
  0 issues found. Moving to ST-002.
───────────────────────────────────────────

───────────────────────────────────────────
⚠️ REJECTED: ST-002 — Monitor found 2 issues
  1. [HIGH] Missing null check on region parameter (line 42)
  2. [MEDIUM] No fallback for unknown region codes
  → Returning to Actor for fix (attempt 2/5)
───────────────────────────────────────────
```

This is a prompt-level change — the orchestrator commands already control agent sequencing, so adding a status emission between agent calls is straightforward.

### Why This Matters

MAP workflows can run for 10+ minutes on complex tasks. Without visibility, users don't know whether the workflow is stuck, making progress, or wasting tokens on unnecessary iterations. Transparency also lets users intervene early — if they see TaskDecomposer created an unnecessary subtask, they can abort before resources are wasted.

---

## 10. Routing Optimization: Smart Workflow Selection

**Priority:** Medium
**Complexity:** Medium (new routing logic or meta-command)
**Affected files:** New `.claude/commands/map.md` or hook-based router

### Anthropic's Recommendation

The routing pattern: "classify input and direct to specialized followup task." The article frames this as a way to handle diverse inputs without overloading a single workflow.

### Current MAP State

MAP has 7+ slash commands (`/map-efficient`, `/map-tdd`, `/map-debug`, `/map-fast`, `/map-review`, `/map-release`, `/map-plan`). The user must choose the right command for their task. This requires understanding what each workflow does and when to use it.

Common user mistakes:
- Using `/map-efficient` for a bug (should be `/map-debug`).
- Using `/map-efficient` for a trivial change (should be `/map-fast`).
- Forgetting `/map-plan` before `/map-task`.

### Proposed Change

Create a **universal entry point** `/map` that routes to the appropriate workflow:

```
## /map — Universal Router

Usage: /map <natural language description of what you want to do>

Routing logic (executed by a lightweight classifier prompt):

1. Parse the user's intent from the description.
2. Classify into one of:
   - "implement feature" → /map-efficient
   - "fix bug" or "debug" → /map-debug
   - "write tests first" or "TDD" → /map-tdd
   - "trivial change" or "rename" or "typo" → /map-fast
   - "review changes" → /map-review
   - "plan only" → /map-plan
   - "release" → /map-release

3. Confirm with user: "I'll use /map-debug for this bug fix. Proceed?"
4. On confirmation, delegate to the selected command.
```

This is the routing pattern from Anthropic's article — one entry point, intelligent dispatch.

### Why This Matters

Reduces cognitive load on users. Instead of memorizing 7 commands and their use cases, users describe what they want and the framework routes. The confirmation step preserves user control (they can override if the classifier is wrong).

---

## 11. Early Exit and Cost Control in Feedback Loops

**Priority:** Medium
**Complexity:** Low (prompt changes in orchestration commands)
**Affected files:** `.claude/commands/map-efficient.md`, `.claude/commands/map-debug.md`

### Anthropic's Recommendation

The article emphasizes that agents "trade latency and cost for better task performance" and this tradeoff should be managed deliberately. It also recommends guardrails and appropriate stopping conditions.

### Current MAP State

Actor → Monitor loops have a fixed maximum (3-5 iterations) but no *early success* exit. If Monitor approves on iteration 1, the loop exits. But there are edge cases:

- Monitor approves with warnings → loop continues for optional improvements → burns tokens on diminishing returns.
- Predictor runs on every subtask regardless of risk level → unnecessary for simple changes.
- No token budget tracking — workflows can silently consume large token counts on complex tasks.

### Proposed Change

1. **Strict early exit:** If Monitor returns `valid: true` with no HIGH severity warnings, exit immediately. Do not iterate to address MEDIUM or LOW warnings unless explicitly requested.

2. **Token budget awareness:** Track cumulative token usage across agents. Add a soft warning at 50k tokens and a hard prompt at 100k tokens:

```
## Token Budget Protocol

Track cumulative tokens used across all agent calls in the current workflow.

At 50k tokens: Emit warning:
  "⚠️ Token usage: ~50k. Remaining subtasks: N. Consider simplifying."

At 100k tokens: Prompt user:
  "🛑 Token usage: ~100k. Continue? [y/n/simplify]"
  - y: continue without limit
  - n: stop workflow, save progress
  - simplify: skip Predictor/Evaluator for remaining subtasks
```

3. **Conditional Predictor:** Only invoke Predictor when the Actor's changes touch public APIs, shared utilities, or files with >5 dependents. Skip for internal implementation changes.

---

## Summary Table

| # | Idea | Source | Priority | Complexity | Key Benefit |
|---|------|--------|----------|------------|-------------|
| 1 | Mental Execution in Monitor | Self-Execution paper | High | Low | Catches logical bugs that static analysis misses |
| 2 | Simulation Ranking in Self-MoA | Self-Execution paper | High | Medium | Objective behavioral signal for Synthesizer |
| 3 | Dry-Run mode for /map-debug | Self-Execution paper | Medium | Medium | Fast feedback when real tests are slow/unavailable |
| 4 | Simulated Integration in Predictor | Self-Execution paper | Medium | High | Catches breaking changes at call sites |
| 5 | Full Execution Traces | Self-Execution paper | Future | High | Richer fix feedback, but high token cost |
| 6 | Context Isolation in Fix Loops | Self-Execution paper | Medium-Low | Low | Cleaner fix iterations, less context pollution |
| 7 | Adaptive Pipeline by Complexity | Anthropic agents | High | Medium | Eliminates overengineered pipelines for simple tasks |
| 8 | ACI: Formalized Agent I/O Schemas | Anthropic agents | High | Medium | One source of truth, validation, fewer parsing errors |
| 9 | Transparent Progress Stream | Anthropic agents | Medium | Low-Medium | User visibility into workflow decisions and progress |
| 10 | Universal /map Router | Anthropic agents | Medium | Medium | Reduces user cognitive load, smart dispatch |
| 11 | Early Exit and Token Budgets | Anthropic agents | Medium | Low | Cost control, eliminates diminishing-returns iterations |

---

## References

- Paper: "Self-Execution Simulation Improves Coding Models" (arXiv:2604.03253v1, April 2025)
- Article: "Building Effective Agents" (https://www.anthropic.com/engineering/building-effective-agents)
- MAP Framework Architecture: `docs/ARCHITECTURE.md`
- Monitor Agent: `.claude/agents/monitor.md`
- Synthesizer Agent: `.claude/agents/synthesizer.md`
- Predictor Agent: `.claude/agents/predictor.md`
- Self-MoA documentation: `docs/USAGE.md` (section "Self-MoA: Solution Synthesis")
- Learned pattern — Contract-First Schemas: `.claude/rules/learned/architecture-patterns.md`
