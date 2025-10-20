# MAP Workflow Enforcement Rules

**CRITICAL**: When using MAP (Modular Agentic Planner) framework, orchestrator MUST follow strict agent invocation rules to ensure cipher integration works correctly.

## Problem Statement

**Discovered Issue**: Agents (Reflector, Curator) have cipher MCP tool instructions in their templates (`.claude/agents/reflector.md`, `.claude/agents/curator.md`), but orchestrator was skipping agent invocation and doing their work manually. This caused:

- `cipher_memory_search` never called → duplicate knowledge
- `cipher_extract_and_operate_memory` never called → knowledge not shared across projects
- Cipher database stayed empty despite learning valuable patterns

**Root Cause**: No enforcement that Reflector and Curator MUST be invoked via `Task` tool. Orchestrator "optimized" by doing their work directly, bypassing MCP tools.

## Mandatory Agent Sequence

**NEVER skip agents or do their work yourself!** Each agent has specific MCP tool requirements that only execute when the agent is properly invoked via Task tool.

### Required Sequence Per Subtask

```
1. Actor (implement)
2. Monitor (validate)
   → If invalid: return to Actor with feedback
3. Predictor (analyze impact)
4. Evaluator (score quality)
   → If not approved: return to Actor
5. ✅ REFLECTOR (extract lessons) ← MANDATORY
6. ✅ CURATOR (update playbook) ← MANDATORY
```

## Critical Enforcement Rules

### Rule 1: ALWAYS Invoke Reflector

**NEVER:**
- ❌ "Analyze the success yourself" and write lessons
- ❌ "Skip Reflector for simple tasks"
- ❌ "Manually create playbook bullets"

**ALWAYS:**
- ✅ Call `Task(subagent_type="reflector", ...)`
- ✅ Verify Reflector used `cipher_memory_search` (check output)
- ✅ Let Reflector extract patterns from agent outputs

**Why:** Reflector template contains instructions to search cipher for existing patterns. When orchestrator does Reflector's work manually, `cipher_memory_search` is NEVER called, causing duplicate knowledge.

### Rule 2: ALWAYS Invoke Curator

**NEVER:**
- ❌ "Apply Reflector insights to playbook yourself"
- ❌ "Manually Edit .claude/playbook.json"
- ❌ "Skip playbook update for small changes"

**ALWAYS:**
- ✅ Call `Task(subagent_type="curator", ...)`
- ✅ Verify Curator used `cipher_memory_search` for deduplication
- ✅ Apply Curator's delta operations (ADD/UPDATE/DEPRECATE)
- ✅ Call `cipher_extract_and_operate_memory` if `sync_to_cipher` has entries

**Why:** Curator template contains instructions to:
1. Check cipher for duplicates before adding bullets
2. Sync high-quality bullets (helpful_count >= 5) back to cipher

Manual updates skip BOTH of these critical steps.

### Rule 3: Verify MCP Tool Usage

After calling Reflector or Curator, CHECK their output contains:

**Reflector Output Should Show:**
```
Perfect! I found highly relevant existing knowledge. The cipher search revealed...
```

**Curator Output Should Show:**
```json
{
  "sync_to_cipher": [
    {"bullet_id": "impl-0008", "content": "...", "helpful_count": 5}
  ]
}
```

**If missing:** The agent DID NOT follow its template instructions. This is a critical workflow failure.

## Self-Check Questions for Orchestrator

Before completing any MAP workflow subtask, orchestrator must verify:

1. ❓ Did I call `Task(subagent_type="reflector", ...)` or did I extract lessons myself?
2. ❓ Did I call `Task(subagent_type="curator", ...)` or did I update playbook myself?
3. ❓ Did Reflector's output show it searched cipher?
4. ❓ Did Curator's output show `sync_to_cipher` operations?

**If you answered "I did it myself" to questions 1-2:** You violated MAP workflow rules. Redo the subtask correctly.

**If you answered "No" to questions 3-4:** The agents didn't follow their templates. Investigate why:
- Check agent template has `<mcp_integration>` section
- Check agent template references cipher tools
- Verify MCP server is running (`mcp__cipher__*` tools available)

## Why This Matters: Dual Memory System

MAP framework uses a dual memory architecture:

### Playbook (Project-Specific)
- **Location**: `.claude/playbook.json`
- **Purpose**: Structured, categorized patterns for THIS project
- **Format**: Bullets with code examples, tags, helpful/harmful counts
- **Scope**: Single project

### Cipher (Cross-Project)
- **Location**: MCP tool (external semantic database)
- **Purpose**: Shared knowledge across ALL projects
- **Format**: Semantic embeddings for similarity search
- **Scope**: All projects using cipher

**When orchestrator skips agents:**
- ✅ Playbook gets updated (orchestrator does it manually via Edit tool)
- ❌ Cipher NEVER gets updated (MCP tools not called)
- ❌ Knowledge not deduplicated (cipher_memory_search not called)
- ❌ Future workflows don't benefit from lessons learned

**Result:** Working in a loop, re-learning the same lessons every time, because cipher stays empty.

## Implementation Checklist

### For /map-feature Command

Update `.claude/commands/map-feature.md` with:

**Step 3.8 (Reflector):**
```markdown
**⚠️ CRITICAL:** Reflector template contains MANDATORY cipher_memory_search instructions.

**Verification Checklist:**
- [ ] Did Reflector output show cipher_memory_search was called?
- [ ] Did Reflector check for duplicate patterns before suggesting new bullets?
```

**Step 3.9 (Curator):**
```markdown
**⚠️ CRITICAL:** Curator template contains MANDATORY cipher integration.

**Verification Checklist:**
- [ ] Did Curator output show cipher_memory_search for deduplication?
- [ ] Did Curator output show sync_to_cipher operations?
```

**Step 3.10 (Apply Operations):**
```markdown
**MANDATORY**: If Curator output contains sync_to_cipher array with ANY entries:
- MUST call mcp__cipher__cipher_extract_and_operate_memory
- DO NOT skip cipher sync
```

### For Orchestrator Instructions

Add to `~/.claude/CLAUDE.md` or project docs:

```markdown
# MAP Workflow Enforcement

**NEVER skip agents in MAP workflows!**

Required sequence:
1. Actor → Monitor → Predictor → Evaluator
2. REFLECTOR (mandatory - uses cipher_memory_search)
3. CURATOR (mandatory - uses cipher sync)

Verify MCP tool usage in agent outputs.
```

## Testing the Fix

### Test 1: Verify Reflector Uses Cipher

Call Reflector with test data:

```
Task(subagent_type="reflector", ...)
```

Check output contains:
```
Perfect! I found highly relevant existing knowledge. The cipher search revealed...
```

### Test 2: Verify Curator Syncs to Cipher

After Curator runs, check output has:
```json
{
  "sync_to_cipher": [...]
}
```

Then verify orchestrator calls:
```
mcp__cipher__cipher_extract_and_operate_memory(...)
```

## Exception: Non-MAP Tasks

These rules ONLY apply when using MAP framework commands:
- `/map-feature`
- `/map-debug`
- `/map-refactor`
- `/map-review`

For regular tasks (simple bug fixes, documentation updates), orchestrator can work directly without invoking the full agent chain.

## Related Documentation

- Agent Templates: `.claude/agents/reflector.md`, `.claude/agents/curator.md`
- Playbook: `.claude/playbook.json`
- Cipher MCP: Check MCP server configuration for `mcp__cipher__*` tools
- Investigation Findings: `docs/INCOMPLETE_PLAN_BEHAVIOR_FINDINGS.md` (example of lessons that should be in cipher)

## Version History

- **2025-10-20**: Initial documentation after discovering cipher wasn't being populated
- **Root Cause**: Orchestrator skipped Reflector/Curator invocation, bypassing MCP tools
- **Fix**: Added explicit enforcement rules and verification checklists
