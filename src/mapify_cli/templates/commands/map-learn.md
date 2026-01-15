---
description: Extract and preserve lessons from completed workflows (OPTIONAL learning step)
---

# MAP Learn - Post-Workflow Learning

**Purpose:** Standalone command to extract and preserve lessons AFTER completing any MAP workflow.

**When to use:**
- After `/map-efficient` completes (to preserve patterns from the workflow)
- After `/map-debug` completes (to preserve debugging patterns)
- After `/map-fast` completes (to retroactively add learning to throwaway code)

**What it does:**
1. Calls Reflector agent to analyze workflow outputs and extract patterns
2. Calls Curator agent to store patterns directly via mem0 MCP tools
3. Verifies patterns stored via `mcp__mem0__map_tiered_search`

**Storage Architecture:**
- Branch tier: `run_id="proj:PROJECT:branch:BRANCH"` (experiment-specific patterns)
- Project tier: `run_id="proj:PROJECT"` (shared across branches)
- Org tier: `user_id="org:ORG"` only (shared across all projects)

**Workflow Summary Input:** $ARGUMENTS

---

## ⚠️ IMPORTANT: This is an OPTIONAL step

**You are NOT required to run this command.** MAP workflows (except /map-fast) include learning by default.

Use /map-learn when:
- You want to batch-learn from multiple workflows at once
- You completed /map-fast and want to preserve lessons retroactively
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
Iterations: 5 total (Actor→Monitor loops)

Subtask 1 (Actor output):
[paste Actor JSON output]

Subtask 1 (Monitor result):
[paste Monitor validation]

...
```

**If input is incomplete:** Ask user to provide missing information before proceeding.

---

## Step 2: Reflector Analysis

**⚠️ MUST use subagent_type="reflector"** (NOT general-purpose):

```
Task(
  subagent_type="reflector",
  description="Extract lessons from completed workflow",
  prompt="Extract structured lessons from this workflow:

**Workflow Summary:**
$ARGUMENTS

**MANDATORY FIRST STEP:**
1. Call mcp__mem0__map_tiered_search to check if similar patterns already exist across tiers
2. Only suggest new bullets if pattern is genuinely novel (not found in any tier)
3. Reference existing patterns with their tier context in your analysis

**Tier Search Parameters:**
- user_id: 'org:ORG_NAME' (for org-level context)
- run_id: 'proj:PROJECT_NAME:branch:BRANCH_NAME' (for branch context with inheritance)

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
- patterns_used: array of strings (existing patterns applied successfully, with tier labels)
- patterns_discovered: array of strings (new patterns worth preserving)
- bullet_updates: array of {bullet_id, tag: 'helpful'|'harmful', reason}
- suggested_new_bullets: array of {section, content, code_example, rationale}
- workflow_efficiency: {total_iterations, avg_per_subtask, bottlenecks: array of strings}
- mem0_duplicates_found: array of {pattern, tier, memory_id} (from tiered search results)"
)
```

**Verification:** Check Reflector output contains evidence of `mcp__mem0__map_tiered_search` call:
- Should show: "mem0 tiered search found existing patterns in [tier]..."
- Or: "No similar patterns found in any tier. This appears to be a novel pattern."

**If tiered search was NOT called:** Reflector did not follow instructions. Flag this as critical issue.

---

## Step 3: Curator Storage

**⚠️ MUST use subagent_type="curator"** (NOT general-purpose):

```
Task(
  subagent_type="curator",
  description="Store workflow learnings via mem0 MCP tools",
  prompt="Store Reflector insights using mem0 MCP tools directly:

**Reflector Insights:**
[paste Reflector JSON output from Step 2]

**MANDATORY: Curator now calls mem0 MCP tools directly (NO JSON delta output)**

**Curator will:**
1. Call mcp__mem0__map_tiered_search to verify no duplicates exist
2. Call mcp__mem0__map_add_pattern for each new pattern
3. Call mcp__mem0__map_promote_pattern for patterns with helpful_count >= 3

**Tier Selection:**
- Branch tier: run_id='proj:PROJECT:branch:BRANCH' (for experimental patterns)
- Project tier: run_id='proj:PROJECT' (for proven patterns)
- Org tier: user_id='org:ORG' only (for cross-project patterns)

**Deduplication via Fingerprinting:**
- Each pattern has SHA256 fingerprint of normalized content
- mcp__mem0__map_add_pattern returns {created: false} if duplicate exists
- Reference existing pattern ID instead of creating duplicate

**Promotion Criteria:**
- helpful_count >= 3: Eligible for promotion to higher tier
- helpful_count >= 5: Auto-promote to project tier
- helpful_count >= 10 with cross-project usage: Promote to org tier"
)
```

**Verification:** Curator will:
- Show tool calls to `mcp__mem0__map_tiered_search` for deduplication
- Show tool calls to `mcp__mem0__map_add_pattern` for new patterns
- Report patterns stored with their tier and memory_id

**If Curator outputs JSON instead of calling tools:** Curator did not follow updated instructions. Flag this as critical issue.

---

## Step 4: Verify Storage

Verify patterns were stored correctly using mem0 tiered search:

```
mcp__mem0__map_tiered_search(
  query="[pattern content from Reflector]",
  user_id="org:ORG_NAME",
  run_id="proj:PROJECT:branch:BRANCH",
  include_archived=false
)
```

**Expected output:**
```json
{
  "results": [
    {
      "memory_id": "mem-abc123",
      "text": "Pattern content...",
      "tier": "branch",
      "metadata": {
        "section_id": "IMPLEMENTATION_PATTERNS",
        "helpful_count": 1,
        "created_at": "2025-01-12T..."
      }
    }
  ],
  "total": 1
}
```

**If patterns not found:** Check Curator tool call outputs for errors. Retry storage if needed.

---

## Step 5: Summary Report

Provide learning summary:

```markdown
## /map-learn Completion Summary

**Workflow Analyzed:** [workflow type from input]
**Total Subtasks:** [N]
**Iterations Required:** [total Actor→Monitor loops]

### Reflector Insights
- **Key Insight:** [key_insight from Reflector]
- **Patterns Used:** [count] existing patterns applied successfully (with tier labels)
- **Patterns Discovered:** [count] new patterns identified
- **mem0 Duplicates Found:** [count] (avoided duplication via fingerprint)

### Curator Storage Results
- **Stored:** [N] new patterns via mcp__mem0__map_add_pattern
- **Skipped (duplicates):** [N] patterns already exist
- **Promoted:** [N] patterns to higher tiers

### Tier Distribution
- **Branch tier:** [N] patterns (run_id=proj:PROJECT:branch:BRANCH)
- **Project tier:** [N] patterns (run_id=proj:PROJECT)
- **Org tier:** [N] patterns (user_id=org:ORG only)

### Next Steps
- Review new patterns: `mcp__mem0__map_tiered_search(query="[pattern]", ...)`
- Validate in next workflow: Apply patterns and increment helpful_count if successful
- Promote proven patterns: Use mcp__mem0__map_promote_pattern for patterns with helpful_count >= 3

**Learning cycle complete. Patterns stored in mem0.**
```

---

## Troubleshooting

### Issue: Reflector didn't call mcp__mem0__map_tiered_search

**Symptom:** Reflector output has no mention of "mem0 tiered search found" or tier labels.

**Cause:** Reflector agent template not followed.

**Fix:**
1. Re-run Reflector with explicit instruction: "FIRST STEP: Call mcp__mem0__map_tiered_search"
2. Verify output shows search results with tier labels
3. Proceed to Curator only after verification

### Issue: Curator output JSON instead of calling tools

**Symptom:** Curator returns JSON delta operations instead of calling mem0 MCP tools directly.

**Cause:** Curator using outdated workflow (pre-mem0 migration).

**Fix:**
1. Ensure Curator agent template is version 4.0.0+
2. Re-run Curator with explicit instruction: "Call mem0 MCP tools directly, DO NOT output JSON"
3. Verify Curator shows mcp__mem0__map_add_pattern calls in output

### Issue: mcp__mem0__map_add_pattern returns duplicate error

**Symptom:** `{created: false, existing_memory_id: "..."}` returned.

**Cause:** Pattern with same fingerprint already exists.

**This is expected behavior!** Fingerprint-based deduplication working correctly.

**Action:**
1. Reference the existing memory_id instead of creating new
2. If pattern needs update, use mcp__mem0__update_memory
3. If pattern should be promoted, use mcp__mem0__map_promote_pattern

### Issue: mem0 MCP server unavailable

**Symptom:** Tool calls fail with connection error.

**Cause:** mem0-mcp server not running or misconfigured.

**Fix:**
1. Check mem0-mcp server status
2. Verify MCP configuration in Claude Code settings
3. Restart mem0-mcp server if needed
4. If persistent failure: Document patterns manually, retry later

### Issue: Patterns stored in wrong tier

**Symptom:** Branch-specific patterns stored at org level, or vice versa.

**Cause:** Incorrect namespace parameters to mcp__mem0__map_add_pattern.

**Fix:**
1. Verify namespace format:
   - Branch: `run_id="proj:PROJECT:branch:BRANCH"` + `user_id="org:ORG"`
   - Project: `run_id="proj:PROJECT"` + `user_id="org:ORG"`
   - Org: `user_id="org:ORG"` only (no run_id)
2. Use mcp__mem0__map_promote_pattern to move to correct tier
3. Archive incorrectly placed pattern with mcp__mem0__map_archive_pattern

---

## Token Budget Estimate

**Typical /map-learn execution:**
- Reflector: ~3K tokens (depends on workflow size)
- Curator: ~2K tokens (direct tool calls, no JSON processing)
- Verification: ~500 tokens (tiered search)
- **Total:** 5-6K tokens for standard workflow

**Large workflow (8+ subtasks):**
- Reflector: ~6K tokens
- Curator: ~4K tokens (multiple pattern storage calls)
- Verification: ~1K tokens
- **Total:** 10-12K tokens

**Compared to per-subtask learning:** /map-learn saves ~(N-1) * 5K tokens for N subtasks.

---

## Examples

### Example 1: Learning from /map-fast workflow

User completed `/map-fast "Prototype real-time dashboard"` (no learning performed).

Now retroactively extract lessons:

```
User: /map-learn "Workflow: /map-fast prototype dashboard
Subtasks: 4 (WebSocket setup, React components, state management, styling)
Files: ws-server.js, Dashboard.jsx, useWebSocket.js, dashboard.css
Iterations: 2 (minor Monitor feedback)

Key implementation:
- WebSocket reconnection with exponential backoff
- React hooks for real-time state updates
- Optimistic UI updates before server confirmation"
```

Reflector extracts:
- mem0 tiered search found no similar patterns in any tier
- Pattern: WebSocket reconnection logic
- Pattern: Optimistic UI updates

Curator stores via mem0 MCP tools:
```
mcp__mem0__map_add_pattern(
  text="WebSocket exponential backoff: Start with 1s delay, double on each retry (max 30s)...",
  user_id="org:myorg",
  run_id="proj:dashboard:branch:feature-ws",
  metadata={section_id: "IMPLEMENTATION_PATTERNS", helpful_count: 1}
)
→ {created: true, memory_id: "mem-abc123", tier: "branch"}

mcp__mem0__map_add_pattern(
  text="Optimistic UI: Update local state immediately, revert on server error...",
  user_id="org:myorg",
  run_id="proj:dashboard:branch:feature-ws",
  metadata={section_id: "FRONTEND_PATTERNS", helpful_count: 1}
)
→ {created: true, memory_id: "mem-def456", tier: "branch"}
```

### Example 2: Batched learning with promotion

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
- mem0 tiered search found "concurrency control" in project tier (helpful_count: 4)
- Common pattern: Concurrency control (UPDATE existing)
- New patterns: DB locks, connection pooling, timezone handling

Curator stores and promotes:
```
# Update existing pattern (increment helpful_count)
mcp__mem0__update_memory(
  memory_id="mem-existing-concurrency",
  text="Updated concurrency control pattern with 3 new use cases..."
)

# Store new patterns at branch tier
mcp__mem0__map_add_pattern(text="Database transaction locks...", ...)
mcp__mem0__map_add_pattern(text="Connection pooling with limits...", ...)
mcp__mem0__map_add_pattern(text="UTC-everywhere timezone pattern...", ...)

# Promote existing pattern to org tier (helpful_count now 5)
mcp__mem0__map_promote_pattern(
  memory_id="mem-existing-concurrency",
  target_user_id="org:myorg"
)
→ {promoted: true, new_memory_id: "mem-org-xyz", new_tier: "org"}
```

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

/map-fast is for throwaway code. Use /map-learn only if:
- The prototype revealed unexpected patterns worth preserving
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

**Storage Architecture Benefits:**
- **Fingerprint deduplication:** Prevents duplicate patterns automatically
- **Tiered inheritance:** Branch patterns inherit from project, project from org
- **Quality-driven promotion:** Proven patterns automatically bubble up to higher tiers
- **Soft delete:** Archived patterns preserved for audit, excluded from search

**Remember:** The goal is to build organizational knowledge, not to learn from every single task. Quality over quantity.
