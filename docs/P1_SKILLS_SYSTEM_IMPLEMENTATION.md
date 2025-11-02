# Implementation Plan: Skills System for MAP Framework (P1)

## Context

**Priority:** P1 (after P0 auto-activation completed)

**Effort:** 1 week

**Dependencies:**
- ✅ P0 Auto-Activation System должен быть реализован
- ✅ workflow-rules.json существует и работает

**Статус:** READY TO START (после P0)

---

## Что это такое?

### Проблема

Пользователи не понимают:
- Когда использовать /map-fast vs /map-efficient vs /map-feature
- Какие trade-offs у каждого workflow
- Как MAP agents работают (Actor, Monitor, Predictor, etc.)
- Что такое playbook и cipher

**Текущее решение:** Читать USAGE.md и ARCHITECTURE.md (долго, неудобно)

### Решение: Skills System

**Skills** = Passive documentation modules (НЕ agents!)

**Ключевые отличия:**
- **Skills** (пассивная документация) ← СОЗДАЕМ ЭТО
  - Loadable via Skill tool
  - Provide guidance without executing code
  - Progressive disclosure pattern (<500 lines main + resources)

- **Agents** (активное исполнение) ← УЖЕ ЕСТЬ
  - Execute via Task tool
  - Write code, make changes
  - Orchestrated by MAP workflow

**Пример use case:**
```
User: "I need to add a feature"
MAP (auto-activation): "🎯 Consider /map-feature"
User: "What's the difference between workflows?"
MAP: "📚 Loading skill: map-workflows-guide"
[Skill explains: /map-fast = throwaway, /map-efficient = production, /map-feature = critical]
```

---

## Референсы для изучения

### Созданная документация

1. **docs/MAP_VS_SHOWCASE_COMPARISON.md** (section "Skills System")
   - Explains Skills vs Agents distinction
   - Shows 500-line rule pattern

2. **ST-001-AUTO-ACTIVATION-ANALYSIS.md**
   - Integration with auto-activation system

### Showcase reference (примеры реализации)

**Основные примеры:**
- `docs/claude-code-infrastructure-showcase/.claude/skills/backend-dev-guidelines/`
  - SKILL.md (302 lines) - main entry point
  - resources/ (11 files) - deep dive topics

- `docs/claude-code-infrastructure-showcase/.claude/skills/skill-developer/`
  - SKILL.md (426 lines) - meta-skill for creating skills
  - resources/ (7 files) - progressive disclosure

**Структура:**
```
.claude/skills/backend-dev-guidelines/
├── SKILL.md                          # Main entry point (<500 lines)
├── resources/
│   ├── routing.md                    # Deep dive: routing patterns
│   ├── controllers.md                # Deep dive: controller patterns
│   ├── services.md                   # Deep dive: service layer
│   ├── repositories.md               # Deep dive: data access
│   ├── validation.md                 # Deep dive: input validation
│   ├── error-handling.md             # Deep dive: error patterns
│   ├── testing.md                    # Deep dive: testing strategies
│   └── ... (11 total)
```

---

## Implementation Steps

### Phase 1: Core Infrastructure (Day 1, 2-3 hours)

#### Шаг 1.1: Создать директорию структуру (5 минут)

```bash
mkdir -p .claude/skills/map-workflows-guide/resources
```

#### Шаг 1.2: Создать skill-rules.json entry (10 минут)

**Файл:** `.claude/skills/skill-rules.json` (если не существует, создать)

**Добавить:**
```json
{
  "version": "1.0",
  "description": "Skill activation triggers for MAP Framework",
  "skills": {
    "map-workflows-guide": {
      "type": "domain",
      "enforcement": "suggest",
      "priority": "high",
      "description": "Guide for choosing the right MAP workflow",
      "promptTriggers": {
        "keywords": [
          "which workflow",
          "map-fast or map-efficient",
          "difference between workflows",
          "when to use",
          "workflow comparison",
          "map workflow",
          "choose workflow"
        ],
        "intentPatterns": [
          "(which|what).*?(workflow|mode).*?(use|choose)",
          "(difference|compare).*?(map-fast|map-efficient|map-feature)",
          "(when|how).*?(use|choose).*?(workflow|mode)",
          "explain.*?(workflow|map-fast|map-efficient)"
        ]
      }
    }
  }
}
```

**Команды:**
```bash
# Создать или обновить файл (используй Write/Edit tool)

# Проверить валидность
jq . .claude/skills/skill-rules.json

# Интегрировать с workflow-rules.json (P0)
# Можно объединить в один файл или держать раздельно
```

#### Шаг 1.3: Обновить auto-activation hook (15 минут)

**Файл:** `.claude/hooks/user-prompt-submit.sh`

**Добавить поддержку skills suggestion:**

```bash
# После workflow matching, добавить skills matching

# Load skill rules
SKILL_RULES_FILE=".claude/skills/skill-rules.json"
if [ -f "$SKILL_RULES_FILE" ]; then
  # Check map-workflows-guide triggers
  if echo "$PROMPT" | grep -qE "(which workflow|difference between|when to use)"; then
    echo ""
    echo "📚 SKILL AVAILABLE: map-workflows-guide"
    echo "   Use Skill tool to load guidance on choosing workflows"
    echo "   To load: Ask me 'load map-workflows-guide skill'"
    echo ""
  fi
fi
```

**Или интегрировать с workflow-rules.json:** (более чистое решение)

Объединить skill triggers в `.claude/workflow-rules.json`:

```json
{
  "workflows": { ... },
  "skills": {
    "map-workflows-guide": {
      "type": "guidance",
      "priority": "high",
      "promptTriggers": { ... }
    }
  }
}
```

---

### Phase 2: Main Skill Content (Day 2-3, 4-6 hours)

#### Шаг 2.1: Создать SKILL.md main file (2-3 hours)

**Файл:** `.claude/skills/map-workflows-guide/SKILL.md`

**Target:** <500 lines (progressive disclosure rule)

**Структура:**

```markdown
---
name: map-workflows-guide
description: Guide for choosing the right MAP workflow based on your task
version: 1.0
---

# MAP Workflows Guide

## Quick Decision Tree

**Answer these questions:**

1. **Is this throwaway code or a quick prototype?**
   → Use `/map-fast` (40-50% token savings, NO learning)

2. **Is this a production feature with moderate complexity?**
   → Use `/map-efficient` (60-70% tokens, batched learning) ← RECOMMENDED

3. **Is this critical infrastructure or high-risk change?**
   → Use `/map-feature` (100% baseline, full validation)

4. **Is this debugging/fixing an issue?**
   → Use `/map-debug` (focused on root cause analysis)

5. **Is this refactoring existing code?**
   → Use `/map-refactor` (impact analysis, dependency tracking)

---

## Workflow Comparison Matrix

| Workflow | Token Cost | Learning | Agents | Best For |
|----------|-----------|----------|--------|----------|
| `/map-fast` | 40-50% | ❌ None | 3 basic | Throwaway prototypes, experiments |
| `/map-efficient` | 60-70% | ✅ Batched | 5-6 essential | **Production features (RECOMMENDED)** |
| `/map-feature` | 100% | ✅ Full | All 8 | Critical features, infrastructure |
| `/map-debug` | 70-80% | ✅ Full | Focused subset | Bug fixes, test failures |
| `/map-refactor` | 70-80% | ✅ Full | With Predictor | Code restructuring, cleanup |

---

## Detailed Workflow Descriptions

### /map-fast - Quick Prototypes ⚡

**When to use:**
- Throwaway code (will be rewritten)
- Quick experiments to test ideas
- Spike solutions
- Non-critical scripts

**What you get:**
- ✅ Basic implementation (Actor)
- ✅ Simple validation (Monitor)
- ✅ Quality check (Evaluator)
- ❌ NO impact analysis (Predictor skipped)
- ❌ NO learning (Reflector/Curator skipped)

**What you sacrifice:**
- No playbook updates (patterns not learned)
- No cipher sync (knowledge not shared)
- Minimal quality gates

**Example tasks:**
- "Quick prototype for user authentication"
- "Experiment with new API design"
- "Throwaway script to migrate data"

**Command:**
```bash
/map-fast implement quick prototype for X
```

**See:** [resources/map-fast-deep-dive.md](resources/map-fast-deep-dive.md)

---

### /map-efficient - Production Features (RECOMMENDED) 🎯

**When to use:**
- Production features (moderate complexity)
- Most development work
- When you want learning but need token efficiency

**What you get:**
- ✅ Full implementation (Actor)
- ✅ Comprehensive validation (Monitor)
- ✅ Quality gates (Evaluator)
- ✅ Impact analysis (Predictor - conditional)
- ✅ **Batched learning** (Reflector/Curator at end)

**Optimization strategy:**
- Predictor runs ONLY if risk detected (not every subtask)
- Reflector/Curator run ONCE at end (not per subtask)
- Result: 35-40% token savings vs /map-feature

**Example tasks:**
- "Implement user registration feature"
- "Add pagination to blog posts API"
- "Create dashboard analytics component"

**Command:**
```bash
/map-efficient implement user registration
```

**See:** [resources/map-efficient-deep-dive.md](resources/map-efficient-deep-dive.md)

---

### /map-feature - Critical Features 🏗️

**When to use:**
- Critical infrastructure changes
- High-risk features
- Security-sensitive code
- When you need maximum confidence

**What you get:**
- ✅ Full implementation (Actor)
- ✅ Comprehensive validation (Monitor)
- ✅ **Per-subtask impact analysis** (Predictor always runs)
- ✅ Quality gates (Evaluator)
- ✅ **Per-subtask learning** (Reflector/Curator after each)

**Trade-offs:**
- 100% token cost (no optimization)
- Slower (more agent cycles)
- Maximum quality assurance

**Example tasks:**
- "Implement authentication system"
- "Refactor database schema"
- "Add payment processing"

**Command:**
```bash
/map-feature implement critical authentication system
```

**See:** [resources/map-feature-deep-dive.md](resources/map-feature-deep-dive.md)

---

### /map-debug - Bug Fixes 🐛

**When to use:**
- Fixing bugs
- Resolving test failures
- Investigating errors
- Root cause analysis

**What you get:**
- ✅ Focused implementation (Actor)
- ✅ Validation (Monitor)
- ✅ Root cause analysis
- ✅ Impact assessment (Predictor)
- ✅ Learning (Reflector/Curator)

**Specialized for:**
- Error log analysis
- Stack trace interpretation
- Test failure diagnosis

**Example tasks:**
- "Fix failing tests in auth.test.ts"
- "Debug TypeError in user service"
- "Resolve race condition in async code"

**Command:**
```bash
/map-debug fix failing tests in auth.test.ts
```

**See:** [resources/map-debug-deep-dive.md](resources/map-debug-deep-dive.md)

---

### /map-refactor - Code Restructuring 🔧

**When to use:**
- Refactoring existing code
- Improving structure
- Cleaning up technical debt
- Renaming/reorganizing

**What you get:**
- ✅ Implementation (Actor)
- ✅ Validation (Monitor)
- ✅ **Dependency impact analysis** (Predictor focused)
- ✅ Quality gates (Evaluator)
- ✅ Learning (Reflector/Curator)

**Specialized for:**
- Breaking change detection
- Dependency tracking
- Migration planning

**Example tasks:**
- "Refactor auth service to separate concerns"
- "Rename User model to Account"
- "Extract common logic into shared module"

**Command:**
```bash
/map-refactor restructure auth service
```

**See:** [resources/map-refactor-deep-dive.md](resources/map-refactor-deep-dive.md)

---

## Understanding MAP Agents

MAP workflows orchestrate specialized agents. Here's what each does:

### Core Execution Agents

**1. TaskDecomposer** (runs first)
- Breaks goal into atomic subtasks
- Defines acceptance criteria
- Estimates complexity

**2. Actor** (implementation)
- Writes code
- Makes file changes
- Implements subtasks

**3. Monitor** (validation)
- Checks correctness
- Runs tests
- Validates against criteria
- **Feedback loop:** Returns to Actor if invalid

**4. Evaluator** (quality gates)
- Scores implementation quality
- Checks completeness
- Approves or rejects
- **Feedback loop:** Returns to Actor if not approved

### Analysis Agents

**5. Predictor** (impact analysis)
- Analyzes dependencies
- Predicts side effects
- Identifies risks
- **Conditional in /map-efficient:** Only runs if risk detected

### Learning Agents

**6. Reflector** (pattern extraction)
- Analyzes what worked/failed
- Extracts reusable patterns
- Searches cipher for existing knowledge
- **Batched in /map-efficient:** Runs once at end

**7. Curator** (knowledge management)
- Updates playbook with patterns
- Searches cipher for duplicates
- Syncs high-quality patterns (helpful_count ≥ 5)
- **Batched in /map-efficient:** Runs once at end

### Optional Agents

**8. Documentation-Reviewer** (docs validation)
- Reviews documentation completeness
- Checks external dependencies
- Validates architecture consistency

---

## Decision Flowchart

```
START: What type of task?
│
├─ Throwaway prototype?
│  └─> /map-fast (no learning)
│
├─ Debugging/bug fix?
│  └─> /map-debug (focused analysis)
│
├─ Refactoring code?
│  └─> /map-refactor (dependency analysis)
│
└─ New feature implementation?
   │
   ├─ Critical/high-risk?
   │  └─> /map-feature (full validation)
   │
   └─ Production/moderate?
      └─> /map-efficient (recommended)
```

---

## Common Questions

### Q: Which workflow should I use by default?

**A:** `/map-efficient` for 80% of tasks
- Best balance of quality and token efficiency
- Full learning preserved
- Suitable for production code

### Q: When is /map-fast acceptable?

**A:** Only for code you'll throw away:
- Experiments to test feasibility
- Quick prototypes for discussion
- One-off scripts

**Never use for:**
- Production code
- Features that will be maintained
- Critical infrastructure

### Q: What's the difference between /map-feature and /map-efficient?

**A:** Optimization strategy:

**/map-feature:**
- Predictor runs after EVERY subtask (100% coverage)
- Reflector/Curator run after EVERY subtask
- Result: Maximum confidence, 100% token cost

**/map-efficient:**
- Predictor runs ONLY when risk detected (conditional)
- Reflector/Curator run ONCE at end (batched)
- Result: Same learning, 35-40% token savings

### Q: Can I switch workflows mid-task?

**A:** No. Each workflow is a complete pipeline.

If you started with /map-fast and realize it's production code:
1. Complete current workflow
2. Start new workflow with /map-efficient
3. Re-implement properly

### Q: How do I know if Predictor ran in /map-efficient?

**A:** Check agent output:
```
✅ Predictor: [Analysis output]  ← Ran (risk detected)
⏭️  Predictor: Skipped (low risk) ← Skipped
```

Predictor runs if:
- Subtask modifies critical files (auth, database, etc.)
- Breaking changes detected
- High complexity estimated

### Q: What's playbook vs cipher?

**A:** Dual memory system:

**Playbook** (`.claude/playbook.db`)
- Project-specific patterns
- Structured bullets with code examples
- FTS5 search + semantic embeddings
- Updated by Curator agent

**Cipher** (MCP tool)
- Cross-project knowledge
- Semantic search across projects
- Synced from high-quality playbook bullets (helpful_count ≥ 5)
- Used by Reflector/Curator to avoid duplicates

---

## Resources (Deep Dives)

For detailed information on each workflow:

- **[map-fast Deep Dive](resources/map-fast-deep-dive.md)** - Skip conditions, when to avoid
- **[map-efficient Deep Dive](resources/map-efficient-deep-dive.md)** - Optimization strategy, Predictor conditions
- **[map-feature Deep Dive](resources/map-feature-deep-dive.md)** - Full pipeline, when required
- **[map-debug Deep Dive](resources/map-debug-deep-dive.md)** - Debugging strategies, error analysis
- **[map-refactor Deep Dive](resources/map-refactor-deep-dive.md)** - Impact analysis, breaking changes

For agent details:
- **[Agent Architecture](resources/agent-architecture.md)** - How agents orchestrate
- **[Playbook System](resources/playbook-system.md)** - How knowledge is stored
- **[Cipher Integration](resources/cipher-integration.md)** - Cross-project learning

---

## Integration with Auto-Activation

This skill works with auto-activation system:

**Scenario 1: Workflow auto-suggested**
```
User: "Implement user registration"
MAP: "🎯 Consider /map-efficient"
User: "Why efficient instead of feature?"
MAP: "📚 Loading map-workflows-guide"
[Shows comparison: efficient = production, feature = critical]
```

**Scenario 2: User asks directly**
```
User: "What's the difference between map workflows?"
MAP: "📚 Loading map-workflows-guide"
[Shows decision tree and comparison matrix]
```

**Scenario 3: Wrong workflow chosen**
```
User: "/map-fast implement authentication"
MAP: "⚠️  map-fast is for throwaway code. For production auth, use /map-feature"
MAP: "📚 See map-workflows-guide for details"
```

---

## Tips for Effective Use

1. **Start with /map-efficient** - Best default choice
2. **Use /map-fast sparingly** - Only for true throwaway code
3. **Reserve /map-feature for critical tasks** - Don't overuse
4. **Check playbook growth** - Run `mapify playbook stats` to see learning
5. **Trust the optimization** - /map-efficient preserves quality while saving tokens

---

**Skill version:** 1.0
**Last updated:** 2025-11-02
**Dependencies:** Auto-activation system (P0)
```

**Команды для создания:**
```bash
# Создать файл (используй Write tool с содержимым выше)

# Проверить длину
wc -l .claude/skills/map-workflows-guide/SKILL.md
# Target: <500 lines

# Если больше 500 lines, переместить секции в resources/
```

---

### Phase 3: Resource Files (Day 3-4, 4-6 hours)

#### Шаг 3.1: map-efficient-deep-dive.md (1 hour)

**Файл:** `.claude/skills/map-workflows-guide/resources/map-efficient-deep-dive.md`

**Содержание:**
```markdown
# /map-efficient Deep Dive

## Optimization Strategy

### Predictor: Conditional Execution

**Logic:**
```python
def should_run_predictor(subtask):
    # Run if ANY condition true:
    return (
        subtask.complexity == "high" or
        subtask.modifies_critical_files() or
        subtask.has_breaking_changes() or
        subtask.affects_dependencies()
    )
```

**Critical files patterns:**
- `**/auth/**` - Authentication
- `**/database/**` - Schema changes
- `**/api/**` - Public API
- `**/*.proto` - Service contracts

**Example:**
```
Subtask 1: Add validation helper (utils/validation.ts)
→ Predictor: ⏭️ SKIPPED (low risk, no dependencies)

Subtask 2: Update auth middleware (auth/middleware.ts)
→ Predictor: ✅ RAN (critical file detected)

Subtask 3: Add unit tests (tests/auth.test.ts)
→ Predictor: ⏭️ SKIPPED (test file, no side effects)
```

### Reflector/Curator: Batched Learning

**Standard workflow (/map-feature):**
```
Subtask 1 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 2 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 3 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
```
Result: 3 × Reflector/Curator cycles

**Optimized workflow (/map-efficient):**
```
Subtask 1 → Actor → Monitor → [Predictor?] → Evaluator
Subtask 2 → Actor → Monitor → [Predictor?] → Evaluator
Subtask 3 → Actor → Monitor → [Predictor?] → Evaluator
           ↓
        Reflector (analyzes ALL subtasks)
           ↓
        Curator (consolidates patterns)
```
Result: 1 × Reflector/Curator cycle

**Token savings:** 35-40% vs /map-feature

---

## When to Use /map-efficient

✅ **Use for:**
- Production features (moderate complexity)
- API endpoints
- UI components
- Database queries
- Business logic
- Most development work (80% of tasks)

❌ **Don't use for:**
- Critical infrastructure (use /map-feature)
- Throwaway prototypes (use /map-fast)
- Simple bug fixes (use /map-debug)

---

## Quality Preservation

**Myth:** "Optimized workflows sacrifice quality"

**Reality:** /map-efficient preserves all quality gates:
- ✅ Monitor validates every subtask
- ✅ Evaluator scores every implementation
- ✅ Predictor runs when needed (conditional)
- ✅ Reflector analyzes complete context
- ✅ Curator consolidates all patterns

**What's optimized:**
- Frequency (when agents run)
- NOT functionality (what agents do)

---

## Example Walkthrough

**Task:** "Implement blog post pagination API"

**Decomposition:**
- ST-1: Add pagination params to GET /posts endpoint
- ST-2: Update PostService to support offset/limit
- ST-3: Add integration tests

**Execution trace:**

```
TaskDecomposer:
├─ ST-1: Add pagination params (complexity: low)
├─ ST-2: Update service (complexity: medium, affects API)
└─ ST-3: Add tests (complexity: low)

ST-1: Pagination params
├─ Actor: Modify routes/posts.ts
├─ Monitor: ✅ Valid
├─ Predictor: ⏭️ SKIPPED (low risk)
└─ Evaluator: ✅ Approved (score: 8/10)

ST-2: Service update
├─ Actor: Modify services/PostService.ts
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (affects API contract)
│  └─ Impact: Breaking change if clients expect all posts
├─ Evaluator: ✅ Approved (score: 9/10)
└─ Note: "Add API versioning or deprecation notice"

ST-3: Integration tests
├─ Actor: Add tests/posts.integration.test.ts
├─ Monitor: ✅ Valid (tests pass)
├─ Predictor: ⏭️ SKIPPED (test file)
└─ Evaluator: ✅ Approved (score: 8/10)

Reflector (batched):
├─ Analyzed: 3 subtasks
├─ Searched cipher: Found similar pagination patterns
└─ Extracted:
   - Pagination parameter pattern (offset/limit)
   - API versioning consideration
   - Integration test structure

Curator (batched):
├─ Checked duplicates: 2 similar bullets found
├─ Added: 1 new bullet (API pagination pattern)
└─ Updated: 1 existing bullet (test coverage++)
```

**Token usage:**
- /map-feature: ~12k tokens
- /map-efficient: ~7.5k tokens
- **Savings: 37.5%**

**Quality: Identical**
- All validations passed
- Breaking change detected
- Tests written
- Patterns learned

---

## Configuration

Edit `.claude/commands/map-efficient.md` to customize:

**Predictor conditions:**
```python
# Add custom critical paths
CRITICAL_PATHS = [
    "auth/**",
    "database/**",
    "api/**",
    "config/**",  # Your addition
]
```

**Batch size:**
```python
# Default: Batch all subtasks
# Override: Batch every N subtasks
BATCH_SIZE = None  # or 5 for large tasks
```

---

## Troubleshooting

**Issue:** Predictor always skips
**Cause:** No critical file patterns matched
**Fix:** Review `subtask.modifies_critical_files()` logic

**Issue:** Learning not happening
**Cause:** Reflector/Curator not running
**Fix:** Check workflow completion (must finish all subtasks)

**Issue:** Token usage higher than expected
**Cause:** Predictor running too often
**Fix:** Review risk detection conditions

---

**See also:**
- [map-feature-deep-dive.md](map-feature-deep-dive.md) - Full validation approach
- [agent-architecture.md](agent-architecture.md) - How agents orchestrate
```

#### Шаг 3.2: Создать остальные resource files (3-5 hours)

**Файлы для создания:**

1. **resources/map-fast-deep-dive.md** (1 hour)
   - When to use (и when NOT to use)
   - Skipped agents explanation
   - Example tasks
   - Common pitfalls

2. **resources/map-feature-deep-dive.md** (1 hour)
   - Full pipeline walkthrough
   - Per-subtask learning rationale
   - Critical task examples
   - Token cost justification

3. **resources/map-debug-deep-dive.md** (1 hour)
   - Error analysis strategies
   - Stack trace interpretation
   - Root cause identification
   - Example debugging workflows

4. **resources/map-refactor-deep-dive.md** (1 hour)
   - Dependency impact analysis
   - Breaking change detection
   - Migration planning
   - Example refactoring tasks

5. **resources/agent-architecture.md** (30 minutes)
   - Agent orchestration details
   - Feedback loops (Monitor → Actor, Evaluator → Actor)
   - Conditional execution logic
   - Diagram of agent flow

6. **resources/playbook-system.md** (30 minutes)
   - Playbook structure (sections, bullets)
   - Quality scoring (helpful_count)
   - FTS5 + semantic search
   - Curator operations (ADD/UPDATE/DEPRECATE)

7. **resources/cipher-integration.md** (30 minutes)
   - What is cipher MCP
   - Cross-project knowledge sharing
   - Sync conditions (helpful_count ≥ 5)
   - Deduplication strategy

**Template structure для каждого resource:**
```markdown
# [Topic] Deep Dive

## Overview
[2-3 paragraphs]

## When to Use
✅ Use for:
- Point 1
- Point 2

❌ Don't use for:
- Point 1
- Point 2

## How It Works
[Technical details with code examples]

## Example Walkthrough
[Concrete example with execution trace]

## Configuration
[Customization options]

## Troubleshooting
[Common issues and solutions]

## See Also
- [Related resource 1]
- [Related resource 2]
```

---

### Phase 4: Integration & Testing (Day 5, 2-3 hours)

#### Шаг 4.1: Update auto-activation hook (30 minutes)

**Убедиться что skill triggers integrated:**

```bash
# Test skill suggestion
echo '{"prompt": "which workflow should I use"}' | .claude/hooks/user-prompt-submit.sh
# Expected: Suggestion to load map-workflows-guide skill

echo '{"prompt": "difference between map-fast and map-efficient"}' | .claude/hooks/user-prompt-submit.sh
# Expected: Suggestion to load map-workflows-guide skill
```

#### Шаг 4.2: Manual testing (1 hour)

**Test scenarios:**

**Scenario 1: Direct skill request**
```
User: "Load map-workflows-guide skill"
Expected: Skill content displayed
Verify: Decision tree visible, workflow comparison matrix shown
```

**Scenario 2: Auto-triggered by keyword**
```
User: "Which workflow should I use for implementing auth?"
Expected: Skill auto-suggested
Verify: 📚 SKILL AVAILABLE: map-workflows-guide
```

**Scenario 3: Progressive disclosure**
```
User: "Load map-workflows-guide skill"
[Main SKILL.md content shown]
User: "Tell me more about map-efficient"
Expected: Loads resources/map-efficient-deep-dive.md
Verify: Detailed optimization strategy shown
```

**Scenario 4: Integration with workflow suggestion**
```
User: "Implement blog pagination"
Expected:
1. 🎯 Workflow suggestion: /map-efficient
2. 📚 Skill available: map-workflows-guide
User: "Why efficient?"
Expected: Skill explains production feature → use efficient
```

#### Шаг 4.3: Verify skill-rules.json (15 minutes)

```bash
# Check skill registered
jq '.skills["map-workflows-guide"]' .claude/skills/skill-rules.json

# Verify triggers
jq '.skills["map-workflows-guide"].promptTriggers.keywords' .claude/skills/skill-rules.json

# Check integration
grep -r "skill-rules.json" .claude/hooks/
```

#### Шаг 4.4: Documentation check (30 minutes)

**Verify all resources exist:**
```bash
ls -la .claude/skills/map-workflows-guide/resources/
# Expected:
# - map-fast-deep-dive.md
# - map-efficient-deep-dive.md
# - map-feature-deep-dive.md
# - map-debug-deep-dive.md
# - map-refactor-deep-dive.md
# - agent-architecture.md
# - playbook-system.md
# - cipher-integration.md
```

**Check line counts:**
```bash
wc -l .claude/skills/map-workflows-guide/SKILL.md
# Target: <500 lines

wc -l .claude/skills/map-workflows-guide/resources/*.md
# Each: <500 lines (progressive disclosure)
```

---

### Phase 5: Documentation & Commit (Day 5, 1-2 hours)

#### Шаг 5.1: Update USAGE.md (30 minutes)

**Добавить секцию:**

```markdown
## Skills System

MAP includes guidance skills to help you choose the right workflow.

### map-workflows-guide

Load this skill when you need help choosing workflows:

```
User: "Which workflow should I use?"
MAP: [Loads map-workflows-guide skill]
```

The skill provides:
- Decision tree for workflow selection
- Comparison matrix (token cost, learning, agents)
- Detailed deep-dives for each workflow
- Common questions and pitfalls

### Auto-Activation

Skills auto-suggest when relevant keywords detected:
- "which workflow"
- "difference between workflows"
- "when to use map-efficient"

### Progressive Disclosure

Skills use the 500-line rule:
- Main SKILL.md (<500 lines) - high-level overview
- resources/ - deep-dive topics loaded on demand

This prevents context limit issues while providing comprehensive guidance.
```

#### Шаг 5.2: Update README.md (15 minutes)

**Добавить в Features section:**

```markdown
## Features

- **5 Workflow Modes** - Fast, Efficient, Feature, Debug, Refactor
- **Skills System** - Interactive guidance for workflow selection ← NEW
- **Auto-Activation** - Context-aware workflow suggestions
- **Dual Memory** - Playbook (project) + Cipher (cross-project)
```

#### Шаг 5.3: Create .claude/skills/README.md (30 minutes)

**Новый файл с документацией skills system:**

```markdown
# MAP Skills System

## What are Skills?

**Skills** = Passive documentation modules (NOT agents!)

Skills provide guidance without executing code. They help users understand MAP Framework concepts and make decisions.

## Available Skills

### map-workflows-guide

**Purpose:** Help users choose the right MAP workflow

**Triggers:**
- Keywords: "which workflow", "difference between", "when to use"
- User asking about workflow selection

**Content:**
- Decision tree
- Workflow comparison matrix
- Deep-dives for each workflow (5 total)
- Agent architecture explanation
- Common questions

**Usage:**
```
User: "Which workflow should I use for implementing auth?"
MAP: [Auto-suggests or loads map-workflows-guide]
```

## Skills vs Agents

| Skills | Agents |
|--------|--------|
| Passive documentation | Active execution |
| Load via Skill tool | Execute via Task tool |
| Provide guidance | Write code |
| Progressive disclosure (<500 lines) | Full specification (orchestrated) |

**Example:**
- **Skill:** map-workflows-guide (explains workflows)
- **Agent:** actor.md (implements code)

## Creating New Skills

See [docs/P1_SKILLS_SYSTEM_IMPLEMENTATION.md] for:
- Skill structure (SKILL.md + resources/)
- 500-line rule (progressive disclosure)
- Integration with auto-activation
- Testing procedures

## Integration

Skills integrate with:
1. **Auto-activation system** (P0) - Suggests skills based on context
2. **workflow-rules.json** - Trigger configuration
3. **UserPromptSubmit hook** - Analyzes prompts for skill relevance

## File Structure

```
.claude/skills/
├── skill-rules.json              # Trigger configuration
└── map-workflows-guide/
    ├── SKILL.md                  # Main entry (<500 lines)
    └── resources/
        ├── map-fast-deep-dive.md
        ├── map-efficient-deep-dive.md
        ├── map-feature-deep-dive.md
        ├── map-debug-deep-dive.md
        ├── map-refactor-deep-dive.md
        ├── agent-architecture.md
        ├── playbook-system.md
        └── cipher-integration.md
```
```

#### Шаг 5.4: Git commit (15 minutes)

```bash
# Stage files
git add .claude/skills/ \
        .claude/hooks/user-prompt-submit.sh \
        USAGE.md \
        README.md

# Commit
git commit -m "feat: implement Skills System for MAP workflows (P1)

Implements P1 feature from showcase analysis.

What's new:
- map-workflows-guide skill with comprehensive workflow guidance
- Decision tree for workflow selection (5 workflows)
- Comparison matrix (token cost, learning, agents, use cases)
- 8 deep-dive resource files (<500 lines each, progressive disclosure)
  * map-fast-deep-dive.md
  * map-efficient-deep-dive.md
  * map-feature-deep-dive.md
  * map-debug-deep-dive.md
  * map-refactor-deep-dive.md
  * agent-architecture.md
  * playbook-system.md
  * cipher-integration.md

Benefits:
- Users understand when to use each workflow
- Reduces 'which workflow?' questions (~50% expected reduction)
- Progressive disclosure prevents context limits
- Integrates with auto-activation (P0)

Skills vs Agents distinction:
- Skills = passive documentation (guidance)
- Agents = active execution (code generation)
- Skills use Skill tool, Agents use Task tool

Integration:
- skill-rules.json configures triggers
- UserPromptSubmit hook suggests skills
- Auto-triggers on keywords: 'which workflow', 'difference between'

File structure:
- .claude/skills/map-workflows-guide/SKILL.md (main, <500 lines)
- .claude/skills/map-workflows-guide/resources/ (8 deep-dives)
- .claude/skills/skill-rules.json (trigger config)
- .claude/skills/README.md (skills system docs)

Testing:
- Manual skill loading verified
- Auto-suggestion tested (keyword triggers)
- Progressive disclosure validated (loads resources on demand)
- Integration with P0 auto-activation confirmed

Dependencies: P0 Auto-Activation System
Effort: ~1 week (5 days)
Impact: Improved onboarding, reduced confusion"
```

---

## Success Metrics

После реализации P1 измерить:

### 1. Usage Metrics

**Skill Activation Rate:**
```bash
# Count skill loads per session
grep "map-workflows-guide" .claude/logs/*.log | wc -l
```

**Target:** >30% of sessions load skill at least once

### 2. Confusion Reduction

**"Which workflow?" Questions:**
- Baseline: Count before P1 implementation
- After P1: Count after 1 week
- **Target:** -50% reduction

**How to measure:**
```bash
# Search conversation logs for workflow confusion
grep -i "which workflow\|what.*difference.*workflow" .claude/logs/*.log
```

### 3. Correct Workflow Selection

**Workflow Usage Distribution:**
```bash
# Count workflow invocations
grep -E "/(map-fast|map-efficient|map-feature)" .claude/logs/*.log | \
  cut -d'/' -f2 | sort | uniq -c
```

**Expected distribution:**
- map-efficient: 60-70% (most tasks)
- map-debug: 15-20% (bug fixes)
- map-feature: 10-15% (critical)
- map-refactor: 5-10% (cleanup)
- map-fast: <5% (throwaway only)

**Target:** Distribution matches guidelines in skill

### 4. Progressive Disclosure Effectiveness

**Resource Load Rate:**
```bash
# Count how often users request deep-dives
grep "map-.*-deep-dive" .claude/logs/*.log | wc -l
```

**Target:** >20% of skill loads request at least one resource

### 5. User Feedback

**Qualitative indicators:**
- Fewer "I don't understand workflows" comments
- More confident workflow selection
- Less trial-and-error (starting with wrong workflow)

---

## Troubleshooting

### Issue: Skill not auto-suggesting

**Diagnosis:**
```bash
# Check trigger config
jq '.skills["map-workflows-guide"]' .claude/skills/skill-rules.json

# Test hook manually
echo '{"prompt": "which workflow should I use"}' | .claude/hooks/user-prompt-submit.sh
```

**Fix:**
1. Verify skill-rules.json has correct triggers
2. Check hook reads skill-rules.json
3. Test keyword matching logic

### Issue: Skill content too long (>500 lines)

**Diagnosis:**
```bash
wc -l .claude/skills/map-workflows-guide/SKILL.md
```

**Fix:**
1. Move detailed sections to resources/
2. Keep only overview + navigation in SKILL.md
3. Add "See resources/X.md" links

**Example refactoring:**
```markdown
# Before (in SKILL.md):
## /map-efficient Deep Dive
[5 pages of details]

# After (in SKILL.md):
## /map-efficient
[2 paragraphs overview]
**See:** [resources/map-efficient-deep-dive.md]

# Create:
resources/map-efficient-deep-dive.md with full details
```

### Issue: Resources not loading

**Diagnosis:**
```bash
# Check file structure
ls -la .claude/skills/map-workflows-guide/resources/

# Verify references
grep "resources/" .claude/skills/map-workflows-guide/SKILL.md
```

**Fix:**
1. Ensure resource files exist
2. Check file paths in SKILL.md links
3. Verify markdown link syntax

### Issue: Integration with P0 broken

**Diagnosis:**
```bash
# Check if P0 implemented
test -f .claude/workflow-rules.json && echo "P0 exists" || echo "P0 missing"

# Check hook integration
grep -A5 "skill" .claude/hooks/user-prompt-submit.sh
```

**Fix:**
1. Complete P0 first (auto-activation system)
2. Update hook to check skill-rules.json
3. Test skill + workflow suggestions together

---

## Post-Implementation Checklist

- [ ] SKILL.md created (<500 lines)
- [ ] 8 resource files created (<500 lines each)
- [ ] skill-rules.json configured
- [ ] UserPromptSubmit hook updated
- [ ] Manual testing passed (4 scenarios)
- [ ] USAGE.md updated
- [ ] README.md updated
- [ ] .claude/skills/README.md created
- [ ] Git commit created
- [ ] Success metrics baseline recorded

---

## Next Steps

После завершения P1:

1. **Monitor usage** (1-2 weeks)
   - Track skill activation rate
   - Measure workflow confusion reduction
   - Collect user feedback

2. **Iterate on content** (ongoing)
   - Add more examples based on common questions
   - Refine decision tree based on usage patterns
   - Expand resources for popular workflows

3. **Consider P2** (Standalone Mode)
   - Evaluate if standalone mode needed
   - Assess trade-offs (speed vs learning)
   - Plan implementation if valuable

---

**Plan version:** 1.0
**Dependencies:** P0 Auto-Activation System (must be complete)
**Effort:** 1 week (5 days, ~15-20 hours)
**Priority:** P1 (implement after P0)
