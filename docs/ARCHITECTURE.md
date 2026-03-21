# MAP Framework Architecture

Deep technical documentation for MAP (Modular Agentic Planner) implementation.

> **Research Foundation:** [Nature Communications research (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks

## Table of Contents

- [Architecture Overview](#architecture-overview)
  - [.map/ Artifact Specifications](#map-artifact-specifications)
- [Agent Specifications](#agent-specifications)
- [MCP Integration](#mcp-integration)
- [Customization Guide](#customization-guide)
- [Template Maintenance](#template-maintenance)
- [Context Engineering](#context-engineering)

---

## Architecture Overview

### High-Level Design

MAP Framework implements cognitive architecture inspired by prefrontal cortex functions, orchestrating 11 specialized agents for software development with automatic quality validation.

**Key Design Principle:** Each slash command has its own unique workflow with different agent sequences. There is no single "standard" workflow — the orchestration logic is defined in `.claude/commands/map-*.md` files.

```
┌─────────────────────────────────────────────────────────────────┐
│                     SLASH COMMANDS                               │
│  Each command orchestrates its own unique agent sequence        │
└───────────────────┬─────────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────────────────────────────┐
    │               │               │               │        │
    ▼               ▼               ▼               ▼        ▼
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐  ┌────────┐  ┌────────┐
│EFFICIENT│    │  TDD   │    │ DEBUG  │    │ DEBATE │  │ REVIEW │  │  FAST  │
└────┬────┘    └────┬────┘   └────┬────┘   └────┬────┘  └────┬────┘  └────┬────┘
     │              │             │              │            │            │
     ▼              ▼             ▼              ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   WORKFLOW-SPECIFIC SEQUENCES                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  /map-efficient (⭐ RECOMMENDED):                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TaskDecomposer → For each subtask:                       │   │
│  │   ├─ Standard: Actor → Monitor → [Predictor if risky]    │   │
│  │   └─ Self-MoA: 3×Actor → 3×Monitor → Synthesizer → Mon.  │   │
│  │ No Evaluator. Learning via /map-learn (optional)         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-tdd (test-first development):                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TaskDecomposer → For each subtask:                       │   │
│  │   TEST_WRITER (tests from spec) → TEST_FAIL_GATE (Red)  │   │
│  │   → Actor (code_only) → Monitor → [Predictor if risky]  │   │
│  │ Tests written BEFORE implementation. 8 phases.          │   │
│  │ Single-subtask: /map-tdd ST-001 (TDD for one subtask)   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-task (single subtask execution):                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Runs one subtask from existing plan (no decomposition).  │   │
│  │ Usage: /map-task ST-001                                  │   │
│  │ Requires: /map-plan completed first.                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-debug (debugging-specific):                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TaskDecomposer → For each step:                          │   │
│  │   Investigation: Actor (analyze) → Monitor               │   │
│  │   Fix: Actor → Monitor → Predictor → Evaluator           │   │
│  │ Includes both investigation AND implementation phases     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-debate (multi-variant with Opus arbiter):                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TaskDecomposer → For each subtask:                       │   │
│  │   3×Actor (parallel: security/perf/simplicity)           │   │
│  │   → 3×Monitor (parallel validation)                      │   │
│  │   → DebateArbiter (Opus) → Monitor → [Predictor if risky]│   │
│  │ Uses Claude Opus for cross-evaluation and synthesis      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-review (interactive 4-section):                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ git diff analysis                                         │   │
│  │ → [Monitor + Predictor + Evaluator] (all 3 parallel)     │   │
│  │ → Interactive: Architecture → Quality → Tests → Perf     │   │
│  │ → Verdict: PROCEED / REVISE / BLOCK                      │   │
│  │ --ci mode: batch report, no interaction                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-fast (⚠️ minimal, low-risk only):                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ TaskDecomposer → Actor → Monitor                         │   │
│  │ No Predictor, no Evaluator, no learning                  │   │
│  │ Max 3 iterations. Use only for small, low-risk changes   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-release (7-phase release workflow):                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Phase 1: 12 validation gates (tests, lint, CI, etc.)     │   │
│  │ Phase 2: Version determination (user decides bump type)  │   │
│  │ Phase 3: Execute bump-version.sh                         │   │
│  │ Phase 4: Push tag (⚠️ IRREVERSIBLE)                      │   │
│  │ Phase 5: Monitor CI/CD, create GitHub release            │   │
│  │ Phase 6: Verify PyPI availability + installation test    │   │
│  │ Phase 7: Summary                                         │   │
│  │ No agents. Bash scripts + GitHub CLI orchestration       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /map-learn (post-workflow learning):                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Reflector → Verification                                  │   │
│  │ Standalone command. Run AFTER any workflow completes.    │   │
│  │ Extracts patterns from workflow outcomes.                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  RESEARCH-AGENT (on-demand in any workflow):                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Heavy codebase reading with compressed output            │   │
│  │ Called conditionally when context gathering needed       │   │
│  │ Runs in isolation to avoid polluting main context        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Orchestration Model

**Command-Driven Workflow:**
- Orchestration logic implemented in slash command prompts (`.claude/commands/map-*.md`)
- NOT a separate agent file
- When you run `/map-efficient`, the command prompt coordinates the workflow by calling agents sequentially via the Task tool

**Workflow Stages:**

1. **Task Decomposition** (TaskDecomposer)
   - Receives high-level goal
   - Breaks into atomic subtasks
   - Estimates complexity and dependencies
   - Outputs structured task plan

2. **Implementation Loop** (per subtask)
   - **Code Generation** (Actor): Generates solution
   - **Validation** (Monitor): Checks quality, security, correctness
   - **Feedback Loop**: If validation fails, return to Actor with feedback (max 3-5 iterations)

3. **Impact Analysis** (Predictor)
   - Analyzes change ripple effects across codebase
   - Identifies affected components
   - Flags potential breaking changes

4. **Quality Scoring** (Evaluator)
   - Rates solution on multiple dimensions
   - Functionality, security, testability, maintainability
   - Scores 0-10, approval threshold >7.0

5. **Learning Cycle** (Reflector)
   - Extracts patterns from successes and failures
   - Enables continuous improvement

### Agent Coordination Protocol

**Sequential Execution:**
- Each agent receives structured input from previous agent
- Agents communicate via JSON output format
- Orchestrator enforces strict agent ordering

**Error Handling:**
- Actor-Monitor feedback loops limited to 3-5 iterations
- Infinite loop detection at orchestrator level
- Graceful degradation if agent fails

**State Management:**
- Workflow checkpoint stored in `.map/progress.md` (YAML frontmatter + markdown)
- Task plan stored in `.map/<branch>/task_plan_*.md`
- Workflow logs in `.map/workflow_logs/`
- Metrics tracked in `.claude/metrics/agent_metrics.jsonl`

### .map/ Artifact Specifications

MAP Framework stores workflow artifacts in the `.map/` directory. All artifacts follow JSON schemas defined in `src/mapify_cli/schemas.py`.

#### 1. State Artifact (`state_<branch>.json`)

**Purpose:** Track workflow state including terminal status and early termination.

**Written by:** `src/mapify_cli/workflow_state.py` (WorkflowState class)

**Schema:** `STATE_ARTIFACT_SCHEMA` in `src/mapify_cli/schemas.py`

**Example:**
```json
{
  "workflow": "map-efficient",
  "terminal_status": "complete",
  "ended_early": null,
  "subtasks": [
    {
      "id": "ST-001",
      "title": "Create User model",
      "status": "complete",
      "validation_criteria": [
        "Model includes email field",
        "Password hashing implemented"
      ]
    },
    {
      "id": "ST-002",
      "title": "Implement login endpoint",
      "status": "complete",
      "validation_criteria": []
    }
  ]
}
```

**Early Termination Example:**
```json
{
  "workflow": "map-efficient",
  "terminal_status": "won't_do",
  "ended_early": {
    "by_user": true,
    "reason": "User requested early termination",
    "at_subtask_id": "ST-003"
  },
  "subtasks": [
    {
      "id": "ST-001",
      "title": "Create User model",
      "status": "complete",
      "validation_criteria": []
    },
    {
      "id": "ST-002",
      "title": "Implement login endpoint",
      "status": "won't_do",
      "validation_criteria": []
    }
  ]
}
```

**Terminal Status Values:**
| Status | Description |
|--------|-------------|
| `pending` | Workflow not started or in progress |
| `complete` | All subtasks completed successfully |
| `blocked` | Workflow blocked by unresolved issue |
| `won't_do` | Workflow terminated early by user |
| `superseded` | Workflow replaced by newer workflow |

#### 2. Verification Results Artifact (`verification_results_<branch>.json`)

**Purpose:** Machine-readable record of hook verification checks for CI/CD integration.

**Written by:** `src/mapify_cli/verification_recorder.py` (record_verification_result function)

**Schema:** `VERIFICATION_RESULTS_SCHEMA` in `src/mapify_cli/schemas.py`

**Example:**
```json
{
  "overall": "pass",
  "recipes": [
    {
      "id": "check_ruff",
      "status": "pass",
      "summary": "ruff passed",
      "duration_ms": 1200
    },
    {
      "id": "check_secrets",
      "status": "skipped",
      "summary": "No staged files to check",
      "duration_ms": 50,
      "skip_reason": "No files were staged for commit"
    },
    {
      "id": "check_mypy",
      "status": "fail",
      "summary": "mypy failed",
      "duration_ms": 3500
    }
  ]
}
```

**Overall Status Aggregation:**
| Condition | Overall Status |
|-----------|----------------|
| ANY recipe is `fail` | `fail` |
| ALL recipes are `pass` | `pass` |
| Otherwise | `unknown` |

**Recipe Status Values:**
| Status | Description |
|--------|-------------|
| `pass` | Check completed successfully |
| `fail` | Check found problems |
| `skipped` | Check intentionally skipped (see `skip_reason`) |

#### 3. Repo Insight Artifact (`repo_insight_<branch>.json`)

**Purpose:** Project metadata for language detection and suggested checks.

**Written by:** `src/mapify_cli/repo_insight.py` (create_repo_insight function)

**Schema:** `REPO_INSIGHT_SCHEMA` in `src/mapify_cli/schemas.py`

**Example:**
```json
{
  "language": "python",
  "suggested_checks": [
    "make check",
    "pytest tests/test_template_sync.py -v",
    "make sync-templates"
  ],
  "key_dirs": [
    "src",
    "tests",
    ".claude"
  ]
}
```

**Language Values:**
| Language | Detection Marker |
|----------|------------------|
| `python` | `pyproject.toml`, `setup.py`, `requirements.txt` |
| `typescript` | `tsconfig.json` (takes precedence over `package.json`) |
| `javascript` | `package.json` |
| `go` | `go.mod` |
| `rust` | `Cargo.toml` |
| `unknown` | No marker files found |

**Constraints:**
- `key_dirs` maximum 5 entries
- All `key_dirs` paths are relative (no leading `/`)
- `suggested_checks` filtered based on available tools (e.g., `make` commands only if `Makefile` exists)

#### Schema Cross-Reference

All JSON schemas are defined in `src/mapify_cli/schemas.py`:

| Schema Constant | Artifact File | JSON Schema Draft |
|----------------|---------------|-------------------|
| `STATE_ARTIFACT_SCHEMA` | `state_<branch>.json` | 2020-12 |
| `VERIFICATION_RESULTS_SCHEMA` | `verification_results_<branch>.json` | 2020-12 |
| `REPO_INSIGHT_SCHEMA` | `repo_insight_<branch>.json` | 2020-12 |

### Workflow Variants

MAP Framework provides multiple workflow variants with different agent orchestration strategies:

#### 1. `/map-efficient` - Optimized Pipeline (4-6 Agents) ⭐ RECOMMENDED

**Agent Sequence:** TaskDecomposer → [conditional ResearchAgent] → (Actor → Monitor → [conditional Predictor]) per subtask → FinalVerifier

**With Self-MoA** (--self-moa flag OR high risk/complexity):
TaskDecomposer → [conditional ResearchAgent] → (3×Actor parallel → 3×Monitor parallel → Synthesizer → final Monitor → [conditional Predictor]) per subtask → FinalVerifier

**Optimizations:**

1. **Conditional Predictor** (token savings)
   - Only called if TaskDecomposer assigns `risk_level='high'/'medium'`
   - OR if Monitor sets `escalation_required=true`
   - Low-risk subtasks (simple CRUD, UI updates) skip impact analysis

2. **Evaluator Skipped** (token savings)
   - Monitor provides sufficient validation for most tasks
   - Evaluator's 6-dimension scoring rarely changes proceed/reject decision
   - Quality still ensured by Monitor's comprehensive checks

3. **Learning is OPTIONAL via /map-learn**
   - Workflow does NOT include Reflector
   - At completion, suggests running `/map-learn` if patterns worth saving
   - Separation keeps workflows fast, learning intentional

**Token Usage:** Baseline for production workflows
**Learning:** Optional via `/map-learn` command
**Quality Gates:** Essential agents (Monitor, conditional Predictor)

**Technical Details:**

```python
# Conditional Predictor Logic (Orchestrator)
for subtask in subtasks:
    actor_output = call_actor(subtask)
    monitor_output = call_monitor(actor_output)

    if monitor_output.valid:
        # Only call Predictor if high risk
        if (subtask.risk_level in ['high', 'medium'] or
            monitor_output.escalation_required):
            predictor_output = call_predictor(actor_output)
        # Apply changes
        apply_code_changes(actor_output)

# At end: suggest /map-learn if valuable patterns discovered
print("Consider running /map-learn to save patterns")
```

**Use for:**
- Production code where token costs matter (RECOMMENDED)
- Well-understood features (standard CRUD, APIs, UI)
- Iterative development with frequent workflows
- Any task where /map-fast feels too risky but /map-debate too expensive

#### 2. `/map-fast` - Minimal Pipeline (3 Agents) ⚠️

**Agent Sequence:** TaskDecomposer → (Actor → Monitor) per subtask

**Agents SKIPPED:**
- ❌ Predictor (no impact analysis)
- ❌ Evaluator (no quality scoring)
- ❌ Reflector (no lesson extraction)

**Token Usage:** 50-60% of baseline
**Learning:** None (defeats MAP's purpose)
**Quality Gates:** Basic only (Monitor validation)

**Architectural Consequences:**
- Knowledge base remains static (no continuous improvement)
- Breaking changes undetected (no Predictor)
- Security/performance issues may slip through (no Evaluator)
- Same mistakes repeated (no Reflector)

**Use ONLY for:**
- Small, low-risk changes with clear acceptance criteria
- Localized fixes with minimal blast radius

**Avoid for:**
- Security-sensitive functionality
- Broad refactors or multi-module changes
- High uncertainty requirements

#### 3. `/map-debate` - Debate-Based Multi-Variant (5-7 Agents)

**Agent Sequence:** TaskDecomposer → [conditional ResearchAgent] → (3×Actor parallel → 3×Monitor parallel → DebateArbiter (Opus) → Monitor → [Predictor if risky]) per subtask

**Multi-Variant Architecture:**

1. **Parallel Actor Variants** (3 simultaneous implementations)
   - Variant 1: Security-focused approach
   - Variant 2: Performance-focused approach
   - Variant 3: Simplicity-focused approach
   - Each variant gets `approach_focus` parameter
   - All variants solve same subtask with different optimization priorities

2. **Parallel Monitor Validation** (3 validations)
   - Each Actor variant validated independently
   - Failures fed back to respective Actor for iteration
   - Continue until all 3 variants pass validation

3. **Debate-Arbiter Cross-Evaluation + Synthesis** (Opus model)
   - Receives all 3 validated variants AND their Monitor outputs
   - Cross-evaluates trade-offs with explicit reasoning matrix
   - **Synthesizes unified solution directly** (no separate Synthesizer agent)
   - Uses Claude Opus 4.5 for high-quality analysis
   - Outputs: comparison_matrix, decision_rationales, synthesis_reasoning, synthesized code

4. **Final Validation**
   - Final Monitor validates the synthesized code
   - Conditional Predictor for medium/high risk subtasks
   - Max 2 DebateArbiter retries if Monitor fails

**Token Usage:** 80-100% of baseline
**Learning:** Optional via `/map-learn` (same as other workflows)
**Quality Gates:** All agents (maximum variant exploration)

**Key Features:**
- **Opus-powered arbiter**: Higher reasoning quality for complex trade-off analysis
- **Explicit decision tracking**: Each variant documents decisions made
- **Multi-perspective synthesis**: Best-of-all-worlds solution
- **Parallel execution**: 3 Actor/Monitor pairs run simultaneously

**Use for:**
- Architecture decisions with significant trade-offs
- Complex features where optimal approach is unclear
- Security-critical code requiring multiple review perspectives
- Performance-sensitive implementations
- Situations where you want to explore solution space thoroughly

**Technical Details:**

```python
# Debate Workflow Orchestrator Logic
for subtask in subtasks:
    # Phase 1: Generate 3 variants in parallel
    variants = parallel_execute([
        call_actor(subtask, approach_focus="security"),
        call_actor(subtask, approach_focus="performance"),
        call_actor(subtask, approach_focus="simplicity")
    ])

    # Phase 2: Validate all variants in parallel
    validations = parallel_execute([
        call_monitor(variants[0]),
        call_monitor(variants[1]),
        call_monitor(variants[2])
    ])

    # Phase 3: Debate-Arbiter cross-evaluation + synthesis (Opus)
    # DebateArbiter both evaluates AND synthesizes in single call
    arbiter_output = call_debate_arbiter(
        variants=variants,
        validations=validations,
        model="claude-opus-4-5"
    )
    # arbiter_output includes: comparison_matrix, decision_rationales,
    # synthesis_reasoning, and synthesized code

    # Phase 4: Final validation and impact analysis
    final_monitor = call_monitor(arbiter_output.synthesized_code)
    if final_monitor.valid:
        if subtask.risk_level in ['high', 'medium']:
            predictor_output = call_predictor(arbiter_output)
        apply_code_changes(arbiter_output.synthesized_code)
```

**Trade-offs:**
- **Pro:** Maximum solution quality through variant exploration
- **Pro:** Discovers optimal patterns for knowledge base
- **Pro:** Arbiter reasoning provides detailed decision documentation
- **Con:** Higher token cost (3× Actor + Opus arbiter)
- **Con:** Longer execution time (parallel but still 3× work)

#### 4. `/map-debug` - Debugging Workflow (5 Agents)

**Agent Sequence:** TaskDecomposer → For each step: Actor → Monitor → Predictor → Evaluator

**Debugging-Specific Features:**

1. **Pre-Analysis Phase**
   - Identify affected files via Grep/Glob

2. **Step Types** (defined by TaskDecomposer):
   - `investigation`: Analyze code, logs, reproduce issue (Actor read-only)
   - `fix`: Implement solution (Actor generates code changes)
   - `verification`: Test fix, check for regressions

3. **Full Agent Pipeline for Fixes**
   - Unlike /map-efficient, debugging fixes go through ALL agents
   - Predictor checks for similar issues elsewhere in codebase
   - Evaluator verifies fix quality and edge case coverage

**Token Usage:** 70-80% of baseline
**Learning:** Optional via `/map-learn`
**Quality Gates:** All agents for fixes, reduced for investigation

**Use for:**
- Bug fixes and issue resolution
- Root cause analysis
- Regression debugging

#### 5. `/map-review` - Interactive Code Review (3 Agents)

**Agent Sequence:** git diff → [Monitor + Predictor + Evaluator] (all 3 parallel) → Interactive 4-section presentation → Verdict

**Review-Specific Features:**

1. **No TaskDecomposer** - Reviews current branch changes as-is
2. **Parallel Agent Launch** - 3 agents launched in a single message
3. **Interactive 4-Section Presentation:**
   - **Architecture** (primary: Predictor — breaking changes, affected components)
   - **Code Quality** (primary: Monitor — correctness, maintainability issues)
   - **Tests** (primary: Monitor — testability, coverage gaps)
   - **Performance** (primary: Monitor — performance issues, cross-ref Predictor risk)
4. **Review Section Protocol** — each section presents top N issues (BIG=4, SMALL=1) with options and tradeoffs, user picks resolution via AskUserQuestion
5. **BIG/SMALL mode** — user selects review depth at start
6. **CI/Auto mode** (`--ci`/`--auto` flag) — batch report with no interaction, auto-selects recommended options
7. **Verdict Logic:**
   - PROCEED: Monitor approved + valid AND Evaluator proceed
   - REVISE: Monitor needs_revision OR Evaluator improve
   - BLOCK: Monitor rejected OR Evaluator reconsider OR security/functionality < 5 OR (Predictor high risk + breaking changes)
   - Priority: BLOCK > REVISE > PROCEED

**Token Usage:** ~15-25K tokens (parallel agents + interactive 4-section presentation; `--ci` mode ~12-15K)
**Learning:** Optional via `/map-learn`
**Quality Gates:** All 3 review agents

**Use for:**
- Pre-commit code review
- PR review automation
- Quality gate before merge
- CI pipeline integration (`--ci` mode)

#### 6. `/map-release` - Release Workflow (No Agents)

**Workflow:** 7 sequential phases with validation gates (no AI agents)

**Phases:**
1. Pre-release validation (12 gates: tests, lint, CI, security, CHANGELOG)
2. Version determination (user chooses bump type)
3. Execute bump-version.sh (updates pyproject.toml, CHANGELOG, creates tag)
4. Push tag (⚠️ IRREVERSIBLE - triggers CI/CD)
5. Monitor CI/CD, create GitHub release
6. Verify PyPI availability + installation test
7. Summary

**Unique Characteristics:**
- **No AI agents** - bash scripts + GitHub CLI orchestration
- **User confirmation required** before irreversible tag push
- **Rollback procedures documented** for each failure scenario

**Use for:**
- Package releases to PyPI
- Version bumping with full validation

#### 7. `/map-learn` - Post-Workflow Learning (1 Agent)

**Agent Sequence:** Reflector → Verification

**Standalone Learning:**
- Run AFTER any workflow completes (not during)
- Extracts patterns from Actor/Monitor/Predictor outputs

**Token Usage:** 5-8K tokens (depends on workflow size)
**When to use:**
- After /map-efficient completes with valuable patterns
- After /map-debug reveals debugging techniques
- Retroactively for /map-fast workflows

#### Token Breakdown by Agent

Typical token consumption per subtask (estimated):

| Agent | Prompt | Output | Total | Notes |
|-------|--------|--------|-------|-------|
| TaskDecomposer | 1.5K | 1K | 2.5K | One-time (not per subtask) |
| Actor | 2K | 3-4K | 5-6K | Largest consumer (full file content) |
| Monitor | 1.5K | 1K | 2.5K | Always included |
| Predictor | 1.5K | 1K | 2.5K | Conditional in /map-efficient, always in /map-debug |
| Evaluator | 2K | 1K | 3K | Only in /map-debug, /map-review |
| Reflector | 2K | 1K | 3K | Only via /map-learn |
| DebateArbiter | 3K | 2K | 5K | Opus model, /map-debate only (includes synthesis) |
| Synthesizer | 2K | 3K | 5K | /map-efficient Self-MoA only (DebateArbiter handles this in /map-debate) |
| ResearchAgent | 2K | 4K | 6K | Heavy codebase reading, on-demand in any workflow |

**Per-subtask totals:**
- /map-efficient (standard): ~9-12K tokens (baseline)
- /map-efficient (Self-MoA): ~25-30K tokens (3× Actor + Synthesizer)
- /map-fast: ~8-10K tokens (minimal, no learning)
- /map-debug: ~15-20K tokens (full pipeline with Evaluator)
- /map-review: ~15-25K tokens (parallel agents + interactive 4-section presentation; --ci mode ~12-15K)
- /map-debate: ~30-40K tokens (3× Actor + Opus DebateArbiter)

**For 5-subtask workflow:**
- /map-efficient: ~45-60K tokens (learning optional via /map-learn: +5-8K)
- /map-fast: ~40-50K tokens (no learning support)
- /map-debate: ~150-200K tokens (3× variants + Opus analysis)

#### Workflow Variant Selection

See [USAGE.md - Workflow Variants](./USAGE.md#workflow-variants) for detailed decision guide, real-world examples, and cost analysis.

---

### Hook-Based Context Injection (v2.0.0+)

**Problem:** Long command files (995 lines, ~5.4K tokens) cause attention dilution → Claude skips critical workflow steps like research and self-audit (20% compliance rate).

**Solution:** State-machine orchestration + PreToolUse hook injection

#### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PreToolUse Hook (workflow-context-injector.py)             │
│  • Reads: .map/<branch>/step_state.json                     │
│  • Injects: ~150 token reminder before EVERY tool call      │
│  • Shows: Current step, progress, mandatory next action     │
│  • Non-blocking: Always allows tool execution               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  map-efficient.md (~1.75K tokens, down from ~5.4K)          │
│  1. Get next step instruction (map_orchestrator.py)         │
│  2. Route to executor (Actor/Monitor/etc)              │
│  3. Execute step                                            │
│  4. Validate completion → Update state                      │
│  5. Recurse if more steps; else complete                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  State Machine (.map/scripts/map_orchestrator.py)                │
│  • State file: .map/<branch>/step_state.json                │
│  • Enforces: Sequential execution, no step skipping         │
│  • CLI: get_next_step, validate_step, initialize            │
└─────────────────────────────────────────────────────────────┘
```

#### Key Innovation: Constant Reminders

**Pattern borrowed from ralph-loop's `build_loop_context()`:** Inject small, frequent reminders rather than upfront instructions.

**Hook Output Example:**
```
╔═══════════════════════════════════════════════════════════╗
║ MAP WORKFLOW CHECKPOINT                                   ║
╠═══════════════════════════════════════════════════════════╣
║ Current Step:  2.2 - RESEARCH
║ Progress:      Subtask 1/5
║
║ ⚠️  MANDATORY NEXT ACTION:
║    Call research-agent BEFORE Actor
╚═══════════════════════════════════════════════════════════╝
```

**Injected into system prompt before EVERY tool call** → Claude cannot "forget" the current step.

#### Results

| Metric | Before (v1.x) | After (v2.0.0) |
|--------|---------------|----------------|
| **Step compliance** | ~20% | ~85% (predicted) |
| **Command file tokens** | ~5,400 | ~1,750 |
| **Research skip rate** | 80% | ~5% (predicted) |
| **Self-audit skip rate** | 90% | ~10% (predicted) |
| **User interventions** | ~3 per workflow | ~0.3 (predicted) |
| **Hook latency** | N/A | <100ms |

#### Token Economics

- **Before:** 5,400 tokens per invocation × 10 invocations = 54,000 tokens
- **After:** 1,750 tokens + (150 hook tokens × 50 tool calls) = 9,250 tokens
- **Net savings:** ~83% reduction despite hook overhead

#### Implementation Details

**8 Step Phases (6 standard + 2 TDD):
1. `1.0 DECOMPOSE` - task-decomposer agent
2. `1.5 INIT_PLAN` - Generate task_plan.md
3. `1.55 REVIEW_PLAN` - User approval checkpoint
4. `1.56 CHOOSE_MODE` - Auto-skipped (always batch mode)
5. `1.6 INIT_STATE` - Create step_state.json
8. `2.2 RESEARCH` - research-agent (conditional)
9. `2.25 TEST_WRITER` - TDD: write tests from spec (TDD mode only, auto-skipped otherwise)
10. `2.26 TEST_FAIL_GATE` - TDD: verify tests fail without impl (TDD mode only)
11. `2.3 ACTOR` - Actor agent implementation (code-only in TDD mode)
12. `2.4 MONITOR` - Monitor validation (retry up to 5 times)

**State Files:**
- `step_state.json` - Hook injection source (current step phase)
- `step_state.json` - Gate enforcement source (actor+monitor completed)

