---
name: map-workflows-guide
description: Comprehensive guide for choosing the right MAP workflow based on task type and requirements
version: 1.0
---

# MAP Workflows Guide

This skill helps you choose the optimal MAP workflow for your development tasks. MAP Framework provides 5 specialized workflows, each optimized for different scenarios with varying token costs, learning capabilities, and quality gates.

## Quick Decision Tree

Answer these 5 questions to find your workflow:

```
1. Is this throwaway code or a quick experiment?
   YES  → Use /map-fast (40-50% tokens, no learning)
   NO   → Continue to question 2

2. Are you debugging/fixing a specific bug or test failure?
   YES  → Use /map-debug (70-80% tokens, focused analysis)
   NO   → Continue to question 3

3. Are you refactoring existing code or restructuring modules?
   YES  → Use /map-refactor (70-80% tokens, dependency analysis)
   NO   → Continue to question 4

4. Is this critical infrastructure or security-sensitive code?
   YES  → Use /map-feature (100% tokens, maximum validation)
   NO   → Continue to question 5

5. Is this a production feature you'll maintain long-term?
   YES  → Use /map-efficient (60-70% tokens, batched learning) ← RECOMMENDED
   NO   → Re-evaluate based on specific constraints
```

---

## Workflow Comparison Matrix

| Aspect | `/map-fast` | `/map-efficient` | `/map-feature` | `/map-debug` | `/map-refactor` |
|--------|-----------|-----------------|----------------|-------------|-----------------|
| **Token Cost** | 40-50% | **60-70%** | 100% (baseline) | 70-80% | 70-80% |
| **Learning** | ❌ None | ✅ Batched | ✅ Per-subtask | ✅ Per-subtask | ✅ Per-subtask |
| **Quality Gates** | Basic | Essential | All 8 agents | Focused | Focused |
| **Impact Analysis** | ❌ Skipped | ⚠️ Conditional | ✅ Always | ✅ Yes | ✅ Yes |
| **Best For** | Throwaway | **Production** | Critical | Bugs | Refactoring |
| **Recommendation** | Never use | **DEFAULT** | High-risk | Issues | Changes |

---

## Detailed Workflow Descriptions

### 1. /map-fast — Quick Prototypes ⚡

**Use this when:**
- Creating throwaway code you'll discard after testing
- Running experiments to validate ideas
- Spike solutions to explore feasibility
- Non-critical helper scripts or utilities

**What you get:**
- ✅ Full implementation (Actor generates code)
- ✅ Basic validation (Monitor checks correctness)
- ✅ Quality check (Evaluator scores solution)
- ❌ NO impact analysis (Predictor skipped entirely)
- ❌ NO learning (Reflector/Curator skipped)

**Trade-offs:**
- Saves 50-60% tokens vs /map-feature
- Playbook never improves (no patterns stored)
- Cipher knowledge never accumulates
- Minimal quality gates (only basic checks)
- Cannot reuse learned patterns in future tasks

**Example tasks:**
- "Quick prototype for authentication approach"
- "Spike solution to test performance impact"
- "Throwaway script to explore API design"

**Command syntax:**
```bash
/map-fast [task description]
```

**When to AVOID:**
- ❌ Never for production code
- ❌ Never for code you'll refactor later
- ❌ Never for security-critical logic
- ❌ Never to save tokens on important work

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
- ✅ Quality gates (Evaluator approval)
- ✅ Impact analysis (Predictor runs conditionally)
- ✅ **Batched learning** (Reflector/Curator run once at end)

**Optimization strategy:**
- **Conditional Predictor:** Runs only if risk detected (security, breaking changes)
- **Batched Learning:** Reflector/Curator run ONCE after all subtasks complete
- **Result:** 35-40% token savings vs /map-feature while preserving learning
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
- Playbook growth from all tasks

**See also:** [resources/map-efficient-deep-dive.md](resources/map-efficient-deep-dive.md)

---

### 3. /map-feature — Critical Features 🏗️

**Use this when:**
- Implementing security-critical functionality
- First-time complex features requiring maximum validation
- High-risk changes affecting many systems
- You need complete assurance before production
- Learning is critical for future similar tasks

**What you get:**
- ✅ Full implementation (Actor)
- ✅ Comprehensive validation (Monitor with loops)
- ✅ **Per-subtask impact analysis** (Predictor always runs)
- ✅ Quality gates (Evaluator always runs)
- ✅ **Per-subtask learning** (Reflector/Curator after each subtask)

**Trade-offs:**
- 100% token cost (no optimization applied)
- Slower execution (maximum agent cycles)
- Maximum quality assurance
- Most comprehensive learning (frequent reflections)
- Best for high-stakes implementations

**When this is required:**
- Authentication/authorization systems
- Payment processing
- Database schema changes
- Multi-service coordination
- Code that affects many dependencies

**Example tasks:**
- "Implement secure JWT authentication system"
- "Refactor database schema for multi-tenancy"
- "Add payment processing via Stripe"
- "Build real-time notification system"

**Command syntax:**
```bash
/map-feature [task description]
```

**Agent pipeline:**
```
TaskDecomposer → Actor → Monitor → Predictor →
Evaluator → Reflector → Curator → [Next subtask]
```

**See also:** [resources/map-feature-deep-dive.md](resources/map-feature-deep-dive.md)

---

### 4. /map-debug — Bug Fixes 🐛

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
- ✅ Learning (Reflector/Curator)

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

### 5. /map-refactor — Code Restructuring 🔧

**Use this when:**
- Refactoring existing code for readability
- Improving code structure or design
- Cleaning up technical debt
- Renaming/reorganizing modules
- Extracting common logic

**What you get:**
- ✅ Implementation (Actor)
- ✅ Validation (Monitor)
- ✅ **Dependency impact analysis** (Predictor focused on dependencies)
- ✅ Quality gates (Evaluator)
- ✅ Learning (Reflector/Curator)

**Specialized for:**
- Breaking change detection
- Dependency tracking
- Migration planning
- Careful phased refactoring

**Example tasks:**
- "Refactor auth service to separate concerns"
- "Extract common validation logic into shared module"
- "Rename User model to Account throughout codebase"
- "Convert callback-based API to promise-based"

**Command syntax:**
```bash
/map-refactor [refactoring description]
```

**Impact analysis includes:**
- Which files/modules depend on changed code
- Potential breaking changes
- Migration strategy
- Scope of refactoring

**See also:** [resources/map-refactor-deep-dive.md](resources/map-refactor-deep-dive.md)

---

## Understanding MAP Agents

MAP workflows orchestrate **8 specialized agents**, each with specific responsibilities:

### Execution & Validation Agents

**TaskDecomposer** — Breaks goal into subtasks
- Analyzes requirements
- Creates atomic, implementable subtasks
- Defines acceptance criteria for each
- Estimates complexity

**Actor** — Writes code and implements
- Generates implementation
- Makes file changes
- Uses playbook patterns
- Queries cipher for relevant knowledge

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

### Analysis Agents

**Predictor** — Impact analysis
- Analyzes dependencies
- Predicts side effects
- Identifies risks and breaking changes
- **Conditional in /map-efficient** (runs if risk detected)
- **Always in /map-feature** (runs per subtask)

### Learning Agents

**Reflector** — Pattern extraction
- Analyzes what worked and failed
- Extracts reusable patterns
- Searches cipher for existing knowledge
- Prevents duplicate pattern storage
- **Batched in /map-efficient** (runs once at end)
- **Per-subtask in /map-feature** (extracts frequently)

**Curator** — Knowledge management
- Updates playbook with new patterns
- Deduplicates against cipher
- Syncs high-quality patterns (helpful_count ≥ 5)
- Maintains pattern metadata
- **Batched in /map-efficient** (runs once at end)

### Optional Agent

**Documentation-Reviewer** — Documentation validation
- Reviews completeness
- Checks consistency
- Validates examples
- Verifies external dependency docs current

---

## Decision Flowchart

```
START: What type of development task?
│
├─────────────────────────────────────┐
│ Throwaway prototype or experiment?  │
│ (Will discard after testing)        │
├─────────────────────────────────────┘
│ YES → /map-fast (40-50% tokens, no learning)
│       ⚠️  WARNING: Never use for production
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
├─────────────────────────────────────┐
│ Refactoring existing code?          │
│ (Improving structure, renaming)     │
├─────────────────────────────────────┘
│ YES → /map-refactor (70-80% tokens, dependency tracking)
│
│ NO ↓
│
├─────────────────────────────────────┐
│ Critical/high-risk feature?         │
│ (Auth, payments, security, database)│
├─────────────────────────────────────┘
│ YES → /map-feature (100% tokens, full validation)
│
│ NO ↓
│
└─────────────────────────────────────┐
  Standard production feature?        │
  (/map-efficient recommended) ←──────┘
  YES → /map-efficient (60-70% tokens, RECOMMENDED)
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

A: Only for code you'll throw away:
- Experiments to test feasibility
- Quick prototypes for discussion
- One-off scripts for temporary use

Never use for:
- Production code (will cause problems later)
- Features that will be maintained
- Security or critical infrastructure

**Q: What's the practical difference between /map-feature and /map-efficient?**

A: Token cost vs learning frequency:

**/map-feature:** Maximum assurance
- Predictor runs after EVERY subtask (100% analysis)
- Reflector/Curator run after EVERY subtask
- Cost: 100% tokens, slowest execution
- Best for: First implementations, critical systems

**/map-efficient:** Smart optimization
- Predictor runs ONLY when risk detected (conditional)
- Reflector/Curator run ONCE at end (batched)
- Cost: 60-70% tokens, faster execution
- Same learning: Patterns still captured at end
- Best for: Standard features, most development

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

**Q: What's the difference between playbook and cipher?**

A: Dual memory system:

**Playbook** (`.claude/playbook.db`)
- Project-specific patterns and code snippets
- Structured bullets with examples
- Full-text search + semantic embeddings
- Updated by Curator agent after each workflow

**Cipher** (Cross-project MCP tool)
- Knowledge shared across all projects
- High-quality patterns (helpful_count ≥ 5)
- Prevents duplicate patterns across projects
- Used by Reflector/Curator for deduplication

---

## Resources & Deep Dives

For detailed information on each workflow:

- **[map-fast Deep Dive](resources/map-fast-deep-dive.md)** — Token breakdown, skip conditions, risks
- **[map-efficient Deep Dive](resources/map-efficient-deep-dive.md)** — Optimization strategy, Predictor conditions, batching
- **[map-feature Deep Dive](resources/map-feature-deep-dive.md)** — Full pipeline, cost analysis, when required
- **[map-debug Deep Dive](resources/map-debug-deep-dive.md)** — Debugging strategies, error analysis, best practices
- **[map-refactor Deep Dive](resources/map-refactor-deep-dive.md)** — Impact analysis, breaking changes, migration planning

Agent & system details:

- **[Agent Architecture](resources/agent-architecture.md)** — How agents orchestrate and coordinate
- **[Playbook System](resources/playbook-system.md)** — Pattern storage and retrieval
- **[Cipher Integration](resources/cipher-integration.md)** — Cross-project knowledge sharing

---

## Real-World Examples

### Example 1: Choosing between /map-efficient and /map-feature

**Task:** "Add OAuth2 authentication"

**Analysis:**
- Affects security ✓ (high-risk indicator)
- Affects multiple modules ✓ (breaking changes possible)
- First implementation of OAuth2 ✓ (high complexity)

**Decision:** `/map-feature` (worth 100% token cost for critical feature)

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
MAP: 🎯 Suggests /map-feature instead
```

**Direct command:**
```
User: "/map-efficient add pagination to blog API"
MAP: 📚 Loads this skill for context
```

---

## Tips for Effective Workflow Selection

1. **Default to /map-efficient** — It's the recommended choice for 80% of tasks
2. **Use /map-fast sparingly** — Only for truly throwaway code, never production
3. **Reserve /map-feature for critical paths** — Don't overuse, save for auth/payments/security
4. **Monitor playbook growth** — Run `mapify playbook stats` to see learning improving
5. **Trust the optimization** — /map-efficient preserves quality while cutting token usage
6. **Review deep dives** — When in doubt, check the appropriate deep-dive resource
7. **Combine with playbook** — Leverage stored patterns from previous tasks

---

## Next Steps

1. **First time using MAP?** Start with `/map-efficient`
2. **Have a critical feature?** See [map-feature-deep-dive.md](resources/map-feature-deep-dive.md)
3. **Debugging an issue?** See [map-debug-deep-dive.md](resources/map-debug-deep-dive.md)
4. **Understanding agents?** See [Agent Architecture](resources/agent-architecture.md)
5. **Learning about playbook?** See [Playbook System](resources/playbook-system.md)

---

**Skill Version:** 1.0
**Last Updated:** 2025-11-03
**Recommended Reading Time:** 5-10 minutes
**Deep Dive Reading Time:** 15-20 minutes per resource