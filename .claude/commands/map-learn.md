---
description: Extract and preserve lessons from completed workflows (OPTIONAL learning step)
---

# MAP Learn - Post-Workflow Learning

**Purpose:** Standalone command to extract lessons AFTER completing any MAP workflow.

**When to use:**
- After `/map-efficient` completes (to preserve patterns from the workflow)
- After `/map-debug` completes (to preserve debugging patterns)
- After `/map-fast` completes (to retroactively add learning when learning was skipped)

**What it does:**
1. Calls Reflector agent to analyze workflow outputs and extract patterns
2. Outputs a structured learning summary for the user to review

**Workflow Summary Input:** $ARGUMENTS

---

## IMPORTANT: This is an OPTIONAL step

**You are NOT required to run this command.** No MAP workflow includes automatic learning -- learning is always a separate step via this command.

Use /map-learn when:
- You completed /map-efficient, /map-debug, or /map-fast and want to extract lessons
- You want to batch-learn from multiple workflows at once
- You want to manually trigger learning for custom workflows

**Do NOT use this command:**
- During active workflow execution (run after workflow completes)
- If no meaningful patterns emerged from the workflow

---

## Step 1: Validate Input

Check that $ARGUMENTS contains workflow summary:

**Required information:**
- Workflow type (feature, debug, refactor, review, custom)
- Subtask outputs (Actor implementations)
- Validation results (Monitor feedback)
- Analysis results (Predictor/Evaluator outputs, if available)
- Workflow metrics (total subtasks, iterations, files changed)

**Example valid input:**
```
Workflow: /map-efficient "Add user authentication"
Subtasks completed: 3
Files changed: api/auth.py, models/user.py, tests/test_auth.py
Iterations: 5 total (Actor->Monitor loops)

Subtask 1 (Actor output):
[paste Actor JSON output]

Subtask 1 (Monitor result):
[paste Monitor validation]

...
```

**If input is incomplete:** Ask user to provide missing information before proceeding.

---

## Step 2: Reflector Analysis

**MUST use subagent_type="reflector"** (NOT general-purpose):

```
Task(
  subagent_type="reflector",
  description="Extract lessons from completed workflow",
  prompt="Extract structured lessons from this workflow:

**Workflow Summary:**
$ARGUMENTS

**Analysis Instructions:**

Analyze holistically across ALL subtasks:
- What patterns emerged consistently?
- What worked well that should be repeated?
- What could be improved for future similar tasks?
- What knowledge should be preserved?
- What trade-offs were made and why?

**Focus areas:**
- Implementation patterns (code structure, design decisions)
- Security patterns (auth, validation, error handling)
- Testing patterns (edge cases, test structure)
- Performance patterns (optimization, resource usage)
- Error patterns (what went wrong, how it was fixed)

**Output JSON with:**
- key_insight: string (one sentence takeaway for entire workflow)
- patterns_used: array of strings (existing patterns applied successfully)
- patterns_discovered: array of strings (new patterns worth preserving)
- bullet_updates: array of {bullet_id, tag: 'helpful'|'harmful', reason}
- suggested_new_bullets: array of {section, content, code_example, rationale}
- workflow_efficiency: {total_iterations, avg_per_subtask, bottlenecks: array of strings}"
)
```

---

## Step 3: Summary Report

Provide learning summary:

```markdown
## /map-learn Completion Summary

**Workflow Analyzed:** [workflow type from input]
**Total Subtasks:** [N]
**Iterations Required:** [total Actor->Monitor loops]

### Reflector Insights
- **Key Insight:** [key_insight from Reflector]
- **Patterns Used:** [count] existing patterns applied successfully
- **Patterns Discovered:** [count] new patterns identified

### Discovered Patterns
[List each pattern from patterns_discovered with description]

### Suggested Improvements
[List each suggested_new_bullet with section and rationale]

### Workflow Efficiency
- **Total Iterations:** [total_iterations]
- **Average per Subtask:** [avg_per_subtask]
- **Bottlenecks:** [list bottlenecks]

**Learning extraction complete.**
```

---

## Token Budget Estimate

**Typical /map-learn execution:**
- Reflector: ~3K tokens (depends on workflow size)
- Summary: ~500 tokens
- **Total:** 3-4K tokens for standard workflow

**Large workflow (8+ subtasks):**
- Reflector: ~6K tokens
- Summary: ~1K tokens
- **Total:** 6-7K tokens

---

## Examples

### Example 1: Learning from /map-fast workflow

User completed `/map-fast "Implement real-time dashboard"` (no learning performed).

Now retroactively extract lessons:

```
User: /map-learn "Workflow: /map-fast real-time dashboard
Subtasks: 4 (WebSocket setup, React components, state management, styling)
Files: ws-server.js, Dashboard.jsx, useWebSocket.js, dashboard.css
Iterations: 2 (minor Monitor feedback)

Key implementation:
- WebSocket reconnection with exponential backoff
- React hooks for real-time state updates
- Optimistic UI updates before server confirmation"
```

Reflector extracts:
- Pattern: WebSocket reconnection logic
- Pattern: Optimistic UI updates

### Example 2: Batched learning

User completed 3 separate debugging sessions, wants to batch-learn:

```
User: /map-learn "Workflows: 3 debugging sessions this week

Session 1: Fixed race condition in payment processing
- Pattern: Added database transaction locks
- Iterations: 4

Session 2: Resolved memory leak in WebSocket connections
- Pattern: Implemented connection pooling with limits
- Iterations: 3

Session 3: Fixed timezone bug in scheduler
- Pattern: Always use UTC internally, convert at display layer
- Iterations: 2

Common theme: Concurrency issues"
```

Reflector extracts:
- Common pattern: Concurrency control
- New patterns: DB locks, connection pooling, timezone handling

---

## Integration with Other Commands

### After /map-efficient (recommended)

/map-efficient does NOT include automatic learning. Use /map-learn to:
- Extract patterns from completed implementation
- Preserve successful approaches for future reference
- Document any edge cases discovered

### After /map-debug (recommended)

/map-debug does NOT include automatic learning. Use /map-learn to:
- Capture holistic debugging strategy
- Preserve error investigation patterns
- Document root cause analysis approach

### After /map-fast (optional)

/map-fast is a reduced-analysis workflow. Use /map-learn only if:
- The work revealed patterns worth preserving
- You want to retroactively capture learnings

---

## Final Notes

**This command is OPTIONAL.** You are not required to run it after every workflow.

**When to skip /map-learn:**
- No meaningful patterns emerged
- Throwaway code with no reusable insights
- Time constraints (learning can happen later)

**When to use /map-learn:**
- Batching multiple workflows for efficient pattern extraction
- Retroactively adding learning to /map-fast workflows
- Capturing holistic patterns across subtasks
- Custom workflows that didn't include learning

**Remember:** The goal is to build organizational knowledge, not to learn from every single task. Quality over quantity.
