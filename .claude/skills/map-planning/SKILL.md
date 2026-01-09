---
name: map-planning
version: "1.0.0"
description: Implements file-based planning for MAP Framework workflows with branch-scoped task tracking in .map/ directory. Prevents goal drift via automatic plan synchronization before tool use and validates completion state on exit.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
hooks:
  PreToolUse:
    - matcher: "Write|Edit|Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/show-focus.sh"
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/check-complete.sh"
---

# MAP Planning Skill

Implements Manus-style file-based planning adapted for MAP Framework workflows. Uses branch-scoped persistent files to track goals, tasks, progress, and learnings across agent sessions.

## Core Concept

Instead of relying solely on conversation context (limited window), this skill externalizes planning artifacts to the filesystem. The agent reads/writes structured files that survive context resets, enable progress resumption, and provide explicit traceability.

**Key Principle**: Filesystem as Extended Memory
- Plan defines "what to do" (phases, dependencies, criteria)
- Notes capture "what learned" (findings, errors, decisions)
- Progress tracked via checkboxes (visual state)
- Branch-specific scope (isolation between features/bugs)

## File Structure

All files reside in `.map/` directory with branch-based naming:

```
.map/
├── task_plan_<branch>.md      # Primary plan with phases
├── notes_<branch>.md           # Findings, errors, decisions
└── output_<branch>.md          # Final deliverables (optional)
```

**Example**: On branch `feature-auth`, files become:
- `.map/task_plan_feature-auth.md`
- `.map/notes_feature-auth.md`
- `.map/output_feature-auth.md`

**Rationale**: Branch scoping prevents plan conflicts when switching branches. Each feature/bug has isolated context.

## Hook Behavior

### PreToolUse Hook (Before Write/Edit/Bash)

**Trigger**: Every time actor invokes `Write`, `Edit`, or `Bash` tool

**Action**: Runs `${CLAUDE_PLUGIN_ROOT}/scripts/show-focus.sh`
- Resolves current branch name via git
- Determines plan file path: `.map/task_plan_<branch>.md`
- Displays first 30 lines of plan (goal + current phase)
- **Purpose**: Re-anchors agent to original goal before taking action

**Why Critical**: Prevents goal drift. Without periodic re-reading, agents lose track of multi-step plans and invent unnecessary work or skip planned steps.

**Output Format**:
```
🎯 Current Focus (branch: feature-auth)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Goal: Implement JWT authentication for API

Phases:
- [x] Phase 1: Research JWT libraries
- [ ] Phase 2: Implement token generation ← CURRENT
- [ ] Phase 3: Add middleware validation
- [ ] Phase 4: Write integration tests
```

### Stop Hook (Before Agent Exit)

**Trigger**: Before conversation/session terminates

**Action**: Runs `${CLAUDE_PLUGIN_ROOT}/scripts/check-complete.sh`
- Reads plan file for current branch
- Parses terminal state: `complete`, `blocked`, `won't_do`, `superseded`
- **Success**: If terminal state present, exit gracefully
- **Warning**: If no terminal state, prompt user to mark status

**Valid Terminal States**:
```yaml
complete: All phases finished successfully
blocked: Cannot proceed (needs external input/resources)
won't_do: Task intentionally cancelled
superseded: Replaced by different approach/task
```

**Example Plan with Terminal State**:
```markdown
## Terminal State
Status: complete
Reason: All phases implemented and tested. Ready for code review.
```

**Why Critical**: Prevents silent failures where agent "forgets" unfinished work. Forces explicit acknowledgment of completion or blockers.

## Plan File Structure

### Minimal Required Sections

```markdown
# Task Plan: <Brief Title>

## Goal
<1-2 sentence description of what to achieve>

## Phases
- [ ] Phase 1: <Description>
  - Acceptance: <How to verify completion>
  - Files: <Affected files/modules>
- [ ] Phase 2: <Description>
  - Acceptance: <Criteria>
  - Files: <Paths>

## Terminal State
Status: <pending|complete|blocked|won't_do|superseded>
Reason: <Explanation if status != pending>
```

### Extended Sections (Optional)

```markdown
## Context
<Background info, requirements, constraints>

## Dependencies
- External: <Libraries, services, APIs>
- Internal: <Other modules/features>

## Risks
- <Identified risks with mitigation strategies>

## Progress Log
<Append-only journal of what happened when>
```

## Notes File Structure

### Purpose
Capture findings, errors, and decisions during execution. Acts as agent's "working memory" across sessions.

```markdown
# Notes: <Task Name>

## Findings
### <Timestamp> - <Topic>
<What discovered, where found, why relevant>

## Errors Encountered
### <Timestamp> - <Error Type>
**Error**: <Message/stack trace>
**Context**: <What was being attempted>
**Resolution**: <How fixed or workaround>
**Attempts**: <Diagnostic steps tried>

## Decisions Made
### <Timestamp> - <Decision Point>
**Options**: <Alternatives considered>
**Chosen**: <Selected approach>
**Rationale**: <Why this choice>
**Trade-offs**: <What given up>

## Search History
- Query: "<search terms>" → Found: <file/resource>
- Query: "<terms>" → Empty (need different approach)
```

## Workflow Integration

### 1. Initialization (via init-session.sh)

When starting new MAP workflow:
```bash
${CLAUDE_PLUGIN_ROOT}/scripts/init-session.sh
```

**Actions**:
- Detects current git branch
- Creates `.map/` directory if missing
- Generates skeleton plan: `.map/task_plan_<branch>.md`
- Generates skeleton notes: `.map/notes_<branch>.md`
- Sets terminal state: `pending`

**Agent Responsibility**: Populate goal and phases based on task description

### 2. Pre-Action Sync (Automatic via PreToolUse Hook)

Before every code change or command:
- Hook auto-displays current focus from plan
- Agent reviews: "Am I still working toward the goal?"
- If drifted: correct course by referring to plan

**No Manual Action Required** - Hook handles automatically

### 3. Progress Tracking (Manual Agent Updates)

As phases complete:
```markdown
- [x] Phase 1: Research JWT libraries ← Mark complete
  Completed: 2025-01-10 10:30
  Notes: Selected jsonwebtoken@9.0.0 for simplicity
```

**Best Practice**: Update checkboxes immediately after phase completion

### 4. Notes Logging (Continuous)

Append findings to notes file as discovered:
```bash
# Edit notes_<branch>.md, add entry:
## Findings
### 2025-01-10 11:15 - Token Expiration Config
Found env var JWT_EXPIRES_IN controls token TTL.
Default: 1h, production recommendation: 15m.
Source: .env.example line 23
```

**Pattern**: Timestamp → Topic → Details → Source

### 5. Error Recovery (3-Attempt Protocol)

When error occurs:
```markdown
## Errors Encountered
### 2025-01-10 12:00 - ImportError: jsonwebtoken
**Error**: Module 'jsonwebtoken' not found
**Context**: Running auth.test.js
**Attempts**:
1. Diagnostic: Check package.json → Missing dependency
2. Alternative: npm install jsonwebtoken@9.0.0
3. Resolution: Dependency installed, tests pass

Status: RESOLVED
```

**Escalation Rule**: After 3 failed attempts, mark phase as `blocked` and request human input

### 6. Terminal State Declaration (Manual)

Upon completion OR blockage:
```bash
# Edit task_plan_<branch>.md, update terminal state:
## Terminal State
Status: complete
Reason: All 4 phases implemented. Integration tests pass. PR ready.
Completed: 2025-01-10 14:30
```

**Trigger**: Stop hook validates this before exit

## MAP Framework Specific Patterns

### Decomposer Integration

**TaskDecomposer** agent generates initial plan:
1. Analyzes user request
2. Creates phases aligned with MAP workflow:
   - Phase 1: Research/Analysis (uses Research-Agent if needed)
   - Phase 2: Implementation (Actor)
   - Phase 3: Validation (Monitor)
   - Phase 4: Impact Analysis (Predictor, if high-risk)
   - Phase 5: Quality Gate (Evaluator)
3. Writes plan to `.map/task_plan_<branch>.md`
4. Sets acceptance criteria per phase

### Actor Sync Pattern

**Before implementing**, Actor agent:
```bash
# PreToolUse hook auto-runs, displaying:
# - Current phase from plan
# - Acceptance criteria for this phase
# - Files to modify

# Actor confirms alignment:
# "Phase 2 requires implementing token generation in auth/jwt.js"
# → Proceed with Write(auth/jwt.js, ...)
```

### Monitor Validation Against Plan

**Monitor** agent reads plan acceptance criteria:
```markdown
- [ ] Phase 3: Add middleware validation
  Acceptance: Middleware rejects expired tokens with 401 status
  Test: curl -H "Authorization: Bearer <expired>" returns 401
```

**Monitor checks**:
1. Reads acceptance criteria from plan
2. Runs specified tests
3. Marks phase complete if pass, else returns to Actor with feedback

### Predictor Risk Assessment

**Predictor** appends risk findings to notes:
```markdown
## Risks
### 2025-01-10 - Dependency on Redis
Phase 2 token storage requires Redis availability.
Mitigation: Add health check endpoint, graceful degradation to in-memory cache.
Impact: Medium (service availability concern)
```

**Referenced in plan**:
```markdown
- [ ] Phase 6: Handle Redis failures
  Acceptance: Service degrades gracefully if Redis down
  Notes: See Risk Assessment in notes.md
```

## Resumption After Interruption

**Scenario**: Agent session ended mid-task (token limit, timeout, etc.)

**Recovery Steps**:
1. New session starts, calls `${CLAUDE_PLUGIN_ROOT}/scripts/show-focus.sh`
2. Script displays plan with current progress
3. Agent reads notes file for context on what was tried
4. Continues from first unchecked phase

**Example**:
```markdown
Phases:
- [x] Phase 1: Research (completed)
- [x] Phase 2: Implementation (completed)
- [ ] Phase 3: Validation ← RESUME HERE
- [ ] Phase 4: Testing
```

**Agent Action**: "Resuming Phase 3 validation. Last note shows tests written but not run. Running tests now..."

## Best Practices

### 1. Goal Clarity
- Write goal as user story: "As [role], I need [feature] so that [benefit]"
- Avoid vague: "Improve auth" → Specific: "Add JWT refresh tokens to reduce re-login friction"

### 2. Granular Phases
- Each phase = 1 agent role (Research, Implement, Validate, etc.)
- Phases should take <30 min each
- If phase complex, break into sub-phases

### 3. Explicit Acceptance Criteria
- Must be testable: "Middleware rejects invalid tokens" (good)
- Not: "Middleware works correctly" (vague)
- Include command to verify: `npm test auth.test.js`

### 4. Append-Only Notes
- Never delete old notes, only append
- Mark outdated info with "OBSOLETE:" prefix
- Preserves decision trail for future reference

### 5. Checkpoint Frequently
- Update checkboxes immediately after phase completion
- Write notes entry after significant finding
- Don't batch updates — context may be lost

### 6. Declare Terminal State Early
- Don't wait for Stop hook to prompt
- Mark `blocked` as soon as blocker identified
- Mark `complete` immediately after last phase passes

## Error Handling

### Common Issues

**Issue**: Plan file not found
**Cause**: Not on git branch OR `.map/` directory missing
**Fix**: Run `init-session.sh` to bootstrap structure

**Issue**: PreToolUse hook shows stale plan
**Cause**: Plan edited outside agent (direct file edit)
**Fix**: Expected behavior — hooks always read from disk for truth

**Issue**: Stop hook warns "No terminal state"
**Cause**: Agent finished work but forgot to update plan
**Fix**: Edit plan, add terminal state section, re-trigger Stop hook

**Issue**: Multiple branches share same plan
**Cause**: Branch name contains special chars (e.g., slashes)
**Fix**: Scripts sanitize branch names: `feature/auth` → `feature-auth`

## Script Reference

### show-focus.sh
**Purpose**: Display current plan focus before actions
**Usage**: Auto-invoked by PreToolUse hook
**Logic**:
```bash
branch=$(git branch --show-current | sed 's/\//-/g')
plan=".map/task_plan_${branch}.md"
head -30 "$plan" | grep -E "(Goal|Phase|Status)"
```

### check-complete.sh
**Purpose**: Validate terminal state before exit
**Usage**: Auto-invoked by Stop hook
**Logic**:
```bash
plan=".map/task_plan_$(git branch --show-current | sed 's/\//-/g').md"
if grep -q "Status: complete\|blocked\|won't_do\|superseded" "$plan"; then
  exit 0  # Terminal state present
else
  echo "⚠️  No terminal state. Update plan before exiting."
  exit 1
fi
```

### get-plan-path.sh
**Purpose**: Resolve branch-specific plan path (helper)
**Usage**: Called by show-focus.sh and check-complete.sh
**Logic**:
```bash
branch=$(git branch --show-current | sed 's/\//-/g')
echo ".map/task_plan_${branch}.md"
```

### init-session.sh
**Purpose**: Bootstrap planning structure for new task
**Usage**: Manual call at workflow start
**Logic**:
```bash
mkdir -p .map
branch=$(git branch --show-current | sed 's/\//-/g')
cat > ".map/task_plan_${branch}.md" <<EOF
# Task Plan: <Fill in title>

## Goal
<Describe goal>

## Phases
- [ ] Phase 1: <Description>

## Terminal State
Status: pending
EOF
```

## Integration with MAP Workflows

### /map-efficient
1. User invokes: `/map-efficient "Add JWT auth"`
2. Orchestrator calls `init-session.sh` → creates plan skeleton
3. TaskDecomposer populates phases in plan file
4. Actor implements Phase 1 → PreToolUse hook shows focus
5. Monitor validates → marks Phase 1 complete in plan
6. Repeat for Phases 2-N
7. Evaluator approves → Actor sets terminal state: `complete`
8. Stop hook validates → session ends cleanly

### /map-debug
1. User invokes: `/map-debug "Fix failing auth tests"`
2. Init creates plan: `.map/task_plan_bugfix-auth.md`
3. Phases:
   - Phase 1: Analyze test failure logs (notes capture stack trace)
   - Phase 2: Identify root cause (notes document hypothesis)
   - Phase 3: Implement fix
   - Phase 4: Verify tests pass
4. Each phase reads notes from previous phase for context
5. Terminal state: `complete` (tests green) or `blocked` (need more info)

### /map-fast (Degraded Mode)
- Skips planning for throwaway code
- No plan files created
- PreToolUse hook no-op if plan missing
- Stop hook skips validation

## Anti-Patterns

❌ **Overwriting Plan**
- Never replace entire plan file
- Append phases, don't delete completed ones
- Keep history for audit trail

❌ **Skipping Notes**
- "I'll remember this error" → Lost after context window
- Always log errors immediately to notes file

❌ **Vague Terminal States**
```markdown
Status: complete
Reason: Done
```
✅ **Better**:
```markdown
Status: complete
Reason: All 5 phases implemented and tested. Integration tests pass (see test/auth.test.js). PR #123 created.
Completed: 2025-01-10 15:45
```

❌ **Manual Hook Execution**
- Don't call `show-focus.sh` manually unless debugging
- Hooks auto-trigger — trust the system

❌ **Forgetting Terminal State**
- Always declare terminal state explicitly
- Don't rely on Stop hook to remind you

## Terminal States Explained

### `complete`
**When**: All phases finished successfully, acceptance criteria met
**Next**: Code review, merge to main, deploy
**Example**: "All 4 phases complete. Tests pass. PR ready."

### `blocked`
**When**: Cannot proceed without external input (human decision, resource, access)
**Next**: Wait for blocker resolution, document in notes
**Example**: "Blocked: Need production API keys from DevOps. Opened ticket OPS-456."

### `won't_do`
**When**: Task intentionally cancelled (requirements changed, deprioritized)
**Next**: Archive plan, close issue
**Example**: "Won't do: Product decided to use OAuth instead of JWT."

### `superseded`
**When**: Different approach adopted mid-task (better solution found)
**Next**: Reference new plan in reason
**Example**: "Superseded: Switched to using existing auth library (see task_plan_auth-v2.md)."

---

## Quick Reference

**Start New Task**:
```bash
${CLAUDE_PLUGIN_ROOT}/scripts/init-session.sh
# Edit .map/task_plan_<branch>.md with goal and phases
```

**Resume Interrupted Task**:
```bash
# PreToolUse hook auto-displays plan on first action
# Read notes file for context on what was tried
```

**Mark Phase Complete**:
```markdown
- [x] Phase 2: Implementation
  Completed: 2025-01-10 11:30
  Notes: Used jsonwebtoken@9.0.0, tests pass
```

**Declare Terminal State**:
```markdown
## Terminal State
Status: complete
Reason: All phases done, tests green, PR created
Completed: 2025-01-10 14:00
```

**Handle Blocker**:
```markdown
## Terminal State
Status: blocked
Reason: Need Redis setup in staging env (ticket OPS-789)
Blocked: 2025-01-10 12:00
```

---

## Version History

**1.0.0** (2025-01-10)
- Initial release
- Branch-scoped planning for MAP Framework
- PreToolUse hook (show-focus.sh)
- Stop hook (check-complete.sh)
- Terminal state validation
- Integration with /map-efficient, /map-debug, /map-fast

---

**See Also**:
- [MAP Workflows Guide](../map-workflows-guide/SKILL.md) - Choose right workflow
- [MAP CLI Reference](../map-cli-reference/SKILL.md) - Command syntax

**References**:
- [planning-with-files v2.0](https://github.com/OthmanAdi/planning-with-files) - Original Manus pattern
- [MAP Framework Architecture](../../../docs/ARCHITECTURE.md) - Agent orchestration
