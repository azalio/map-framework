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
- Any task where /map-fast feels too risky

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
| Synthesizer | 2K | 3K | 5K | /map-efficient Self-MoA only |
| ResearchAgent | 2K | 4K | 6K | Heavy codebase reading, on-demand in any workflow |

**Per-subtask totals:**
- /map-efficient (standard): ~9-12K tokens (baseline)
- /map-efficient (Self-MoA): ~25-30K tokens (3× Actor + Synthesizer)
- /map-fast: ~8-10K tokens (minimal, no learning)
- /map-debug: ~15-20K tokens (full pipeline with Evaluator)
- /map-review: ~15-25K tokens (parallel agents + interactive 4-section presentation; --ci mode ~12-15K)

**For 5-subtask workflow:**
- /map-efficient: ~45-60K tokens (learning optional via /map-learn: +5-8K)
- /map-fast: ~40-50K tokens (no learning support)

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
│  • 8 step phases (DECOMPOSE → SUBTASK_APPROVAL + 2 TDD)     │
│  • State file: .map/<branch>/step_state.json                │
│  • Enforces: Sequential execution, no step skipping         │
│  • CLI: get_next_step, validate_step, initialize,            │
│         monitor_failed, wave_monitor_failed, skip_step,      │
│         set_waves, get_wave_step, advance_wave, + more       │
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
║ Completed:     1.0_DECOMPOSE, 1.5_INIT_PLAN, 1.6_INIT_STATE
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

**8 Step Phases (6 standard + 2 TDD):**
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

**State File:**
- `step_state.json` - Single source of truth for step sequencing, hook injection, and gate enforcement

#### Migration Guide (v1.x → v2.0.0)

**Breaking Change:** /map-efficient now requires Python state machine.

**User Action:**
```bash
# Update MAP Framework installation
mapify init  # Regenerates .claude/ with new hooks and scripts

# Existing workflows continue automatically
# No manual migration needed for in-progress workflows
```

**For Custom Workflows:**
If you modified `.claude/commands/map-efficient.md`, you must manually integrate state machine calls:
- Replace monolithic step logic with `map_orchestrator.py` CLI calls
- See template: `src/mapify_cli/templates/commands/map-efficient.md`

---

## Agent Specifications

### 1. TaskDecomposer

**Responsibility:** Break high-level goals into atomic, executable subtasks.

**Input:**
```json
{
  "goal": "implement user authentication with JWT tokens",
  "context": {
    "language": "Python",
    "framework": "Flask",
    "existing_files": ["app.py", "models.py"]
  }
}
```

**Output:**
```json
{
  "subtasks": [
    {
      "id": "auth_001",
      "description": "Create User model with password hashing",
      "estimated_complexity": "medium",
      "dependencies": []
    },
    {
      "id": "auth_002",
      "description": "Implement /login endpoint with JWT generation",
      "estimated_complexity": "high",
      "dependencies": ["auth_001"]
    }
  ]
}
```

**Key Behaviors:**
- Each subtask should be completable in <100 lines of code
- Explicit dependency tracking
- Complexity estimation (low/medium/high)
- Considers existing codebase structure

### 2. Actor

**Responsibility:** Generate code and solutions for subtasks.

**Input:**
```json
{
  "subtask_description": "Implement /login endpoint with JWT generation",
  "language": "Python",
  "framework": "Flask",
  "existing_patterns": ["impl-0042: Use bcrypt for password hashing"],
  "feedback": "Missing error handling for invalid credentials"
}
```

**Output Structure:**
1. **Approach** (2-3 sentences)
2. **Code Changes** (complete implementations, no ellipsis)
3. **Trade-offs** (alternatives considered, decisions made)
4. **Testing Considerations** (critical test cases)
5. **Used Patterns** (pattern IDs applied)

**Key Behaviors:**
- Fetches current docs for external libraries (via deepwiki)
- Explicit error handling required (no silent failures)
- Complete code, not sketches or placeholders
- Security-first approach for auth/data access

**MCP Tool Usage:**
- `mcp__deepwiki__read_wiki_contents`: Get current library/project documentation

### 3. Monitor

**Responsibility:** Validate code quality, security, and correctness.

**Input:** Actor's complete output (approach, code, trade-offs, tests)

**Output:**
```json
{
  "validation_passed": false,
  "issues": [
    {
      "severity": "critical",
      "category": "security",
      "description": "Password not hashed before storage",
      "suggested_fix": "Use bcrypt.hashpw() before db.session.add()"
    }
  ],
  "feedback": "Add password hashing using bcrypt library. Import bcrypt at top of file."
}
```

**Validation Criteria:**
- ✅ Error handling present (no silent failures)
- ✅ Security best practices (OWASP Top 10 compliance)
- ✅ File scope respected (no out-of-scope modifications)
- ✅ Code completeness (no ellipsis/placeholders)
- ✅ Dependency justification (if new deps added)

**Key Behaviors:**
- Severity classification: critical/major/minor
- Specific, actionable feedback
- Checks against project coding standards

### 4. Predictor

**Responsibility:** Analyze change impact across codebase.

**Input:** Actor's code changes

**Output:**
```json
{
  "impact_analysis": {
    "affected_files": ["app.py", "models.py", "tests/test_auth.py"],
    "breaking_changes": false,
    "risk_level": "medium",
    "ripple_effects": [
      {
        "component": "User API",
        "effect": "New endpoint requires documentation update",
        "action_required": "Update API docs"
      }
    ]
  }
}
```

**Analysis Dimensions:**
- File dependencies (imports, function calls)
- API contract changes
- Database schema modifications
- Configuration requirements
- Test coverage gaps

**Model Used:** Sonnet (impact analysis requires complex reasoning)

### 5. Evaluator

**Responsibility:** Score solution quality on multiple dimensions.

**Input:** Actor's output + Predictor's impact analysis

**Output:**
```json
{
  "scores": {
    "functionality": 9,
    "security": 8,
    "testability": 7,
    "maintainability": 8,
    "overall": 8.0
  },
  "approved": true,
  "rationale": "Strong implementation with proper error handling. Consider adding integration tests."
}
```

**Scoring Rubric (0-10):**
- **Functionality:** Does it solve the problem completely?
- **Security:** OWASP compliance, input validation, secure defaults
- **Testability:** Can it be easily tested? Clear test cases provided?
- **Maintainability:** Clear code, good naming, documented trade-offs

**Approval Threshold:** >7.0 overall score

**Model Used:** Sonnet (evaluation requires nuanced judgment)

### 6. Reflector

**Responsibility:** Extract lessons from successes and failures.

**Input:** Complete workflow context (Actor, Monitor, Predictor, Evaluator outputs)

**Output:**
```json
{
  "patterns_extracted": [
    {
      "pattern_id": "auth_jwt_001",
      "category": "implementation",
      "content": "Use bcrypt for password hashing with work factor 12",
      "when_to_use": "User authentication with password storage",
      "trade_offs": "Slower than SHA256 but much more secure",
      "code_snippet": "hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12))"
    }
  ]
}
```

**Key Behaviors:**
- Extracts both successful patterns and failure lessons
- Contextualizes lessons (when to apply, when to avoid)
- Links to specific workflow outcomes

**MCP Tool Usage:**
- `mcp__sequential-thinking__sequentialthinking`: Structure reasoning process

### 7. DocumentationReviewer

**Responsibility:** Check documentation completeness and correctness.

**Input:** Documentation files + related code

**Output:**
```json
{
  "completeness_score": 8,
  "issues": [
    {
      "file": "API.md",
      "issue": "Missing error response format for 401 Unauthorized",
      "suggested_fix": "Add example JSON response for 401 errors"
    }
  ]
}
```

**Validation Criteria:**
- ✅ API endpoints documented with request/response examples
- ✅ Error codes and responses documented
- ✅ Configuration options explained
- ✅ Examples match actual code behavior

### 8. Synthesizer

**Responsibility:** Merge best elements from multiple Actor variants in Self-MoA (Mixture of Agents) workflows.

**Input:** Multiple Actor variants (typically 3) with different optimization focuses + DebateArbiter guidance

**Output:**
```json
{
  "synthesized_solution": {
    "approach": "Hybrid approach combining security validation from v1, performance optimization from v2, and clear structure from v3",
    "code_changes": "// Complete merged implementation",
    "trade_offs": "Decision points resolved based on arbiter analysis",
    "testing_considerations": "Merged test cases covering all variants' scenarios",
    "decisions_resolved": [
      {
        "decision": "Error handling strategy",
        "variants": {
          "v1_security": "Comprehensive validation with detailed errors",
          "v2_performance": "Fast-fail with minimal overhead",
          "v3_simplicity": "Standard try-catch blocks"
        },
        "chosen": "v1_security with v2_performance optimizations",
        "rationale": "Arbiter recommended comprehensive validation is critical; optimized by caching validation results"
      }
    ]
  }
}
```

**Key Behaviors:**
- Analyzes decision points from all variants
- Resolves conflicts using DebateArbiter guidance
- Preserves best practices from each variant
- Creates coherent unified solution (not patchwork)
- Documents synthesis rationale for learning

**Model Used:** Sonnet (requires strong reasoning for synthesis)

**Usage Context:** Invoked in `/map-efficient --self-moa` workflow for multi-variant synthesis

### 9. ResearchAgent

**Responsibility:** Heavy codebase reading with context isolation and compressed output for Actor/Monitor consumption.

**Input:**
```json
{
  "research_goal": "Find all authentication implementations",
  "file_patterns": ["**/*auth*.py", "**/*login*.js"],
  "symbols": ["authenticate", "login", "verify_token"],
  "intent": "locate|understand|pattern|impact"
}
```

**Output:**
```json
{
  "relevant_locations": [
    {
      "file": "app/auth/jwt.py",
      "lines": [45, 67],
      "signatures": ["def verify_token(token: str) -> User"],
      "description": "JWT token validation with expiration check"
    }
  ],
  "patterns_found": [
    "All auth functions use bcrypt for password hashing",
    "Token refresh logic in separate module (app/auth/refresh.py)"
  ],
  "confidence": 0.85
}
```

**Key Behaviors:**
- Reads multiple files without polluting Actor context
- Compresses findings to essential information
- Provides file locations and signatures (not full code)
- Returns confidence score for search completeness
- Enables Actor to Read() only necessary files

**Model Used:** Sonnet (requires understanding code semantics)

**Usage Context:** Called by Actor when implementing features that integrate with existing code

**Performance:**
- Reads 10-50 files per invocation
- Outputs compressed summary (<2K tokens)
- Prevents Actor context bloat (would be 20-50K tokens if Actor read directly)

### 11. FinalVerifier

**Responsibility:** Adversarial verifier applying the "Four-Eyes Principle" — verifies the ENTIRE task goal is achieved, not just individual subtasks. Catches premature completion and hallucinated success.

**Input:**
```json
{
  "original_goal": "From .map/<branch>/task_plan_<branch>.md",
  "acceptance_criteria": "From task plan table",
  "completed_subtasks": "From progress_<branch>.md checkboxes",
  "validation_criteria": "From orchestrator"
}
```

**Output:**
```json
{
  "verdict": "PASS",
  "confidence": 0.95,
  "criteria_met": ["All acceptance criteria verified"],
  "root_cause": null,
  "recommendation": "COMPLETE"
}
```

**Verification Process:**
1. Read original goal and acceptance criteria from `.map/` checkpoint files
2. Verify each acceptance criterion against actual file state (Read, Grep, Bash)
3. Run tests if specified in validation criteria
4. Apply root cause analysis if verification fails
5. Return verdict: PASS → COMPLETE, FAIL → RE_DECOMPOSE or ESCALATE

**Model Used:** Sonnet (adversarial verification requires strong reasoning)

**Usage Context:** Mandatory final step in `/map-efficient` and invoked by `/map-check`

---

## MCP Integration

### Overview

MAP uses MCP (Model Context Protocol) servers for enhanced capabilities beyond base Claude Code functionality.

### Available MCP Servers

| MCP Server | Purpose | Required For | Performance Notes |
|------------|---------|--------------|-------------------|
| **sequential-thinking** | Chain-of-thought reasoning | Complex problem solving | Medium latency (~1-3s) |
| **deepwiki** | GitHub repository analysis | Research phase | Medium latency (~3-7s) |

### Configuration

MCP servers are configured differently depending on the usage context:

#### Project-Specific Configuration

**File:** `.claude/mcp_config.json`

```json
{
  "mcp_servers": {
    "sequential-thinking": {
      "enabled": true,
      "description": "Chain-of-thought reasoning for complex problems"
    },
    "deepwiki": {
      "enabled": true,
      "description": "GitHub repository analysis and documentation"
    }
  }
}
```

### MCP Tool Usage Patterns

#### Pattern 1: Documentation Lookup (Actor)

```markdown
**WHEN using external libraries or researching projects:**

1. Read wiki structure:
   - Tool: mcp__deepwiki__read_wiki_structure
   - Input: Repository owner/name (e.g., "pallets/flask")

2. Read wiki contents:
   - Tool: mcp__deepwiki__read_wiki_contents
   - Parameters: repo_name, page path

3. Use docs for:
   - API signature verification
   - Best practices
   - Deprecation warnings
```

### MCP Server Availability

**Commonly Available:**
- sequential-thinking (reasoning)

**May Require Installation:**
- deepwiki (check Claude Code documentation)

**To verify availability:**
```bash
# Inside Claude Code session
/tools list
```

### Performance Considerations

**Latency Budget (per subtask):**
- deepwiki docs: ~3-7s per fetch (Actor: 1-2 fetches)
- Total overhead: ~3-7s per subtask

**Optimization Strategies:**
- Batch similar searches where possible
- Enable MCP caching when available (Phase 2 roadmap)

---

## Customization Guide

### Modifying Agent Prompts

Agent prompts are located in `.claude/agents/*.md` and use **Handlebars template syntax** for dynamic context injection.

#### Safe Modifications

✅ **You CAN modify:**
- Instructions and examples
- MCP tool usage guidance
- Output format specifications
- Domain-specific requirements
- Validation criteria
- Decision frameworks

**Example:**
```markdown
# Add to Monitor agent:

## Additional Security Checks

- OWASP Top 10 compliance required
- All user inputs must be sanitized
- No hardcoded credentials allowed
- SQL queries must use parameterized statements
```

#### Unsafe Modifications

❌ **You CANNOT remove:**
- Template variables: `{{language}}`, `{{project_name}}`, `{{framework}}`
- Conditional blocks: `{{#if existing_patterns}}...{{/if}}`
- Context sections: `{{subtask_description}}`, `{{feedback}}`

**Why they're critical:**
- Orchestrator fills these at runtime with project context
- Removing them breaks multi-language support and feedback loops
- Git pre-commit hook validates their presence (see Hooks Integration)

#### Template Variable Reference

**Available in all agents:**
```handlebars
{{project_name}}           # e.g., "my-web-app"
{{language}}               # e.g., "Python", "JavaScript"
{{framework}}              # e.g., "Flask", "Next.js"
{{standards_doc}}          # Link to coding standards
```

**Actor-specific:**
```handlebars
{{subtask_description}}    # From TaskDecomposer
{{existing_patterns}}      # Relevant patterns from context
{{#if feedback}}           # Monitor feedback (retry loop)
  {{feedback}}
{{/if}}
{{allowed_scope}}          # Files allowed to modify
```

**Monitor-specific:**
```handlebars
{{#if feedback}}           # Previous iteration feedback
  {{feedback}}
{{/if}}
```

**Reflector-specific:**
```handlebars
{{plan_context}}           # Full workflow context
```

### Model Selection Per Agent

MAP Framework uses intelligent model selection to balance quality and cost.

**Current Configuration:**

| Agent | Model | Rationale |
|-------|-------|-----------|
| TaskDecomposer | sonnet-4-5 | Quality-critical: task planning |
| Actor | sonnet-4-5 | Quality-critical: code generation |
| Monitor | sonnet-4-5 | Quality-critical: validation |
| Predictor | sonnet-4-5 | Impact analysis requires complex reasoning |
| Evaluator | sonnet-4-5 | Evaluation requires nuanced judgment |
| Reflector | sonnet-4-5 | Quality-critical: pattern extraction |
| DocumentationReviewer | sonnet-4-5 | Quality-critical: doc validation |
| Synthesizer | sonnet-4-5 | Quality-critical: variant synthesis |
| DebateArbiter | opus-4-5 | Highest quality: cross-variant reasoning |
| ResearchAgent | sonnet-4-5 | Quality-critical: codebase understanding |

**Override Model Per Agent:**

Edit `.claude/agents/{agent}.md` frontmatter:

```yaml
---
model: claude-sonnet-4-5  # or claude-haiku-3-5
---
```

**Cost vs Quality Trade-offs:**
- **All Sonnet/Opus (current):** Highest quality, Opus only for DebateArbiter
- **Downgrade to Haiku:** Lower cost, risk of quality degradation in analysis and scoring

**Recommended:**
- Keep on Sonnet: TaskDecomposer, Actor, Monitor, Predictor, Evaluator, Reflector, DocumentationReviewer, Synthesizer, ResearchAgent
- Keep on Opus: DebateArbiter (cross-variant reasoning requires highest quality)
- Safe to downgrade to Haiku: Predictor, Evaluator (if cost reduction is priority)

### Adding Custom Agents

**Use Case:** Add domain-specific agent (e.g., SecurityAuditor, PerformanceOptimizer)

**Steps:**

1. **Create agent file:**
   ```bash
   touch .claude/agents/security-auditor.md
   ```

2. **Add YAML frontmatter:**
   ```yaml
   ---
   version: 1.0.0
   model: claude-sonnet-4-5
   last_updated: 2025-10-23
   ---
   ```

3. **Define agent role and context:**
   ```markdown
   # IDENTITY
   You are a security auditor specializing in OWASP Top 10 vulnerabilities.

   ## CONTEXT
   - **Project**: {{project_name}}
   - **Language**: {{language}}
   - **Framework**: {{framework}}
   ```

4. **Define output format:**
   ```markdown
   ## OUTPUT FORMAT

   ```json
   {
     "vulnerabilities": [
       {
         "severity": "critical|high|medium|low",
         "owasp_category": "A01:2021 - Broken Access Control",
         "description": "...",
         "suggested_fix": "...",
         "references": ["..."]
       }
     ]
   }
   ```
   ```

5. **Update orchestration:**
   Edit `.claude/commands/map-efficient.md` to call new agent:
   ```markdown
   ## After Monitor validates:

   **6. Security Audit** (SecurityAuditor):
   - Call: Task(subagent_type="security-auditor", input=actor_output)
   - Verify no critical vulnerabilities
   ```

### Adapting to Project Conventions

**Common Customizations:**

1. **Add project-specific coding standards:**
   Edit Actor agent:
   ```markdown
   ## PROJECT STANDARDS

   - Use TypeScript strict mode
   - All functions require JSDoc comments
   - Max function length: 50 lines
   - Prefer functional programming patterns
   ```

2. **Add custom validation rules:**
   Edit Monitor agent:
   ```markdown
   ## CUSTOM VALIDATION

   - [ ] All API endpoints have rate limiting
   - [ ] Database queries use connection pooling
   - [ ] Logs use structured JSON format
   ```

3. **Integrate with CI/CD:**
   Edit Evaluator agent:
   ```markdown
   ## CI/CD INTEGRATION

   **After approval:**
   - Run: `npm run lint`
   - Run: `npm test`
   - Run: `npm run build`
   - Only approve if all checks pass
   ```

### Template Variables in Custom Agents

**Access project context:**
```handlebars
{{project_name}}    # From .claude/config.json
{{language}}        # From .claude/config.json
{{framework}}       # From .claude/config.json
{{standards_doc}}   # From .claude/config.json
```

**Pass custom variables:**

In orchestrator prompt:
```markdown
Task(
  subagent_type="security-auditor",
  input={
    "code": actor_output,
    "compliance_level": "{{compliance_level}}"  # Custom variable
  }
)
```

In agent template:
```handlebars
{{compliance_level}}  # Will be filled by orchestrator
```

---

## Template Maintenance

### Template Validation

**Automated Linter:**

```bash
python scripts/lint-agent-templates.py
```

**Checks performed:**
1. ✅ YAML frontmatter completeness (version, last_updated, changelog)
2. ✅ Required sections present (mcp_integration, context, examples)
3. ✅ Template variable syntax (`{{variable}}` - no spaces)
4. ✅ XML tag matching (`<section></section>`)
5. ✅ MCP tool description consistency
6. ✅ Output format specifications

**Example output:**
```
✅ actor.md - PASSED
✅ monitor.md - PASSED
❌ predictor.md - FAILED
   - Missing section: <mcp_integration>
   - Unmatched tag: </examples>
   - Invalid template variable: {{ language }} (has spaces)
```

### Git Pre-Commit Hook

**Automatic validation before commits:**

Located at: `.git/hooks/pre-commit`

**Prevents commits if:**
- Template variables removed from agents
- Critical sections deleted (feedback, context)
- Massive deletions (>500 lines) without review

**Example block:**
```bash
❌ BLOCKED: Agent file is missing critical template variables!

File: .claude/agents/actor.md
Missing templates:
  - {{language}}
  - {{#if existing_patterns}}

These template variables are used by Orchestrator for context injection.
See .claude/agents/README.md for details.
```

**To bypass (emergency only):**
```bash
git commit --no-verify -m "message"
```

### Template Versioning

**Version Metadata:**

All agent templates include:
```yaml
---
version: 2.0.0
last_updated: 2025-10-17
changelog: .claude/agents/CHANGELOG.md
---
```

**Version Scheme (Semantic Versioning):**
- **Major (X.0.0):** Breaking changes (template variable removal, output format changes)
- **Minor (2.X.0):** New features (new MCP tool integration, new sections)
- **Patch (2.0.X):** Bug fixes, clarifications, typo fixes

**Changelog:**

Agent template changes are tracked in the project's main CHANGELOG.md.

**Example entry:**
```markdown
## [4.0.0] - 2025-01-14

### Breaking Changes
- Actor: Changed output format to include `used_patterns` array

### Fixed
- Monitor: Clarified validation criteria for error handling
```

### MCP Patterns Reference

**Centralized MCP guidance** is embedded directly in agent templates:

**Contents:**
- Common MCP tool usage patterns
- Decision frameworks for tool selection
- Agent-specific MCP integration guidelines
- Best practices and anti-patterns
- Troubleshooting common issues

**Usage:** Each agent template contains its own MCP Tool Selection Matrix with:
- Conditions for when to use each tool
- Query patterns for effective searches
- Skip conditions to avoid unnecessary calls

### Updating Strategies

**When to update agent templates:**

1. **Research insights:** New papers on prompt engineering, context engineering
2. **Performance degradation:** Monitor approval rate drops, Evaluator scores decline
3. **New MCP tools:** Additional capabilities become available
4. **User feedback:** Agents consistently make same mistakes

**Update Process:**

1. **Analyze metrics:**
   ```bash
   python scripts/analyze-metrics.py
   # Check: approval rate, iteration count, quality scores
   ```

2. **Identify root cause:**
   - Low Monitor approval → Actor needs better guidance
   - High iteration count → Monitor giving unclear feedback
   - Low Evaluator scores → Evaluator rubric too strict/loose

3. **Update template:**
   - Add examples of correct behavior
   - Clarify ambiguous instructions
   - Update MCP tool usage patterns

4. **Validate:**
   ```bash
   python scripts/lint-agent-templates.py
   ```

5. **Test:**
   - Run `/map-efficient` on known task
   - Compare metrics before/after
   - Ensure no regressions

6. **Document:**
   - Update `version` and `last_updated` in frontmatter
   - Add entry to CHANGELOG.md
   - Update MCP Tool Selection Matrix in agent template if tool usage changed

**Rollback if needed:**
```bash
git checkout HEAD~1 .claude/agents/actor.md
```

---

## Context Engineering

MAP Framework applies cutting-edge context engineering principles for AI agents, based on research from Manus.im and academic papers.

### Recitation Pattern (Phase 1.1)

**Problem:** On long tasks (5+ subtasks), models lose focus and forget goals as context window fills.

**Solution:** Attention focus mechanism — `.map/progress.md` is updated before each step, keeping goals "fresh" in the context window.

**Mechanism:**

1. **TaskDecomposer** creates initial plan:
   ```markdown
   # Task: feat_auth
   ## Goal: Implement JWT authentication
   ## Subtasks:
   - [ ] 1/5: Create User model
   - [ ] 2/5: Implement login endpoint
   - [ ] 3/5: Add token validation middleware
   - [ ] 4/5: Add refresh token logic
   - [ ] 5/5: Write integration tests
   ```

2. **Orchestrator** updates before each subtask:
   ```markdown
   # Current Task: feat_auth
   ## Progress: 2/5 completed
   - [✓] 1/5: Create User model
   - [→] 2/5: Implement login endpoint (CURRENT, Iteration 2)
     - Last error: Missing JWT import
   - [☐] 3/5: Add token validation middleware
   - [☐] 4/5: Add refresh token logic
   - [☐] 5/5: Write integration tests
   ```

3. **Actor** receives plan in context:
   ```handlebars
   ## Current Task Plan (Recitation Pattern)

   {{plan_context}}

   **Your current subtask is marked with (CURRENT)**
   ```

**Implementation:**

Workflow state is managed through file-based persistence in `.map/` directory:
- `.map/progress.md` - Workflow checkpoint (YAML frontmatter + markdown body)
- `.map/<branch>/task_plan_*.md` - Task decomposition with validation criteria
- `.map/dev_docs/context.md` - Project context
- `.map/dev_docs/tasks.md` - Task checklist

**Benefits:**
- ✅ +20-30% success rate on complex tasks (5+ subtasks)
- ✅ -20-30% token usage (prevents re-explaining context)
- ✅ +50% observability (clear progress tracking)
- ✅ Error context persistence (retry loops retain error history)

### Context-Aware Step Injection (Phase 1.2)

**Problem:** When a plan has 10+ subtasks, injecting the entire plan and all logs wastes tokens and dilutes attention on the current step.

**Solution:** Two-layer "active window" injection that shows only relevant context:

1. **Hook layer** (`workflow-context-injector.py` PreToolUse hook):
   - Fires on every Edit/Write/significant Bash command
   - Injects ≤500 char reminder: goal + current subtask title + progress
   - Uses `load_goal_and_title()` to extract goal from `task_plan.md` and title from `blueprint.json`
   - Graceful fallback to original format when blueprint missing

2. **Actor prompt layer** (`map-efficient.md` ACTOR phase):
   - Fires once per subtask when Actor agent is spawned
   - Injects structured `<map_context>` block (target: ≤4 000 tokens, best-effort) containing:
     - `# Goal` — one sentence from task_plan.md
     - `# Current Subtask` — full AAG contract, affected files, validation criteria
     - `# Plan Overview` — all subtasks as one-liners with `[x]/[ ]/[>>]` status markers
     - `# Upstream Results` — only results from dependency subtasks (from `step_state.json subtask_results`)
     - `# Repo Delta` — files changed since last subtask (via `git diff` from `last_subtask_commit_sha`)
   - Built by `build_context_block()` in `map_step_runner.py`

**Key data sources:**
- `blueprint.json` — subtask metadata (deps, files, criteria). Single source of truth.
- `step_state.json` — `subtask_results` dict (per-subtask files_changed + status), `last_subtask_commit_sha`
- `task_plan.md` — goal text only (never parsed for structured data)

**Benefits:**
- 30-60% fewer tokens in system prompt on long workflows
- Actor focuses on current subtask criteria, not future steps
- Dependency results passed explicitly — no re-reading completed files

### Compaction Resilience

**Problem:** Context compaction (conversation history clearing) would normally lose workflow state, forcing restart from scratch.

**Solution:** File-based persistence architecture where all workflow state persists to disk, surviving compaction.

**Architecture:**

```
Filesystem (persists forever)           Conversation Memory (clears on compaction)
─────────────────────────────           ─────────────────────────────────────────
.map/
├── current_plan.json                   ← Structured state
│   ├── task_id, goal                   ← NEVER lost
│   ├── subtasks[]
│   │   ├── id, description
│   │   ├── status (pending/in_progress/completed)
│   │   ├── iterations, errors
│   │   └── depends_on[]
│   └── current_subtask_id
│
├── progress.md                         ← Workflow checkpoint
│   ├── YAML frontmatter (machine state)
│   └── Markdown body (human-readable)
│
├── task_plan_*.md                      ← Task decomposition
│   └── Subtasks with validation criteria
│
└── dev_docs/
    ├── context.md                      ← Project-specific context
    └── tasks.md                        ← Auto-generated task list
```

**Persistence Mechanism:**

1. **Automatic Saves** (every workflow step):
   - Status changes automatically update `.map/progress.md`
   - WorkflowState class handles serialization/deserialization

2. **Recovery Workflow** (after compaction):
   ```
   User: /map-resume

   Claude: ## Found Incomplete Workflow
           Progress: 3/5 completed
           Resume from last checkpoint? [Y/n]

   User: Y

   Claude: Resuming workflow from ST-004...
           [continues Actor→Monitor loop]
   ```

**Why This Works:**

| Storage Type | Compaction Effect | MAP's Choice |
|-------------|-------------------|--------------|
| Conversation memory | ❌ Cleared | Not used for state |
| File system (.map/) | ✅ Persists | Used for all state |
| Automatic updates | ✅ Always current | No manual checkpointing |

**Comparison to Manual Approaches:**

- **Manual checkpointing** (e.g., "/update-dev-docs"): Requires user to remember command before compaction. Risk of forgetting.
- **MAP's approach**: Automatic persistence with optional checkpoint command for guidance. Zero cognitive load.

**Benefits:**
- ✅ **Zero data loss** - All progress persists across compactions
- ✅ **Automatic** - No manual checkpointing required
- ✅ **Always current** - Files update on every status change
- ✅ **Cross-session** - Resume in any new conversation

**Implementation:**
- Checkpoint: `.map/progress.md` (YAML frontmatter + markdown body)
- Task plan: `.map/<branch>/task_plan_*.md` (subtask decomposition with validation criteria)
- Recovery: `/map-resume` command (detects checkpoint and offers to resume)

### Automatic Recovery (Phase 2)

**Problem:** Manual recovery (Phase 1) requires users to reference checkpoint files after compaction, adding cognitive load and causing 60% workflow abandonment rate.

**Solution:** `/map-resume` command detects `.map/progress.md` checkpoint and offers to resume incomplete workflow with a simple Y/n prompt.

**Architecture:**

```
User runs /map-resume command
        ↓
Command checks .map/progress.md existence
        ↓
    [Checkpoint exists?]
        ↓ Yes
    Parse YAML frontmatter for workflow state
        ↓
    Display progress summary:
    - Task plan
    - Completed subtasks (with checkmarks)
    - Remaining subtasks
        ↓
    Prompt: "Resume from last checkpoint? [Y/n]"
        ↓
    [User confirms?]
        ↓ Yes
    Load task plan from .map/<branch>/task_plan_*.md
        ↓
    Continue Actor→Monitor loop for remaining subtasks
        ↓
    [Workflow continues from checkpoint]
```

**Implementation:**

| Component | Location | Purpose |
|-----------|----------|---------|
| Resume command | `.claude/commands/map-resume.md` | User-facing recovery workflow |
| WorkflowState class | `src/mapify_cli/workflow_state.py` | Checkpoint serialization/deserialization |
| Checkpoint file | `.map/progress.md` | YAML frontmatter + markdown progress |
| Task plan | `.map/<branch>/task_plan_*.md` | Subtask decomposition with validation |
| Unit tests | `tests/test_workflow_state.py` | WorkflowState logic coverage |

**Execution Flow:**

1. **User runs `/map-resume`** - Explicit recovery command (no auto-injection)
2. **Command checks checkpoint** - Tests if `.map/progress.md` exists
3. **YAML frontmatter parsed** - WorkflowState.load() extracts machine state
4. **Progress summary displayed** - Shows completed/remaining subtasks
5. **User confirms Y/n** - Simple prompt, Y resumes, n clears checkpoint
6. **Task plan loaded** - Full decomposition with validation criteria
7. **Workflow resumes** - Actor→Monitor loop continues from last incomplete subtask

**Security Validation (Defense-in-Depth):**

All validation layers use AND logic - checkpoint must pass **all 4 layers** to be injected.

**Layer 1: Path Traversal Prevention**

*Rationale:* Prevent attackers from injecting arbitrary files (e.g., `../../../etc/passwd`)

*Implementation:*
```python
# Resolve to absolute path (handles .., symlinks)
resolved = Path(file_path).resolve()
base_path = Path(".map").resolve()

# Security check: Ensure resolved path is within .map/
if not resolved.is_relative_to(base_path):
    return {"valid": False, "error": "Path traversal detected"}
```

*Rejects:*
- Absolute paths outside `.map/`
- Symlinks pointing outside `.map/`
- Relative paths with `../` escaping `.map/`

**Layer 2: Size Bomb Protection**

*Rationale:* Prevent memory exhaustion attacks via multi-GB files

*Implementation:*
```python
MAX_FILE_SIZE_BYTES = 256 * 1024  # 256KB

# Check size BEFORE reading into memory
size_bytes = file_path.stat().st_size

if size_bytes > MAX_FILE_SIZE_BYTES:
    return {"valid": False, "error": f"File too large: {size_kb}KB exceeds 256KB limit"}
```

*Performance:* File size check completes in <0.05s without loading file content

**Layer 3: UTF-8 Validation**

*Rationale:* Prevent binary file injection (executables, images, malformed text)

*Implementation:*
```python
# Strict UTF-8 decoding - raises UnicodeDecodeError on invalid bytes
content = file_path.read_text(encoding='utf-8', errors='strict')
```

*Rejects:*
- Binary files (executables, images)
- Non-UTF-8 encoded text
- Files with invalid byte sequences

**Layer 4: Content Sanitization**

*Rationale:* Prevent terminal injection via ANSI escape codes and control characters

*Implementation:*
```python
# Regex strips control characters except newlines (\n) and tabs (\t)
CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b-\x0d\x0e-\x1f\x7f\u0080-\u009f\u2028\u2029]')

sanitized = CONTROL_CHAR_PATTERN.sub('', content)
```

*Removes:*
- NULL bytes (`\x00`)
- ANSI escape codes (`\x1b[...`)
- Carriage returns (`\r`) for terminal safety
- Unicode control characters (`\u2028`, `\u2029`)

*Preserves:*
- Newlines (`\n`) - Required for markdown formatting
- Tabs (`\t`) - Required for code indentation

**Bash Hook Limitations:**

Claude Code hooks run in subprocess with restricted capabilities:

| Capability | Available? | Workaround |
|-----------|-----------|-----------|
| MCP tool access | ❌ No | Hooks can't call MCP tools like `sequential-thinking` |
| Python imports | ❌ No | Must call separate Python script via subprocess |
| Async operations | ❌ No | Synchronous execution only (5s timeout) |
| External scripts | ✅ Yes | Can call `python3`, `jq`, bash utilities |
| Filesystem access | ✅ Yes | Direct read/write to `.map/` directory |

**Why no MCP tools?** Hooks execute in isolated subprocess without access to Claude Code's MCP server connections. Use helpers for complex logic.

**Performance Characteristics:**

| Metric | Typical | Maximum | Notes |
|--------|---------|---------|-------|
| Total execution time | <0.5s | 5s | Hook timeout enforced by Claude Code |
| Validation overhead | ~0.1s | 0.2s | 4-layer security checks |
| File I/O | <0.05s | 0.1s | Read 256KB checkpoint file |
| JSON parsing | <0.01s | 0.02s | Parse validator output with `jq` |

**Test Results (64 total tests):**
- ✅ 41 unit tests (validation logic) - 95% coverage
- ✅ 23 integration tests (end-to-end hook) - All pass
- ✅ Security tests: Path traversal, size bombs, control characters, UTF-8 errors
- ✅ Performance tests: <0.5s for 5KB checkpoint, <1s for 256KB checkpoint

**Integration with .map/ Persistence:**

**Without Recovery** vs **With /map-resume**:

```
Without Recovery                       With /map-resume
────────────────                       ────────────────
Context exhausted                      Context exhausted
        ↓                                      ↓
Workflow state lost                    .map/progress.md persists
        ↓                                      ↓
Start over from scratch                User runs /map-resume
        ↓                                      ↓
Re-explain everything                  Checkpoint parsed
        ↓                                      ↓
[Workflow abandoned]                   Progress summary shown
                                               ↓
                                       User confirms Y/n
                                               ↓
                                       [Workflow continues]
```

**Key Differences:**

| Aspect | Phase 1 (Manual) | Phase 2 (Automatic) |
|--------|------------------|---------------------|
| User action required | ✅ Yes (copy/paste paths) | ❌ No (zero-touch) |
| Cognitive load | Medium (remember 3 file paths) | Zero (invisible) |
| Error prone | Yes (typos, wrong files) | No (validated automatically) |
| Workflow abandonment | ~30% (users forget) | ~5% (edge cases only) |
| Time to resume | 30-60s (manual steps) | 0s (instant) |

**Benefits:**

- ✅ **Zero cognitive load** - Users never think about compaction recovery
- ✅ **Seamless UX** - Invisible to users, "just works" experience
- ✅ **Secure by design** - 4-layer validation prevents all known attack vectors
- ✅ **Always current** - Reads latest checkpoint (auto-saved by Phase 1)
- ✅ **Non-blocking** - Hook failures don't prevent session start (exit 0)
- ✅ **Observable** - Logs to stderr for debugging (`[session-start] ...`)
- ✅ **Tested** - 64 tests with >90% coverage

**Failure Modes & Handling:**

All failures are non-blocking - hook returns `{"continue": true}` and logs error to stderr:

| Failure Scenario | Hook Behavior | User Impact |
|------------------|---------------|-------------|
| No checkpoint file | Skip injection, continue | None (new session, expected) |
| Validator script missing | Skip injection, continue | None (fallback to Phase 1 manual) |
| Path traversal detected | Reject file, continue | None (security protection) |
| File too large (>256KB) | Reject file, continue | None (size bomb protection) |
| Invalid UTF-8 encoding | Reject file, continue | None (binary file protection) |
| Control characters found | Sanitize + inject | None (transparent cleanup) |
| Validator crashes | Skip injection, continue | None (error logged to stderr) |

**Design Principle:** Session start must **always succeed**. Security validation prevents injection of malicious content, but never blocks users from starting new sessions.

**References:**

- User research: Reddit feedback analysis showing 60% manual recovery confusion rate
- Implementation: Phase 2 addresses Monitor finding: "Missing compaction recovery workflow docs"

### Workflow Logging (Phase 1.2)

**Problem:** Debugging failed workflows requires manual correlation of agent outputs.

**Solution:** Structured logging with workflow context in `.map/workflow_logs/`.

**Log Format:**

**Note:** `subtask_id` is an **integer** (not string) matching the `id` field from TaskDecomposer output. TaskDecomposer generates subtask IDs as sequential integers: 1, 2, 3, etc.

```json
{
  "task_id": "feat_auth_20251023_143022",
  "goal": "Implement JWT authentication",
  "start_time": "2025-10-23T14:30:22Z",
  "subtasks": [
    {
      "subtask_id": 1,
      "description": "Create User model",
      "status": "completed",
      "iterations": 1,
      "agents": {
        "actor": {
          "start_time": "2025-10-23T14:30:25Z",
          "end_time": "2025-10-23T14:31:10Z",
          "duration_seconds": 45,
          "output_summary": "Generated User model with password hashing"
        },
        "monitor": {
          "validation_passed": true,
          "issues": []
        },
        "evaluator": {
          "overall_score": 8.5,
          "approved": true
        }
      }
    }
  ]
}
```

**Implementation:**

- Class: `MapWorkflowLogger` (246 lines)
- Location: `scripts/utils/map_workflow_logger.py`
- API:
  ```python
  logger = MapWorkflowLogger(task_id, goal)
  logger.start_subtask(subtask_id, description)
  logger.log_agent_output(agent_name, output)
  logger.complete_subtask(subtask_id, status="completed")
  logger.finalize()
  ```

**Benefits:**
- ✅ Post-mortem analysis of failures
- ✅ Performance benchmarking per agent
- ✅ Audit trail for compliance
- ✅ Metrics dashboard input

### Template Optimization (Phase 1.3)

**Problem:** Verbose agent outputs waste tokens without adding value.

**Changes:**

1. **Monitor:** Reduced validation output verbosity (-9.6% tokens)
   - Before: Full code review with line-by-line feedback
   - After: Issue summaries with severity and category

2. **Evaluator:** Structured scoring format
   - Before: Prose explanation of scores
   - After: JSON scores + brief rationale

**Results:**
- ✅ 9.6% overall token reduction (Monitor, Evaluator)
- ✅ Maintained validation quality (no decrease in approval rates)
- ✅ Faster parsing of agent outputs

### Context Engineering Roadmap

**Phase 1 ✅ COMPLETED** (2025-10-18):
- [x] **RecitationManager** (482 lines): Recitation Pattern for focus
- [x] **MapWorkflowLogger** (246 lines): Detailed workflow logging
- [x] **Pattern limit=5**: Limit retrieved patterns
- [x] **Template Optimization**: Optimize verbose outputs (-9.6% tokens)

**Phase 1 Results:**
- ✅ 9.6% reduction in token usage (Monitor, Evaluator templates)
- ✅ Documentation-driven orchestration architecture
- ✅ 728 lines of new infrastructure

**Phase 2** (Prioritized):
1. **Checkpoints** (high impact) — Workflow resumption after interruption
2. **MCP caching** (medium-high) — Latency reduction for MCP servers
3. **Keyword+semantic search** (medium) — Hybrid retrieval accuracy
4. **Pattern variation** (low-medium) — Few-shot bias reduction

**Phase 3-4:** Parallelism, auto-testing, temperature per agent

**Research Foundation:**
- ["Context Engineering for AI Agents" (Manus.im, 2025)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

---

## Success Metrics

**Target KPIs:**
- **Monitor approval rate:** >80% first try (current: varies by task complexity)
- **Evaluator scores:** average >7.0/10 (approval threshold)
- **Iteration count:** <3 per subtask (indicates clear feedback)
- **Knowledge growth:** increasing high-quality patterns over time

**Tracking:**
```bash
# View metrics dashboard
python scripts/analyze-metrics.py

# Check specific workflow
cat .map/workflow_logs/feat_auth_20251023_143022.json | jq '.subtasks[].agents.evaluator.overall_score'
```

---

## References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [Context Engineering for AI Agents (Manus.im)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)

---

**For usage examples and best practices, see [USAGE.md](USAGE.md).**
**For installation and setup, see [README.md](../README.md).**
