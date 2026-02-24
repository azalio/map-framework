---
name: map-workflows-guide
description: >-
  Guide for choosing the right MAP workflow based on task type, risk level,
  and token budget. Use when user asks "which workflow should I use",
  "difference between map-fast and map-efficient", "when to use map-debug",
  or compares MAP workflows. Do NOT use for actual workflow execution —
  use /map-efficient, /map-fast, etc. instead. Do NOT use for CLI errors
  (use map-cli-reference).
version: 1.0
metadata:
  author: azalio
  version: 3.1.0
---

# MAP Workflows Guide

This skill helps you choose the optimal MAP workflow for your development tasks. MAP Framework provides **10 workflow commands**: 4 primary workflows (`/map-fast`, `/map-efficient`, `/map-debug`, `/map-debate`) and 6 supporting commands (`/map-review`, `/map-check`, `/map-plan`, `/map-release`, `/map-resume`, `/map-learn`). Each is optimized for different scenarios with varying token costs, learning capabilities, and quality gates. Two additional workflows (`/map-feature`, `/map-refactor`) are planned but not yet implemented.

## Quick Decision Tree

Answer these 5 questions to find your workflow:

```
1. Is this a small, low-risk change with clear acceptance criteria?
   YES  → Use /map-fast (40-50% tokens, no learning)
   NO   → Continue to question 2

2. Are you debugging/fixing a specific bug or test failure?
   YES  → Use /map-debug (70-80% tokens, focused analysis)
   NO   → Continue to question 3

3. Do stakeholders need documented reasoning and trade-off analysis?
   YES  → Use /map-debate (3x cost, Opus arbiter, explicit reasoning)
   NO   → Continue to question 4

4. Is this critical infrastructure or security-sensitive code?
   YES  → Use /map-efficient (60-70% tokens, recommended default)
   NO   → Continue to question 5

5. Is this a change you'll maintain long-term or that has non-trivial impact?
   YES  → Use /map-efficient (60-70% tokens, batched learning) ← RECOMMENDED
   NO   → If still low-risk and localized, /map-fast may be acceptable
```

---

## Workflow Comparison Matrix

| Aspect | `/map-fast` | `/map-efficient` | `/map-debug` | `/map-debate` |
|--------|-----------|-----------------|-------------|--------------|
| **Token Cost** | 40-50% | **60-70%** | 70-80% | ~3x baseline |
| **Learning** | ❌ None | ✅ Via /map-learn | ✅ Per-subtask | ✅ Via /map-learn |
| **Quality Gates** | Basic | Essential | Focused | Multi-variant |
| **Impact Analysis** | ❌ Skipped | ⚠️ Conditional | ✅ Yes | ⚠️ Conditional |
| **Multi-Variant** | ❌ Never | ⚠️ Optional (--self-moa) | ❌ Never | ✅ Always (3 variants) |
| **Synthesis Model** | N/A | Sonnet | N/A | **Opus** |
| **Best For** | Low-risk | **Production** | Bugs | Reasoning transparency |
| **Recommendation** | Use sparingly | **DEFAULT** | Issues | Complex decisions |

> **Note:** `/map-feature` and `/map-refactor` are **planned but not yet implemented**.
> Use `/map-efficient` for critical features and refactoring tasks.
> See [Planned Workflows](#planned-workflows) below for details.

---

## Detailed Workflow Descriptions

### 1. /map-fast — Low-Risk Changes ⚡

**Use this when:**
- Small, localized changes with minimal blast radius
- Minor fixes and tweaks where speed matters
- Low-risk maintenance work

**What you get:**
- ✅ Full implementation (Actor generates code)
- ✅ Basic validation (Monitor checks correctness)
- ❌ NO quality scoring (Evaluator skipped)
- ❌ NO impact analysis (Predictor skipped entirely)
- ❌ NO learning (Reflector skipped)

**Trade-offs:**
- Saves 50-60% tokens vs full pipeline (every agent per subtask)
- Knowledge never accumulates
- Minimal quality gates (only basic checks)

**Example tasks:**
- "Fix a small validation edge case"
- "Update error message wording"
- "Add a small CLI option with tests"

**Command syntax:**
```bash
/map-fast [task description]
```

**When to AVOID:**
- ❌ Security-critical logic
- ❌ Wide refactors or multi-module changes
- ❌ High uncertainty / unclear requirements

**See also:** [resources/map-fast-deep-dive.md](resources/map-fast-deep-dive.md)

---

### 2. /map-efficient — Production Features (RECOMMENDED) 🎯

**Use this when:**
- Building production features (moderate complexity)
- Most of your development work
- You want full learning but need token efficiency
- Standard feature implementation with familiar patterns

**What you get:**
- ✅ Full implementation (Actor)
- ✅ Comprehensive validation (Monitor with feedback loops)
- ✅ Impact analysis (Predictor runs conditionally)
- ✅ Tests gate + Linter gate per subtask
- ✅ Final-Verifier (adversarial verification at end)
- ✅ **Learning via /map-learn** (Reflector, optional after workflow)

**Optimization strategy:**
- **Conditional Predictor:** Runs only if risk detected (security, breaking changes)
- **Batched Learning:** Reflector runs ONCE after all subtasks complete
- **Result:** 35-40% token savings vs full pipeline while preserving learning
- **Same quality gates:** Monitor still validates each subtask

**When Predictor runs:**
- Modifies authentication/security code
- Introduces breaking changes
- High complexity detected
- Multiple files affected

**Example tasks:**
- "Implement user registration with email validation"
- "Add pagination to blog posts API"
- "Create dashboard analytics component"
- "Build shopping cart feature"

**Command syntax:**
```bash
/map-efficient [task description]
```

**Quality guarantee:**
Despite token optimization, preserves:
- Per-subtask validation (Monitor always checks)
- Complete implementation feedback loops
- Full learning (batched, not skipped)

**See also:** [resources/map-efficient-deep-dive.md](resources/map-efficient-deep-dive.md)

---

### 3. /map-debug — Bug Fixes 🐛

**Use this when:**
- Fixing specific bugs or defects
- Resolving test failures
- Investigating runtime errors
- Performing root cause analysis
- Diagnosing unexpected behavior

**What you get:**
- ✅ Focused implementation (Actor targets root cause)
- ✅ Validation (Monitor verifies fix)
- ✅ Root cause analysis
- ✅ Impact assessment (Predictor)
- ✅ Learning (Reflector)

**Specialized features:**
- Error log analysis
- Stack trace interpretation
- Test failure diagnosis
- Regression prevention

**Example tasks:**
- "Fix failing tests in auth.test.ts"
- "Debug TypeError in user service"
- "Resolve race condition in async code"
- "Fix memory leak in notification handler"

**Command syntax:**
```bash
/map-debug [issue description or error message]
```

**Include in request:**
- Error message/stack trace
- When it occurs (specific scenario)
- What the expected behavior is
- Relevant log files if available

**See also:** [resources/map-debug-deep-dive.md](resources/map-debug-deep-dive.md)

---

### Planned Workflows

The following workflows are **planned but not yet implemented**. Use `/map-efficient` as a substitute for both.

#### /map-feature — Critical Features (PLANNED)

Intended for security-critical and high-risk features requiring maximum validation (100% token cost, per-subtask learning, Predictor always runs). **Not yet implemented.** Use `/map-efficient` instead — it provides the same agent pipeline with conditional Predictor and batched learning.

**Design reference:** [resources/map-feature-deep-dive.md](resources/map-feature-deep-dive.md)

#### /map-refactor — Code Restructuring (PLANNED)

Intended for refactoring with dependency-focused impact analysis and breaking change detection. **Not yet implemented.** Use `/map-efficient` instead — describe the refactoring intent in the task description for appropriate Predictor analysis.

**Design reference:** [resources/map-refactor-deep-dive.md](resources/map-refactor-deep-dive.md)

---

## Understanding MAP Agents

MAP workflows orchestrate **12 specialized agents**, each with specific responsibilities:

### Execution & Validation Agents

**TaskDecomposer** — Breaks goal into subtasks
- Analyzes requirements
- Creates atomic, implementable subtasks
- Defines acceptance criteria for each
- Estimates complexity

**Actor** — Writes code and implements
- Generates implementation
- Makes file changes
- Uses existing patterns from previous workflows

**Monitor** — Validates correctness
- Checks implementation against criteria
- Runs tests to verify
- Identifies issues
- Feedback loop: Returns to Actor if invalid

**Evaluator** — Quality gates
- Scores implementation quality (0-10)
- Checks completeness
- Approves/rejects solution
- Feedback loop: Returns to Actor if score < threshold
- **Only in /map-debug, /map-review** (skipped in /map-efficient, /map-fast, /map-debate)

### Analysis Agents

**Predictor** — Impact analysis
- Analyzes dependencies
- Predicts side effects
- Identifies risks and breaking changes
- **Conditional in /map-efficient** (runs if risk detected)
- **Always in /map-debug** (focused analysis)

### Learning Agents

**Reflector** — Pattern extraction
- Analyzes what worked and failed
- Extracts reusable patterns
- Prevents duplicate pattern extraction
- **Batched in /map-efficient** (runs once at end, via /map-learn)
- **Skipped in /map-fast** (no learning)

### Optional Agent

**Documentation-Reviewer** — Documentation validation
- Reviews completeness
- Checks consistency
- Validates examples
- Verifies external dependency docs current

### Synthesis Agents

**Debate-Arbiter** — Multi-variant cross-evaluation (MAP Debate)
- Cross-evaluates Actor variants with explicit reasoning
- Synthesizes optimal solution from multiple approaches
- Uses Opus model for reasoning transparency
- **Only in /map-debate workflow**

**Synthesizer** — Solution synthesis
- Extracts decisions from multiple variants
- Generates unified code from best elements (Self-MoA)
- Merges insights across Actor outputs
- **Used in /map-efficient with --self-moa flag**

### Discovery & Verification Agents

**Research-Agent** — Codebase discovery
- Heavy codebase reading with compressed output
- Gathers context proactively before Actor implementation
- Prevents context pollution in implementation agents
- **Used in /map-plan, /map-efficient, /map-debug**

**Final-Verifier** — Adversarial verification (Ralph Loop)
- Root cause analysis via adversarial testing
- Terminal verification after all other agents
- Ensures no regressions or overlooked issues
- **Used in /map-check, /map-efficient**

---

## Decision Flowchart

```
START: What type of development task?
│
├─────────────────────────────────────┐
│ Small, low-risk change?             │
│ (Localized, clear acceptance)       │
├─────────────────────────────────────┘
│ YES → /map-fast (40-50% tokens, no learning)
│
│ NO ↓
│
├─────────────────────────────────────┐
│ Debugging/fixing a specific issue?  │
│ (Bug, test failure, error)          │
├─────────────────────────────────────┘
│ YES → /map-debug (70-80% tokens, focused analysis)
│
│ NO ↓
│
└─────────────────────────────────────┐
  Everything else (features,          │
  refactoring, critical code)  ←──────┘
  → /map-efficient (60-70% tokens, RECOMMENDED)
```

---

## Common Questions

**Q: Which workflow should I use by default?**

A: **`/map-efficient`** for 80% of tasks.
- Best balance of quality and token efficiency
- Full learning preserved (just batched)
- Suitable for all production code
- Default recommendation for feature development

**Q: When is /map-fast actually acceptable?**

A: When the change is small and low-risk:
- Localized fixes with minimal blast radius
- Small UI/text tweaks
- Minor maintenance changes

Avoid /map-fast for:
- Security or critical infrastructure
- Broad refactors or multi-module changes
- High uncertainty requirements

**Q: What about /map-feature and /map-refactor?**

A: These are **planned but not yet implemented**. Use `/map-efficient` for all feature development and refactoring tasks. `/map-efficient` provides the full agent pipeline (Actor, Monitor, conditional Predictor, Tests/Linter gates, Final-Verifier) with optional learning via `/map-learn`. Describe the risk level and refactoring intent in your task description for appropriate Predictor analysis.

**Q: Can I switch workflows mid-task?**

A: No, each workflow is a complete pipeline. If you started with wrong workflow:
1. Complete current workflow
2. Start new workflow with correct one
3. Re-implement if needed

**Q: How do I know if Predictor actually ran in /map-efficient?**

A: Check agent output for indicators:
```
✅ Predictor: [Risk detected - Full analysis]
⏭️  Predictor: [Skipped - Low risk item]
```

Predictor runs if:
- Subtask touches authentication/security code
- Breaking changes detected
- High complexity estimated
- Multiple files affected

---

## Resources & Deep Dives

For detailed information on each workflow:

- **[map-fast Deep Dive](resources/map-fast-deep-dive.md)** — Token breakdown, skip conditions, risks
- **[map-efficient Deep Dive](resources/map-efficient-deep-dive.md)** — Optimization strategy, Predictor conditions, batching
- **[map-debug Deep Dive](resources/map-debug-deep-dive.md)** — Debugging strategies, error analysis, best practices
- **[map-feature Deep Dive](resources/map-feature-deep-dive.md)** — Design reference (PLANNED, not yet implemented)
- **[map-refactor Deep Dive](resources/map-refactor-deep-dive.md)** — Design reference (PLANNED, not yet implemented)

Agent & system details:

- **[Agent Architecture](resources/agent-architecture.md)** — How agents orchestrate and coordinate

---

## Real-World Examples

### Example 1: Choosing /map-efficient for a critical feature

**Task:** "Add OAuth2 authentication"

**Analysis:**
- Affects security (high-risk indicator)
- Affects multiple modules (breaking changes possible)
- First implementation of OAuth2 (high complexity)

**Decision:** `/map-efficient` — describe the security-sensitive nature in the task description. Predictor will trigger conditionally on security-related subtasks.

### Example 2: Choosing /map-debug

**Task:** "Tests failing in checkout flow"

**Analysis:**
- Specific issue (test failures) ✓
- Not new feature (debugging)
- Needs root cause analysis ✓

**Decision:** `/map-debug` (focused on diagnosing failures)

### Example 3: Choosing /map-efficient

**Task:** "Add user profile page"

**Analysis:**
- Standard production feature ✓
- Moderate complexity (not first-time) ✓
- No security implications
- No breaking changes

**Decision:** `/map-efficient` (recommended default)

---

## Integration with Auto-Activation

This skill integrates with MAP's auto-activation system to suggest workflows:

**Natural language request:**
```
User: "Implement user registration"
MAP: 🎯 Suggests /map-efficient
```

**Questions from MAP:**
```
MAP: "Is this for production?"
User: "Yes, but critical feature"
MAP: 🎯 Suggests /map-efficient with --self-moa instead
```

**Direct command:**
```
User: "/map-efficient add pagination to blog API"
MAP: 📚 Loads this skill for context
```

---

## Tips for Effective Workflow Selection

1. **Default to /map-efficient** — It's the recommended choice for 80% of tasks
2. **Use /map-fast sparingly** — Only for small, low-risk changes with clear scope
3. **Use /map-efficient for critical paths** — Describe risk context in the task description for appropriate Predictor triggers
4. **Trust the optimization** — /map-efficient preserves quality while cutting token usage
5. **Review deep dives** — When in doubt, check the appropriate deep-dive resource

---

## Next Steps

1. **First time using MAP?** Start with `/map-efficient`
2. **Have a critical feature?** Use `/map-efficient` with risk context in the task description
3. **Debugging an issue?** See [map-debug-deep-dive.md](resources/map-debug-deep-dive.md)
4. **Understanding agents?** See [Agent Architecture](resources/agent-architecture.md)
---

## Examples

### Example 1: Choosing a workflow for a new feature

**User says:** "I need to add JWT authentication to the API"

**Actions:**
1. Assess risk level — security-sensitive (high-risk indicator)
2. Check if first implementation — yes, OAuth/JWT is new
3. Multiple modules affected — auth middleware, user service, token storage

**Result:** Recommend `/map-efficient` — describe the security context in the task. Predictor will trigger on security-sensitive subtasks. Batched learning captures patterns at the end.

### Example 2: Quick fix with clear scope

**User says:** "Update the error message in the login form"

**Actions:**
1. Assess risk — low, localized text change
2. Check blast radius — single file, no dependencies
3. No security implications

**Result:** Recommend `/map-fast` — small, low-risk change with clear acceptance criteria. No learning needed.

### Example 3: Debugging a test failure

**User says:** "Tests in auth.test.ts are failing after the last merge"

**Actions:**
1. Identify task type — debugging/fixing specific issue
2. Need root cause analysis — yes, regression after merge
3. Not a new feature or refactor

**Result:** Recommend `/map-debug` — focused on diagnosing failures with root cause analysis and regression prevention.

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Wrong workflow chosen mid-task | Cannot switch workflows during execution | Complete current workflow, then restart with correct one |
| Predictor never runs in /map-efficient | Subtasks assessed as low-risk | Expected behavior; Predictor is conditional. Use /map-debug for guaranteed analysis |
| No patterns stored after /map-fast | /map-fast skips learning agents | By design — use /map-efficient + /map-learn for pattern accumulation |
| Skill suggests wrong workflow | Description trigger mismatch | Check skill-rules.json triggers; refine query wording |

---

**Skill Version:** 1.0
**Last Updated:** 2025-11-03
**Recommended Reading Time:** 5-10 minutes
**Deep Dive Reading Time:** 15-20 minutes per resource
