---
description: Optimized workflow with batched learning (RECOMMENDED for token-conscious production work)
---

# MAP Efficient Workflow

**CRITICAL INSTRUCTION:** This is an **automated sequential workflow**. You MUST execute ALL steps from start to finish without stopping. After calling each subagent, IMMEDIATELY proceed to the next step in the workflow. DO NOT wait for user input between steps.

**🚨 ABSOLUTELY FORBIDDEN 🚨**

You are **STRICTLY PROHIBITED** from:

❌ **"Optimizing" the workflow by skipping agents** - Each agent MUST be called
❌ **"Using general-purpose instead of specialized agents"** - USE the correct subagent_type
❌ **"Combining steps to save time"** - Each agent MUST be called individually
❌ **Any variation of "I'll optimize by..."** - NO ADDITIONAL OPTIMIZATION ALLOWED

**YOU MUST:**
✅ Call task-decomposer FIRST (not general-purpose)
✅ Call actor for EACH subtask (not general-purpose)
✅ Call monitor after EACH actor (not general-purpose)
✅ Verify each agent used required MCP tools (check output)

---

**✅ RECOMMENDED: Best Balance of Speed and Quality**

This workflow provides **intelligent token optimization (30-40% savings)** while **preserving MAP's core value**:

✅ **Impact Analysis** (Predictor) → Conditional on risk level
✅ **Basic Validation** (Monitor) → Always enforced
✅ **Learning** → OPTIONAL via `/map-learn` command after workflow

**Token Savings vs Full Workflow:**
- Skip Evaluator per subtask: ~8-12% savings
- Conditional Predictor: ~5-10% savings
- Optional learning (not automatic): ~15-20% savings
- **Total: 40-50% token reduction**

**When to use /map-efficient:**
- Production code where token costs matter
- Well-understood tasks with low risk
- Iterative development with frequent workflows
- Any task where /map-fast feels too risky but /map-feature too expensive

**When to use /map-feature instead:**
- First time implementing critical functionality
- High-risk changes (security, authentication, data handling)
- Complex refactoring across many files
- When maximum quality assurance is required

---

## Self-MoA Configuration (Optional)

**Self-MoA** (Self-Mixture of Agents) generates 3 implementation variants and **synthesizes** the best parts into an optimal combined solution.

**Activation:**
- **Explicit:** User includes `--self-moa` flag: `/map-efficient --self-moa "task"`
- **Auto:** TaskDecomposer marks subtask as `complexity: high` OR `security_critical: true`

**Token Cost:**
- ~4x standard per subtask (3 Actors + 3 Monitors + Synthesizer + Final Monitor)
- Use only for critical subtasks where quality improvement justifies cost

**When to use Self-MoA:**
- Security-critical implementations (authentication, authorization, data validation)
- Complex algorithms where multiple approaches could work
- Tasks where you want the best of security, performance, AND simplicity

**When NOT to use Self-MoA:**
- Simple CRUD operations
- Configuration changes
- Documentation updates
- When token budget is constrained

---

Implement the following with efficient workflow:

**Task:** $ARGUMENTS

## Workflow Overview

Optimized agent sequence (no automatic learning):

```
1. DECOMPOSE → task-decomposer
2. FOR each subtask:
   2.1. PLAYBOOK → get context
   2.1a. ELIGIBILITY → check Self-MoA activation
   2.2. RESEARCH (optional) → research-agent if existing code understanding needed

   ┌─── IF Self-MoA ENABLED ───────────────────────────────┐
   │ 2.3a. PARALLEL ACTORS → 3 variants (security, perf, simplicity)
   │ 2.3b. PARALLEL MONITORS → validate each variant
   │ 2.3c. SYNTHESIZER → combine best parts
   │ 2.3d. FINAL MONITOR → validate synthesized code
   └───────────────────────────────────────────────────────┘
   ┌─── ELSE (Standard Path) ─────────────────────────────┐
   │ 2.3. IMPLEMENT → actor
   │ 2.4. VALIDATE → monitor
   └───────────────────────────────────────────────────────┘

   2.5. If invalid: provide feedback, retry (max 3-5 iterations)
   2.6. If high_risk: ANALYZE → predictor
   2.7. ACCEPT and apply changes
3. DONE → Suggest /map-learn if user wants to preserve lessons
```

**Key Optimizations:**
- **Evaluator skipped** → Monitor provides sufficient validation for most tasks
- **Predictor conditional** → Only called when Monitor flags high risk
- **Learning optional** → User runs `/map-learn` separately if desired

## Step 1: Load Playbook Context

Use `mapify playbook query` or `mapify playbook search` to get relevant patterns from the playbook SQLite database.

## Step 1.1: Task Decomposition

Call the task-decomposer subagent (NOT general-purpose):

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="Break down this task into atomic subtasks (≤8):

Task: $ARGUMENTS

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, estimated_complexity, risk_level, depends_on}
- total_subtasks: number
- estimated_duration: string

**IMPORTANT**: Assign risk_level ('low'|'medium'|'high') to each subtask based on:
- 'high': Security-sensitive, breaking changes, multi-file modifications
- 'medium': Moderate complexity, some dependencies
- 'low': Simple, isolated changes

Risk level determines if Predictor is called (high/medium = yes, low = no)."
)
```

## Step 2: For Each Subtask - Efficient Loop

### Step 2.1: Get Relevant Playbook Context

**Step A: Query Local Playbook**:

```bash
# Query playbook using FTS5 (project-specific patterns)
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)
```

**Step B: Search Cipher** (optional but recommended):

```
# Get cross-project patterns via MCP tool
mcp__cipher__cipher_memory_search(
  query="[subtask concept]",
  top_k=5
)
```

**Benefits over grep/read:**
- Works with large playbooks (>256KB)
- FTS5 full-text search with relevance ranking
- Quality-scored results
- Cipher adds cross-project validated patterns

### Step 2.2: Research Phase (Context Isolation)

IF subtask requires understanding existing code patterns:
- Refactoring or extending existing code
- Bug fixes requiring code comprehension
- Adapting patterns from other modules
- Any task touching 3+ files

**Skip research for:** new standalone features, documentation, configuration updates

**Call research-agent:**

```
Task(
  subagent_type="research-agent",
  description="Research for subtask [ID]",
  prompt="Query: [subtask description]\nFile patterns: [relevant globs from task-decomposer]\nSymbols: [keywords from subtask]\nIntent: locate\nMax tokens: 1500"
)
```

**Handle results:**

IF research.confidence >= 0.7:
  → Pass research.executive_summary to Actor
  → Pass research.relevant_locations to Actor
  → Actor can Read() full code by path:lines if needed

IF research.confidence < 0.7:
  → Consider broadening search
  → Or proceed with warning to Actor

IF research.status == "DEGRADED_MODE":
  → Note in Actor prompt that search was limited
  → Actor should verify findings more carefully

**Then proceed to step 2.1a (Self-MoA Check) or 2.3 (Actor)**

### Step 2.1a: Self-MoA Eligibility Check

**Check if Self-MoA should be activated:**

```python
self_moa_enabled = (
    "--self-moa" in user_command OR
    subtask.complexity == "high" OR
    subtask.security_critical == True
)
```

**If Self-MoA enabled:** Execute Steps 2.3a-2.3d (Self-MoA Path)
**If Self-MoA disabled:** Execute Steps 2.3-2.4 (Standard Path)

---

## Self-MoA Path (Steps 2.3a-2.3d)

### Step 2.3a: Parallel Actor Generation

Call Actor 3 times with different optimization focuses:

```
# Actor Variant 1: Security Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Security Focus (v1)",
  prompt="Implement this subtask with SECURITY focus:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]
**approach_focus:** security
**self_moa_mode:** true
**variant_id:** v1

Focus on:
- Input validation and sanitization
- OWASP compliance
- Defensive coding patterns
- Parameterized queries

Output JSON with:
- approach, code_changes, trade_offs, testing_approach, used_bullets
- **decisions_made:** array of {category, statement, rationale, priority_class}"
)

# Actor Variant 2: Performance Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Performance Focus (v2)",
  prompt="... approach_focus: performance, variant_id: v2
Focus on: Algorithm efficiency, caching, async patterns, minimal allocations"
)

# Actor Variant 3: Simplicity Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Simplicity Focus (v3)",
  prompt="... approach_focus: simplicity, variant_id: v3
Focus on: Readability, standard patterns, clear structure, explicit over clever"
)
```

**Execute all 3 Actor calls in parallel** to minimize latency.

### Step 2.3b: Parallel Monitor Validation

Validate each variant independently:

```
# Monitor for Variant 1
Task(
  subagent_type="monitor",
  description="Validate v1 (security focus)",
  prompt="Review variant v1:
**Actor Output:** [v1 output]
**variant_id:** v1
**self_moa_mode:** true

Output JSON with:
- valid, issues, verdict, feedback
- **decisions_identified:** array of Decision objects
- **compatibility_features:** {error_paradigm, concurrency_model, state_management, type_strictness, naming_convention, imports_used}
- **contract_compliant:** boolean
- **strengths:** array, **weaknesses:** array
- **recommended_as_base:** boolean"
)

# Monitor for Variant 2 and 3 (parallel)
Task(subagent_type="monitor", ... variant_id: v2)
Task(subagent_type="monitor", ... variant_id: v3)
```

**Execute all 3 Monitor calls in parallel.**

### Step 2.3c: Synthesizer - Combine Best Parts

**Compute compatibility score** (orchestrator deterministic calculation):

```python
# Use Monitor's compatibility_features for pairwise scoring
WEIGHTS = {
    "error_paradigm": 2.0,      # CRITICAL
    "concurrency_model": 2.0,   # CRITICAL
    "state_management": 1.5,
    "type_strictness": 1.0,
    "naming_convention": 0.5,
}

def pairwise_score(m1, m2):
    total = 0
    for dim, weight in WEIGHTS.items():
        if m1.compatibility_features[dim] == m2.compatibility_features[dim]:
            total += weight
    return total / sum(WEIGHTS.values())

compatibility_score = min(
    pairwise_score(m1, m2),
    pairwise_score(m1, m3),
    pairwise_score(m2, m3)
)
```

**Call Synthesizer:**

```
Task(
  subagent_type="synthesizer",
  description="Synthesize best implementation",
  prompt="Synthesize the best parts from 3 variants:

**Variants:**
- v1: [Actor v1 output]
- v2: [Actor v2 output]
- v3: [Actor v3 output]

**Monitor Results:**
- m1: [Monitor v1 output with decisions_identified, compatibility_features]
- m2: [Monitor v2 output]
- m3: [Monitor v3 output]

**Compatibility Score:** [computed score]
**Priority Policy:** [correctness, maintainability, security, performance]

Extract decisions, resolve conflicts, generate unified code.

Output JSON with:
- code: complete synthesized implementation
- decisions_implemented: array of decision IDs
- decisions_rejected: array of [ID, reason]
- strategy_used: 'base_enhance' | 'fresh_generation'
- conflict_resolutions: array
- confidence: float"
)
```

### Step 2.3d: Validate Synthesized Solution

**Call Monitor to validate final code:**

```
Task(
  subagent_type="monitor",
  description="Validate synthesized implementation",
  prompt="Review synthesized implementation:

**Synthesizer Output:** [synthesizer output]
**variant_id:** synthesized

Check for:
- All decisions properly implemented
- No conflicting patterns introduced
- Code coherence and consistency
- Contract compliance

Output standard Monitor JSON (valid, issues, verdict, feedback)"
)
```

**If monitor.valid === false:**
- Provide feedback to Synthesizer
- Retry synthesis (max 2 iterations)

**If monitor.valid === true:**
- Continue to Step 2.6 (Predictor if high_risk) or Step 2.7 (Apply)

---

## Standard Path (Steps 2.3-2.4)

### Step 2.3: Call Actor to Implement

**⚠️ MUST use subagent_type="actor"** (NOT general-purpose):

```
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement this subtask:

**Subtask:** [description]
**Acceptance Criteria:** [criteria]
**Risk Level:** [risk_level from TaskDecomposer]

**Relevant Playbook Context:**
[Include 3-5 relevant bullets from playbook]

Output JSON with:
- approach: string (implementation strategy)
- code_changes: array of {file_path, change_type, content, rationale}
- trade_offs: array of strings
- testing_approach: string
- used_bullets: array of bullet IDs that were helpful

Provide FULL file content for each change, not diffs."
)
```

### Step 2.4: Call Monitor to Validate

**⚠️ MUST use subagent_type="monitor"** (NOT general-purpose):

```
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt="Review this implementation:

**Actor Output:** [paste actor JSON]

Check for:
- Code correctness
- Security issues
- Basic performance concerns
- Test coverage
- Standards compliance

**RISK ASSESSMENT**: Flag if:
- Security vulnerabilities detected
- Breaking API changes likely
- Multiple files modified (>3)
- Complex dependencies involved

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description, file_path, line_range}
- verdict: 'approved' | 'needs_revision' | 'rejected'
- feedback: string (actionable guidance)
- **high_risk_detected**: boolean (if true, Predictor will be called)"
)
```

### Step 2.5: Decision Point

**If monitor.valid === false:**
- Provide feedback to actor
- Go back to step 2.3 (max 3-5 iterations)

**If monitor.valid === true:**
- Continue to step 2.6

### Step 2.6: Conditional Predictor (Token Optimization)

**Only call Predictor if:**
- `monitor.high_risk_detected === true`, OR
- `subtask.risk_level === 'high'` or `'medium'`

**Skip Predictor if:**
- `subtask.risk_level === 'low'` AND
- `monitor.high_risk_detected === false`

**⚠️ MUST use subagent_type="predictor"** (NOT general-purpose):

```
Task(
  subagent_type="predictor",
  description="Analyze implementation impact",
  prompt="Analyze the impact of this implementation:

**Actor Output:** [paste actor JSON]
**Monitor Verdict:** approved
**Risk Trigger:** [why Predictor was called: subtask.risk_level or monitor flag]

Analyze:
- Affected files and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Migration requirements
- Rollback strategy

Output JSON with:
- affected_files: array of {path, change_type, impact_level}
- breaking_changes: array of {type, description, mitigation}
- required_updates: array of strings
- risk_level: 'low' | 'medium' | 'high'
- rollback_plan: string"
)
```

**Token Savings Note:** Skipping Predictor for low-risk tasks saves ~2-3K tokens per subtask.

### Step 2.7: Apply Changes

- Apply code changes using Write/Edit tools
- Mark subtask completed

### Step 2.8: Move to Next Subtask

Repeat steps 2.1-2.7 for each remaining subtask.

## Step 3: Final Summary

Run tests (if applicable), create commit, and summarize:
- Features implemented
- Files changed
- Overall quality
- **Token efficiency:**
  - Predictor calls: [count] / [total_subtasks] subtasks ([X]% saved)
  - Learning skipped: ~15-20% additional savings
  - Estimated token savings: ~40-50% vs /map-feature

---

## 💡 Optional: Preserve Lessons Learned

**If you want to save patterns from this workflow for future use:**

```
/map-learn [workflow summary with actor outputs, monitor results, files changed]
```

This is **completely optional**. Run it when:
- You discovered valuable patterns worth preserving
- The implementation approach could help future similar tasks
- You want to update the playbook with new insights

Skip `/map-learn` when:
- The task was routine with no novel patterns
- You're iterating quickly and learning overhead isn't worth it
- Token budget is constrained

## MCP Tools Available

- `mcp__cipher__cipher_memory_search` - Search past implementations
- `mcp__cipher__cipher_extract_and_operate_memory` - Store successful patterns
- `mcp__sequential-thinking__sequentialthinking` - Complex decision making
- `mcp__context7__get-library-docs` - Get library documentation
- `mcp__claude-reviewer__request_review` - Request code review

## Comparison: /map-efficient vs Alternatives

| Feature | /map-feature (Full) | /map-efficient (YOU) | /map-fast (Minimal) |
|---------|---------------------|----------------------|---------------------|
| **Validation** | Monitor + Evaluator | Monitor only | Monitor only |
| **Impact Analysis** | Always (Predictor) | Conditional | Never |
| **Learning** | Per-subtask | Optional (/map-learn) | None |
| **Quality Gates** | All agents | Essential agents | Basic only |
| **Token Usage** | 100% (baseline) | **50-60%** | 40-50% |
| **Production Safe** | ✅ Maximum | ✅ Yes | ❌ No |
| **Knowledge Growth** | ✅ Full | 🔸 On-demand | ❌ None |
| **Best For** | Critical features | **Most tasks** | Throwaway only |

## Critical Constraints

- **Predictor conditional** on risk level (saves tokens for low-risk tasks)
- **Evaluator skipped** (Monitor provides sufficient validation)
- **Learning optional** — run `/map-learn` after workflow if desired
- **MAX 5 iterations** per subtask
- **Use /map-feature** if you need maximum quality assurance

## Example

User says: `/map-efficient implement user profile editing feature`

This workflow will:
1. Decompose into subtasks (e.g., API endpoint, database update, frontend form)
2. For each subtask:
   - Actor implements
   - Monitor validates
   - Predictor called only if high risk (e.g., database migration)
   - Apply changes
3. Done! Optionally run `/map-learn` to preserve patterns

**Token savings**: ~40-50% vs /map-feature, while maintaining:
- Essential quality gates (Monitor, conditional Predictor)
- Production readiness
- On-demand learning via `/map-learn`

---

**Why /map-efficient is RECOMMENDED:**

✅ **Maximum token savings** (40-50% vs /map-feature)
✅ **Production-ready** (essential quality gates maintained)
✅ **Learning on-demand** (run /map-learn only when needed)
✅ **Best balance** of speed and quality

Begin now with efficient workflow.
