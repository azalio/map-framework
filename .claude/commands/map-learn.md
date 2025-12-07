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
2. Calls Curator agent to create playbook delta operations (with deduplication)
3. Applies Curator operations to `.claude/playbook.db`
4. Syncs high-quality bullets (helpful_count >= 5) to cipher for cross-project sharing

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
1. Call mcp__cipher__cipher_memory_search to check if similar patterns already exist in cross-project knowledge base
2. Only suggest new bullets if pattern is genuinely novel (not already in cipher)
3. Reference existing cipher patterns in your analysis

**Analysis Instructions:**

Analyze holistically across ALL subtasks:
- What patterns emerged consistently?
- What worked well that should be repeated?
- What could be improved for future similar tasks?
- What knowledge should be preserved in playbook?
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
- bullet_updates: array of {bullet_id, new_helpful_count, new_harmful_count, reason}
- suggested_new_bullets: array of {section, content, code_example, initial_score, rationale}
- workflow_efficiency: {total_iterations, avg_per_subtask, bottlenecks: array of strings}
- cipher_duplicates_found: array of {pattern, existing_cipher_entry} (from cipher_memory_search results)"
)
```

**Verification:** Check Reflector output contains evidence of `cipher_memory_search` call:
- Should show: "Perfect! I found highly relevant existing knowledge. The cipher search revealed..."
- Or: "No similar patterns found in cipher. This appears to be a novel pattern."

**If cipher_memory_search was NOT called:** Reflector did not follow instructions. Flag this as critical issue.

---

## Step 3: Curator Update

**⚠️ MUST use subagent_type="curator"** (NOT general-purpose):

```
Task(
  subagent_type="curator",
  description="Create playbook operations from workflow learnings",
  prompt="Integrate Reflector insights into playbook:

**Reflector Insights:**
[paste Reflector JSON output from Step 2]

**MANDATORY STEPS:**
1. BEFORE creating ADD operations: call mcp__cipher__cipher_memory_search to verify no duplicates exist in playbook
2. Create delta operations (ADD/UPDATE/DEPRECATE) for playbook
3. AFTER operations defined: IF any bullet has helpful_count >= 5, MUST prepare sync_to_cipher entries

**Deduplication Rules:**
- If Reflector found cipher duplicates: DO NOT create ADD operations, reference existing knowledge instead
- If playbook already has similar bullet: CREATE UPDATE operation with incremented helpful_count
- If pattern is genuinely novel: CREATE ADD operation with initial helpful_count=1

**Bullet Scoring:**
- Set helpful_count=1 for new patterns (will increment over time)
- Set helpful_count=+1 for existing patterns that proved useful again
- Set harmful_count=+1 for patterns that caused issues

**Output JSON with:**
- operations: array of {operation: 'ADD'|'UPDATE'|'DEPRECATE', section, bullet_id, content, code_example, reason}
- deduplication_check: array of {new_bullet_pattern, similar_existing_bullets, action_taken, reason}
- sync_to_cipher: array of {bullet_id, content, helpful_count, section} (REQUIRED if helpful_count >= 5)
- summary: {total_adds, total_updates, total_deprecates, bullets_synced_to_cipher}"
)
```

**Verification:** Check Curator output contains:
- `deduplication_check` array (proves cipher_memory_search was called)
- `sync_to_cipher` array (may be empty if no bullets reach helpful_count >= 5)

**If deduplication_check is missing:** Curator did not follow instructions. Flag this as critical issue.

---

## Step 4: Apply Curator Operations

Apply Curator delta operations to playbook database:

```bash
# Save Curator output to temporary file
cat > /tmp/curator_operations.json <<'EOF'
[paste Curator JSON output from Step 3]
EOF

# Apply to playbook SQLite database
mapify playbook apply-delta /tmp/curator_operations.json

# Verify operations applied
echo "Applied operations:"
mapify playbook query "" --limit 5
```

**Expected output:**
```
Applying delta operations...
✓ Added 2 bullets
✓ Updated 1 bullet
✓ Deprecated 0 bullets
Playbook updated successfully.
```

**If apply-delta fails:** Check JSON format, ensure bullet_ids are valid, verify .claude/playbook.db exists.

---

## Step 5: Sync High-Quality Bullets to Cipher

**Only if Curator output contains `sync_to_cipher` entries:**

For each bullet with helpful_count >= 5, sync to cross-project knowledge base:

```
FOR each entry in sync_to_cipher array:
  mcp__cipher__cipher_extract_and_operate_memory(
    interaction: [bullet content + code_example],
    memoryMetadata: {
      "projectId": "map-framework",
      "source": "curator",
      "section": [bullet section],
      "helpful_count": [bullet helpful_count]
    },
    options: {
      "useLLMDecisions": false,
      "similarityThreshold": 0.85,
      "enableBatchProcessing": true
    }
  )
```

**Example:**
```
mcp__cipher__cipher_extract_and_operate_memory(
  interaction: "Error Handling Pattern: Always wrap external API calls with try/except blocks. Log errors with context (service name, request ID). Return sanitized error messages to users.",
  memoryMetadata: {
    "projectId": "map-framework",
    "source": "curator",
    "section": "ERROR_HANDLING_PATTERNS",
    "helpful_count": 6
  },
  options: {
    "useLLMDecisions": false,
    "similarityThreshold": 0.85
  }
)
```

**Verification:**
```bash
# Verify sync succeeded by searching cipher
mcp__cipher__cipher_memory_search(
  query: [bullet content],
  top_k: 1
)
```

**Expected:** Search should return the newly synced knowledge entry.

**If sync_to_cipher array is empty:** This is normal if no bullets reached helpful_count >= 5 yet. Skip this step.

---

## Step 6: Summary Report

Provide learning summary:

```markdown
## /map-learn Completion Summary

**Workflow Analyzed:** [workflow type from input]
**Total Subtasks:** [N]
**Iterations Required:** [total Actor→Monitor loops]

### Reflector Insights
- **Key Insight:** [key_insight from Reflector]
- **Patterns Used:** [count] existing patterns applied successfully
- **Patterns Discovered:** [count] new patterns identified
- **Cipher Duplicates Found:** [count] (avoided duplication)

### Curator Operations
- **Added:** [N] new bullets to playbook
- **Updated:** [N] existing bullets (incremented helpful_count)
- **Deprecated:** [N] outdated bullets
- **Synced to Cipher:** [N] high-quality bullets (helpful_count >= 5)

### Playbook Impact
- **Total Bullets After Update:** [query playbook for count]
- **Sections Modified:** [list sections]
- **Knowledge Shared Cross-Project:** [N bullets synced to cipher]

### Next Steps
- Review new bullets: `mapify playbook query "[pattern]" --section [SECTION]`
- Validate in next workflow: Apply new patterns and increment helpful_count if successful
- Monitor harmful_count: Deprecate patterns if harmful_count exceeds helpful_count

**Learning cycle complete. Playbook and cipher updated.**
```

---

## Troubleshooting

### Issue: Reflector didn't call cipher_memory_search

**Symptom:** Reflector output has no mention of "cipher search revealed" or "no similar patterns in cipher".

**Cause:** Reflector agent template not followed.

**Fix:**
1. Re-run Reflector with explicit instruction: "FIRST STEP: Call mcp__cipher__cipher_memory_search"
2. Verify output shows search results
3. Proceed to Curator only after verification

### Issue: Curator created duplicates

**Symptom:** apply-delta succeeds but playbook now has redundant bullets.

**Cause:** Curator didn't properly deduplicate against existing playbook.

**Fix:**
1. Query playbook for duplicates: `mapify playbook query "[pattern]"`
2. Manually deprecate duplicates: Create delta JSON with DEPRECATE operations
3. Re-run Curator with explicit deduplication instruction

### Issue: cipher sync failed

**Symptom:** mcp__cipher__cipher_extract_and_operate_memory returns error.

**Cause:** MCP server unavailable or malformed input.

**Fix:**
1. Check MCP server status: Test with simple cipher_memory_search
2. Verify JSON format of interaction parameter
3. Retry with exponential backoff
4. If persistent failure: Skip cipher sync, document in playbook comments

### Issue: apply-delta fails with schema error

**Symptom:** "Invalid operation format" or "Missing required field".

**Cause:** Curator output doesn't match expected delta schema.

**Fix:**
1. Validate Curator JSON against schema:
   - `operations` array required
   - Each operation needs: `operation`, `section`, `bullet_id`, `content`
2. Manually fix JSON if minor format issue
3. Re-run Curator if major structural problem

---

## Token Budget Estimate

**Typical /map-learn execution:**
- Reflector: ~3K tokens (depends on workflow size)
- Curator: ~2K tokens
- Apply operations: <100 tokens (bash)
- Cipher sync: ~500 tokens per bullet
- **Total:** 5-8K tokens for standard workflow

**Large workflow (8+ subtasks):**
- Reflector: ~6K tokens
- Curator: ~3K tokens
- Cipher sync: ~2K tokens (multiple bullets)
- **Total:** 10-15K tokens

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
- Pattern: WebSocket reconnection logic
- Pattern: Optimistic UI updates

Curator creates:
- ADD impl-0042: WebSocket exponential backoff pattern
- ADD frontend-0008: Optimistic UI update pattern

### Example 2: Batched learning from multiple workflows

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
- Specific patterns: DB locks, connection pooling, timezone handling

Curator creates:
- ADD err-0023: Database transaction lock pattern
- ADD perf-0015: Connection pooling pattern
- ADD impl-0056: UTC-everywhere timezone pattern
- UPDATE arch-0009: Concurrency patterns section (increments helpful_count)

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
- Batching multiple workflows to reduce playbook bloat
- Retroactively adding learning to /map-fast workflows
- Capturing holistic patterns across subtasks
- Custom workflows that didn't include learning

**Remember:** The goal is to build organizational knowledge, not to learn from every single task. Quality over quantity.
