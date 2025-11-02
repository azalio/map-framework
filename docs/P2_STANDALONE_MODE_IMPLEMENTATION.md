# Implementation Plan: Standalone Mode for MAP Framework (P2)

## Context

**Priority:** P2 (after P0 and P1 completed)

**Effort:** 2-3 weeks

**Dependencies:**
- ✅ P0 Auto-Activation System implemented
- ✅ P1 Skills System implemented
- ⚠️ Significant refactoring of command templates required

**Статус:** EVALUATE FIRST (assess cost/benefit before implementing)

---

## ⚠️ IMPORTANT: Cost/Benefit Analysis Required

**Before implementing P2, answer these questions:**

1. **How often do users need quick reviews without learning?**
   - If <10% of tasks → P2 may not be worth effort
   - If >30% of tasks → P2 provides value

2. **Is losing learning acceptable for quick tasks?**
   - MAP's key advantage = continuous learning
   - Standalone mode sacrifices this
   - Trade-off: Speed vs systematic improvement

3. **Can workflow-rules.json address the use case?**
   - Auto-suggest /map-fast for throwaway tasks
   - May be sufficient without standalone mode

**Recommendation:** Monitor P0 + P1 usage for 2-4 weeks before deciding on P2

---

## Что это такое?

### Проблема

Некоторые задачи не требуют full learning pipeline:
- Quick code review перед PR
- One-off analysis задачи
- Exploratory research
- Fast feedback loops

**Текущее решение:** Use /map-fast (no learning)

**Limitation:** /map-fast still runs TaskDecomposer, Actor, Monitor, Evaluator
- Can't run single agent standalone
- Always requires workflow invocation

### Решение: Standalone Mode

**Standalone mode** = Run single agent without orchestration

**Two approaches:**

#### Approach 1: Standalone Flag (Less invasive)

Add `--standalone` flag to existing workflows:

```bash
/map-review --standalone  # Skip Reflector/Curator
```

**What changes:**
- Workflow runs normally
- Skips learning agents at end (Reflector, Curator)
- Faster completion
- No playbook/cipher updates

#### Approach 2: Standalone Agent Commands (More flexible)

Direct agent invocation without workflow:

```bash
/agent actor "implement quick prototype"
/agent monitor "check this code"
```

**What changes:**
- No workflow orchestration
- Single agent execution
- Fire-and-forget
- Maximum speed

---

## Референсы для изучения

### Созданная документация

1. **docs/MAP_VS_SHOWCASE_COMPARISON.md** (section "Standalone Agent Mode")
   - Explains trade-offs
   - Compares with Showcase standalone agents

2. **ARCHITECTURE.md**
   - Current orchestration flow
   - Agent specifications
   - Where to inject standalone logic

### Showcase reference

**Standalone pattern:**
- `docs/claude-code-infrastructure-showcase/.claude/agents/*.md`
- Each agent is self-contained markdown
- No orchestration, no learning
- Direct Task tool invocation

**Example:**
```markdown
# Showcase standalone agent
Task(
  subagent_type="general-purpose",
  description="Review code",
  prompt="Load .claude/agents/code-reviewer.md\n\nReview src/auth.ts"
)
```

vs

```markdown
# MAP orchestrated workflow
/map-review → TaskDecomposer → Actor → Monitor → Evaluator → Reflector → Curator
```

---

## Implementation Approaches

### Approach 1: Standalone Flag (RECOMMENDED)

**Pros:**
- Less invasive (minimal code changes)
- Preserves workflow structure
- Easier to test
- Can be per-workflow (`--standalone`)

**Cons:**
- Still requires workflow invocation
- Can't run single agent directly
- Limited flexibility

**Effort:** 1-2 weeks

---

### Approach 2: Standalone Commands (More flexible)

**Pros:**
- Maximum flexibility
- True single-agent execution
- Fast feedback loops
- Direct agent invocation

**Cons:**
- Major refactoring required
- Breaks current workflow model
- Harder to maintain
- Loses orchestration benefits

**Effort:** 3-4 weeks

---

## Implementation Plan: Approach 1 (Standalone Flag)

### Phase 1: Design & Planning (Day 1-2, 4-6 hours)

#### Шаг 1.1: Define standalone semantics (2 hours)

**Questions to answer:**

1. **Which workflows support standalone?**
   - `/map-review --standalone` ✅ (code review without learning)
   - `/map-debug --standalone` ❓ (debugging needs learning?)
   - `/map-feature --standalone` ❌ (contradicts purpose)
   - `/map-fast --standalone` ❌ (already minimal)

**Recommendation:**
- Support only `/map-review --standalone`
- Other workflows keep standard behavior

2. **What does standalone skip?**
   ```
   Standard /map-review:
   TaskDecomposer → Actor → Monitor → Evaluator → Reflector → Curator

   /map-review --standalone:
   TaskDecomposer → Actor → Monitor → Evaluator
   [Skip: Reflector, Curator]
   ```

3. **How to communicate trade-off to user?**
   ```
   User: "/map-review --standalone src/auth.ts"
   MAP: "⚠️  Standalone mode: NO LEARNING (playbook/cipher not updated)
         Use for quick reviews only. For production reviews, use /map-review"
   [Proceed with review...]
   ```

#### Шаг 1.2: Review current workflow structure (2 hours)

**Файлы для изучения:**
```bash
# Workflow command templates
.claude/commands/map-review.md
.claude/commands/map-feature.md
.claude/commands/map-debug.md

# Agent templates
.claude/agents/reflector.md
.claude/agents/curator.md
```

**Key sections:**
```markdown
# In .claude/commands/map-review.md

## Phase 4: Learning (REFLECTION)

7. **Reflector Agent**
   - Invoke Task(subagent_type="reflector", ...)
   - Extract patterns from completed review

8. **Curator Agent**
   - Invoke Task(subagent_type="curator", ...)
   - Update playbook with patterns
```

**Modification strategy:**
- Add conditional logic: `{{#unless standalone_mode}}`
- Skip Reflector/Curator invocation if flag set
- Preserve all other agents

#### Шаг 1.3: Design flag parsing (1-2 hours)

**Challenge:** Slash commands don't natively support flags

**Options:**

**Option A: Parse flag in command template**
```markdown
# .claude/commands/map-review.md

You are orchestrating a MAP code review workflow.

## Step 1: Parse Input

Analyze user input for flags:
- If contains "--standalone": Set standalone_mode = true
- Remove flags from task description

Example:
Input: "/map-review --standalone src/auth.ts"
Parsed:
  - standalone_mode: true
  - task: "Review src/auth.ts"
```

**Option B: Separate command**
```markdown
# .claude/commands/map-review-standalone.md

/map-review-standalone <task>
= /map-review --standalone <task>
```

**Option C: Auto-detect pattern**
```markdown
# In map-review.md

If task description contains:
- "quick review"
- "fast feedback"
- "one-off check"
→ Auto-enable standalone mode
```

**Recommendation:** Option A (explicit flag) for clarity

---

### Phase 2: Implementation (Day 3-7, 15-20 hours)

#### Шаг 2.1: Modify map-review.md template (3-4 hours)

**Файл:** `.claude/commands/map-review.md`

**Changes:**

```markdown
# ADD: Flag parsing section

## Step 1: Parse Input and Flags

**Analyze user input:**

```python
import re

user_input = "{{user_prompt}}"  # Full input including flags

# Check for standalone flag
standalone_mode = "--standalone" in user_input

# Remove flags from task description
task_description = re.sub(r'\s*--standalone\s*', '', user_input)

if standalone_mode:
    print("⚠️  STANDALONE MODE ENABLED")
    print("    - Playbook will NOT be updated")
    print("    - Cipher will NOT be synced")
    print("    - Use for quick reviews only")
    print("")
```

**Task to review:** {task_description}
**Standalone mode:** {standalone_mode}

---

# MODIFY: Learning phase (make conditional)

## Phase 4: Learning (REFLECTION)

{{#unless standalone_mode}}

7. **Reflector Agent** ← CONDITIONAL

Invoke the Reflector agent to analyze the review:

```
Task(
  subagent_type="reflector",
  description="Extract patterns from code review",
  prompt="""
Analyze the completed code review and extract reusable patterns.

Review artifacts:
{review_output}

Search cipher for similar patterns to avoid duplicates.
"""
)
```

8. **Curator Agent** ← CONDITIONAL

Invoke the Curator agent to update playbook:

```
Task(
  subagent_type="curator",
  description="Update playbook with review patterns",
  prompt="""
Apply delta operations to playbook:

{reflector_output}

Check cipher for duplicates before adding.
Sync high-quality patterns (helpful_count ≥ 5) to cipher.
"""
)
```

{{/unless}}

{{#if standalone_mode}}

7-8. **Learning Skipped (Standalone Mode)**

⏭️  Reflector and Curator agents skipped.

**Trade-off:**
- ✅ Faster completion (~30% time savings)
- ❌ No playbook updates (patterns not learned)
- ❌ No cipher sync (knowledge not shared)

**Recommendation:** Use standalone mode sparingly. For production reviews, use standard /map-review.

{{/if}}

---

# ADD: Final summary

## Workflow Complete

{{#if standalone_mode}}
✅ Review complete (Standalone mode - NO LEARNING)

**What was skipped:**
- Reflector analysis
- Playbook updates
- Cipher synchronization

**Next time:** Consider using standard /map-review for production code.
{{else}}
✅ Review complete with learning

**Knowledge updated:**
- Playbook: {new_bullets_count} bullets added
- Cipher: {synced_patterns_count} patterns synced
{{/if}}
```

**Команды для изменения:**
```bash
# Backup original
cp .claude/commands/map-review.md .claude/commands/map-review.md.backup

# Edit file (используй Edit tool)

# Sync to templates
cp .claude/commands/map-review.md src/mapify_cli/templates/commands/
```

#### Шаг 2.2: Add flag support to other workflows (optional, 2-3 hours)

**Consider adding to:**

**map-debug.md:**
```bash
/map-debug --standalone "quick check TypeError"
# Skip learning, just analyze and fix
```

**Trade-off:**
- Debugging insights are valuable to learn
- May want to preserve learning even for quick fixes
- **Recommendation:** Start with map-review only

#### Шаг 2.3: Update documentation (2 hours)

**USAGE.md:**
```markdown
## Standalone Mode

For quick tasks without learning, use `--standalone` flag:

```bash
/map-review --standalone src/auth.ts
```

**What changes:**
- Reflector skipped (no pattern extraction)
- Curator skipped (no playbook updates)
- Result: ~30% faster, but NO LEARNING

**When to use:**
- Quick code review before PR
- One-off sanity checks
- Fast feedback loops
- Exploratory analysis

**When NOT to use:**
- Production code reviews (use standard /map-review)
- Code that will be maintained
- When you want to learn patterns

**Trade-off:**
MAP's key advantage is continuous learning. Standalone mode sacrifices this for speed.

**Alternative:** Use /map-fast for throwaway code (already minimal learning).
```

**README.md:**
```markdown
## Workflow Modes

| Workflow | Token Cost | Learning | Standalone? |
|----------|-----------|----------|-------------|
| /map-fast | 40-50% | ❌ None | N/A (already minimal) |
| /map-efficient | 60-70% | ✅ Batched | ❌ Not supported |
| /map-feature | 100% | ✅ Full | ❌ Not supported |
| /map-debug | 70-80% | ✅ Full | ⚠️ Optional (--standalone) |
| /map-review | 70-80% | ✅ Full | ✅ Yes (--standalone) |
```

**P1 skills integration:**

Update `.claude/skills/map-workflows-guide/SKILL.md`:

```markdown
## Standalone Mode (P2)

For quick tasks without learning:

```bash
/map-review --standalone src/auth.ts
```

**Trade-offs:**
- ✅ 30% faster completion
- ❌ No playbook updates
- ❌ No cipher sync

**Decision tree:**
```
Need quick feedback?
├─ Throwaway code? → /map-fast
└─ Quick review? → /map-review --standalone
```

**When NOT to use:**
- Production code (use /map-review)
- Code that will be maintained
- When learning is valuable
```

#### Шаг 2.4: Update auto-activation (optional, 1-2 hours)

**Enhancement:** Auto-suggest standalone mode for quick tasks

**Файл:** `.claude/workflow-rules.json`

```json
{
  "workflows": {
    "map-review": {
      "priority": "high",
      "variants": {
        "standard": {
          "promptTriggers": {
            "keywords": ["review code", "code review"]
          }
        },
        "standalone": {
          "promptTriggers": {
            "keywords": ["quick review", "fast check", "sanity check"]
          },
          "suggestion": "/map-review --standalone"
        }
      }
    }
  }
}
```

**Hook logic:**
```bash
# In .claude/hooks/user-prompt-submit.sh

if echo "$PROMPT" | grep -qE "(quick|fast|sanity).*?(review|check)"; then
  echo "🎯 WORKFLOW SUGGESTION: /map-review --standalone"
  echo "   Reason: Quick review detected (standalone mode for speed)"
fi
```

---

### Phase 3: Testing (Day 8-9, 6-8 hours)

#### Шаг 3.1: Unit testing (2-3 hours)

**Test standalone flag parsing:**

```bash
# Test case 1: Flag present
INPUT="/map-review --standalone src/auth.ts"
# Expected:
#   standalone_mode: true
#   task: "Review src/auth.ts"

# Test case 2: Flag absent
INPUT="/map-review src/auth.ts"
# Expected:
#   standalone_mode: false
#   task: "Review src/auth.ts"

# Test case 3: Multiple flags (future)
INPUT="/map-review --standalone --verbose src/auth.ts"
# Expected:
#   standalone_mode: true
#   verbose: true
#   task: "Review src/auth.ts"
```

#### Шаг 3.2: Integration testing (2-3 hours)

**Test scenario 1: Standard review (with learning)**

```
User: "/map-review src/auth.ts"

Expected execution:
├─ TaskDecomposer ✅
├─ Actor ✅
├─ Monitor ✅
├─ Evaluator ✅
├─ Reflector ✅
└─ Curator ✅

Expected output:
✅ Review complete with learning
Playbook: 2 bullets added
Cipher: 1 pattern synced
```

**Test scenario 2: Standalone review (no learning)**

```
User: "/map-review --standalone src/auth.ts"

Expected warning:
⚠️  STANDALONE MODE ENABLED
    - Playbook will NOT be updated
    - Cipher will NOT be synced

Expected execution:
├─ TaskDecomposer ✅
├─ Actor ✅
├─ Monitor ✅
├─ Evaluator ✅
├─ Reflector ⏭️ SKIPPED
└─ Curator ⏭️ SKIPPED

Expected output:
✅ Review complete (Standalone mode - NO LEARNING)

What was skipped:
- Reflector analysis
- Playbook updates
```

**Verify:**
```bash
# Check playbook NOT updated
mapify playbook stats
# Bullet count should be unchanged

# Check no task invocations for Reflector/Curator
grep "subagent_type=\"reflector\"" [session_log]
# Should be empty for standalone run
```

#### Шаг 3.3: Performance testing (1-2 hours)

**Measure time savings:**

```bash
# Benchmark standard review
time /map-review src/auth.ts
# Record: completion time, token usage

# Benchmark standalone review
time /map-review --standalone src/auth.ts
# Record: completion time, token usage

# Calculate savings
echo "Time saved: $((standard_time - standalone_time))"
echo "Tokens saved: $((standard_tokens - standalone_tokens))"
```

**Expected savings:**
- Time: 25-35% faster
- Tokens: 20-30% reduction
- Trade-off: No learning

#### Шаг 3.4: User acceptance testing (1-2 hours)

**Scenario: Quick PR review**

```
Context: Developer has 5-minute window before meeting
Task: Quick sanity check of PR changes

User: "/map-review --standalone src/auth.ts src/middleware.ts"

Success criteria:
✅ Review completes in <2 minutes
✅ Identifies obvious issues
✅ No playbook updates (confirmed)
✅ Warning displayed about standalone mode
```

**Scenario: Production code review**

```
Context: Reviewing critical auth changes for production
Task: Comprehensive review with learning

User: "/map-review src/auth.ts"  [No --standalone flag]

Success criteria:
✅ Full review with all agents
✅ Reflector extracts patterns
✅ Curator updates playbook
✅ Patterns synced to cipher
```

---

### Phase 4: Documentation & Rollout (Day 10, 2-3 hours)

#### Шаг 4.1: Create migration guide (1 hour)

**docs/STANDALONE_MODE_GUIDE.md:**

```markdown
# Standalone Mode Guide

## What is Standalone Mode?

Quick execution without learning for one-off tasks.

## Usage

```bash
/map-review --standalone <task>
```

## Decision Tree

```
Need code review?
│
├─ Production code or maintained feature?
│  └─> /map-review (with learning)
│
├─ Quick PR sanity check (<5 min)?
│  └─> /map-review --standalone
│
└─ Throwaway prototype?
   └─> /map-fast (minimal workflow)
```

## Trade-offs

| Aspect | Standard | Standalone |
|--------|----------|------------|
| Speed | Slower | ✅ 30% faster |
| Learning | ✅ Yes | ❌ No |
| Playbook | ✅ Updated | ❌ Skipped |
| Cipher | ✅ Synced | ❌ Skipped |
| Use case | Production | Quick checks |

## Examples

**Good use of standalone:**
- "Quick review before PR submission"
- "Sanity check after refactoring"
- "Fast feedback on approach"

**Bad use of standalone:**
- "Review critical auth system" → Use standard /map-review
- "Review code for production" → Use standard /map-review
- "Learn from this review" → Use standard /map-review

## Best Practices

1. **Default to standard mode** - Only use standalone when time-constrained
2. **Follow up with full review** - For production code, do comprehensive review later
3. **Monitor usage** - If >30% reviews are standalone, re-evaluate workflows
4. **Consider /map-fast** - For truly throwaway code, /map-fast may be better

## Technical Details

**What's skipped:**
- Reflector agent (pattern extraction)
- Curator agent (playbook updates)
- Cipher synchronization

**What's preserved:**
- TaskDecomposer (planning)
- Actor (implementation/analysis)
- Monitor (validation)
- Evaluator (quality gates)

**Performance:**
- Time savings: 25-35%
- Token savings: 20-30%
- Quality: Slightly reduced (no pattern-based improvements)
```

#### Шаг 4.2: Update changelog (15 minutes)

**CHANGELOG.md:**

```markdown
## [Unreleased]

### Added
- **Standalone mode** for quick tasks without learning
  - `/map-review --standalone` skips Reflector and Curator
  - ~30% faster completion
  - Trade-off: No playbook/cipher updates
  - Use for quick checks only, not production code

### Changed
- map-review.md template supports `--standalone` flag
- Auto-activation suggests standalone for "quick review" keywords

### Documentation
- Added docs/STANDALONE_MODE_GUIDE.md
- Updated USAGE.md with standalone mode section
- Updated P1 skills (map-workflows-guide) with standalone decision tree
```

#### Шаг 4.3: Git commit (30 minutes)

```bash
# Stage files
git add .claude/commands/map-review.md \
        src/mapify_cli/templates/commands/map-review.md \
        .claude/workflow-rules.json \
        .claude/hooks/user-prompt-submit.sh \
        .claude/skills/map-workflows-guide/SKILL.md \
        docs/STANDALONE_MODE_GUIDE.md \
        USAGE.md \
        README.md \
        CHANGELOG.md

# Commit
git commit -m "feat: implement standalone mode for quick tasks (P2)

Implements P2 feature from showcase analysis.

What's new:
- /map-review --standalone flag for quick reviews without learning
- Flag parsing in command templates
- Conditional Reflector/Curator execution (skipped in standalone)
- Warning message about trade-offs

Benefits:
- 25-35% faster completion for quick checks
- 20-30% token savings
- Suitable for quick PR reviews, sanity checks, fast feedback

Trade-offs:
- No playbook updates (Curator skipped)
- No cipher sync (Reflector skipped)
- Sacrifices MAP's continuous learning advantage

Usage:
```bash
# Quick review (no learning)
/map-review --standalone src/auth.ts

# Production review (with learning)
/map-review src/auth.ts
```

When to use:
✅ Quick PR sanity checks
✅ Fast feedback before meeting
✅ One-off exploratory analysis
❌ Production code (use standard mode)
❌ Code that will be maintained

Implementation:
- Flag parsing in map-review.md template
- Conditional template sections ({{#unless standalone_mode}})
- Auto-activation enhancement (suggests standalone for 'quick review')
- Integration with P1 skills system (decision tree updated)

Testing:
- Unit tests: flag parsing validated
- Integration tests: learning correctly skipped
- Performance tests: 30% time savings confirmed
- User acceptance: quick review scenario validated

Documentation:
- docs/STANDALONE_MODE_GUIDE.md (comprehensive guide)
- USAGE.md updated (standalone section)
- README.md updated (workflow comparison table)
- P1 skills updated (decision tree includes standalone)

Dependencies: P0 (Auto-Activation), P1 (Skills System)
Effort: 2 weeks (~30-40 hours)
Impact: Selective (use sparingly to preserve learning advantage)"
```

---

## Alternative: Approach 2 (Standalone Commands)

### Overview

Direct agent invocation without workflow orchestration.

### Commands

```bash
/agent actor "implement quick prototype"
/agent monitor "validate this code"
/agent reflector "extract patterns from this session"
```

### Implementation (High-Level)

**Create:** `.claude/commands/agent.md`

```markdown
---
name: agent
description: Invoke single MAP agent standalone
---

You are invoking a single MAP agent without workflow orchestration.

## Step 1: Parse Input

```
/agent <agent_name> <task>

Example: /agent actor "implement user login"
```

**Available agents:**
- actor (implementation)
- monitor (validation)
- predictor (impact analysis)
- evaluator (quality scoring)
- reflector (pattern extraction)
- curator (playbook updates)

## Step 2: Load Agent Template

Load the agent's template from `.claude/agents/<agent_name>.md`.

## Step 3: Invoke Agent

```
Task(
  subagent_type="{agent_name}",
  description="{task}",
  prompt="""
{agent_template_content}

Task: {task}
"""
)
```

## Step 4: Return Result

Output agent result directly (no further orchestration).
```

### Pros & Cons

**Pros:**
- Maximum flexibility
- True standalone execution
- Can chain manually: `/agent actor X` then `/agent monitor X`

**Cons:**
- Breaks workflow orchestration model
- Agents expect orchestration context (previous agent outputs)
- Much harder to implement correctly
- Higher maintenance burden

**Effort:** 3-4 weeks vs 1-2 weeks for Approach 1

**Recommendation:** Only pursue if Approach 1 insufficient after user feedback

---

## Success Metrics

После реализации P2 измерить:

### 1. Usage Patterns

**Standalone mode adoption:**
```bash
# Count standalone invocations
grep "/map-review --standalone" .claude/logs/*.log | wc -l

# Compare to standard reviews
grep "/map-review[^-]" .claude/logs/*.log | wc -l

# Calculate percentage
```

**Target:** 10-20% of reviews use standalone
- If <5%: Feature underutilized (may not be needed)
- If >40%: Overused (users avoiding learning)

### 2. Time Savings

**Measure actual performance:**
```bash
# Average completion time: standard vs standalone
grep "completion_time" .claude/logs/*.log | \
  awk -F'standalone:' '{sum+=$2; count++} END {print sum/count}'
```

**Target:** 25-35% time savings for standalone

### 3. Learning Impact

**Playbook growth rate:**
```bash
# Before P2: bullets per week
# After P2: bullets per week (should decrease slightly)

mapify playbook stats | jq '.metadata.total_bullets'
```

**Target:** <10% reduction in playbook growth
- If >20% reduction: Standalone overused, learning suffering

### 4. Workflow Distribution

**Desired distribution:**
```
map-efficient:     60-70% (most tasks)
map-review:        15-20% (standard reviews)
map-review --standalone: 5-10% (quick checks)
map-debug:         10-15% (bug fixes)
map-feature:       5-10% (critical)
map-fast:          <5% (throwaway)
```

### 5. User Satisfaction

**Qualitative feedback:**
- Faster for quick checks?
- Understand trade-offs?
- Appropriate usage (not overusing)?

---

## Risks & Mitigation

### Risk 1: Standalone Mode Overused

**Problem:** Users default to standalone, losing learning advantage

**Indicators:**
- >40% of reviews use standalone
- Playbook growth slows >20%
- Pattern quality decreases

**Mitigation:**
1. Add usage warnings after N consecutive standalone runs
2. Update P1 skills to emphasize trade-offs
3. Consider removing feature if learning suffers

**Warning message:**
```
⚠️  STANDALONE MODE WARNING

You've used standalone mode 5 times in a row.

Reminder: Standalone mode skips learning.
- No playbook updates
- No pattern extraction
- Future workflows won't benefit

Consider using standard /map-review for your next task.
```

### Risk 2: Users Don't Understand Trade-offs

**Problem:** Use standalone without realizing learning lost

**Indicators:**
- Users surprised playbook not updated
- Questions like "Why didn't this get learned?"

**Mitigation:**
1. Clear warning at start of standalone run
2. Summary at end explaining what was skipped
3. P1 skills education (decision tree)

### Risk 3: Implementation Complexity

**Problem:** Template logic becomes hard to maintain

**Indicators:**
- Bugs in conditional rendering
- Flag parsing errors
- Template variables incorrectly scoped

**Mitigation:**
1. Start with single workflow (map-review only)
2. Comprehensive testing before expanding
3. Clear documentation of template logic

---

## Post-Implementation Checklist

- [ ] P0 Auto-Activation complete (prerequisite)
- [ ] P1 Skills System complete (prerequisite)
- [ ] Cost/benefit analysis performed (>30% usage predicted?)
- [ ] map-review.md template modified
- [ ] Flag parsing logic implemented
- [ ] Conditional learning sections added
- [ ] Templates synced (.claude → src/mapify_cli/templates)
- [ ] workflow-rules.json updated (auto-suggest standalone)
- [ ] P1 skills updated (decision tree includes standalone)
- [ ] USAGE.md updated
- [ ] README.md updated
- [ ] docs/STANDALONE_MODE_GUIDE.md created
- [ ] CHANGELOG.md updated
- [ ] Unit tests passed (flag parsing)
- [ ] Integration tests passed (learning skipped correctly)
- [ ] Performance tests passed (30% time savings)
- [ ] User acceptance tests passed
- [ ] Git commit created
- [ ] Success metrics baseline recorded

---

## Decision Point: Should We Implement P2?

**Answer after P0 + P1 deployed for 2-4 weeks:**

### Implement P2 if:
- ✅ >30% of reviews are quick checks (not production)
- ✅ Users frequently ask for "faster review mode"
- ✅ Use cases clearly benefit from standalone (PR quick checks, etc.)
- ✅ P1 skills successfully educate about trade-offs

### Skip P2 if:
- ❌ <10% of tasks are quick checks
- ❌ /map-fast sufficient for throwaway code
- ❌ Auto-activation (P0) adequately addresses workflow selection
- ❌ Learning advantage more valuable than speed

### Alternative Solutions Before P2:
1. **Improve /map-fast** - Make it faster/lighter for quick tasks
2. **Optimize /map-efficient** - Further token optimizations
3. **Auto-suggest workarounds** - "For quick checks, use /map-fast"

---

## Summary

**Priority:** P2 (lowest)

**Dependencies:** P0 + P1 must be complete

**Effort:**
- Approach 1 (flag): 2 weeks
- Approach 2 (commands): 3-4 weeks

**Impact:** Selective (10-20% of tasks)

**Trade-off:** Speed vs Learning (loses MAP's key advantage)

**Recommendation:** EVALUATE FIRST
- Deploy P0 + P1
- Monitor usage patterns 2-4 weeks
- Decide based on actual user needs
- Consider alternatives before committing

**Next Steps After P2:**
1. Monitor usage (ensure not overused)
2. Iterate on trade-off communication
3. Consider further optimizations if needed

---

**Plan version:** 1.0
**Dependencies:** P0 (Auto-Activation), P1 (Skills System)
**Effort:** 2-3 weeks (~30-50 hours)
**Priority:** P2 (evaluate before implementing)
**Status:** PENDING EVALUATION
