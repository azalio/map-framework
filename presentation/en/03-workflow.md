# MAP Framework Workflow

## Workflow Overview

MAP Framework uses a **strictly sequential orchestration** that begins with TaskDecomposer and then runs an implementation loop for each subtask.

**Mandatory sequence:**

```mermaid
flowchart TD
    Start([Task Start]) --> Decompose[0. TaskDecomposer<br/>Create subtasks]
    Decompose --> Plan[2.5 Checkpoint<br/>Create progress.md]
    Plan --> Actor[1. Actor<br/>Implement subtask]
    Actor --> Monitor[2. Monitor<br/>Quality validation]

    Monitor -->|Valid| Predictor[3. Predictor<br/>Impact analysis]
    Monitor -->|Invalid<br/>max 3-5 iterations| Actor

    Predictor --> Evaluator[4. Evaluator<br/>Quality assessment]

    Evaluator -->|Approved| Accept[5. ACCEPT changes<br/>Apply to files]
    Evaluator -->|Not Approved| Actor

    Accept --> Reflector[6. Reflector<br/>Extract lessons<br/><b>MANDATORY</b>]
    Reflector --> Curator[7. Curator<br/>Update playbook<br/><b>MANDATORY</b>]

    Curator --> End([Subtask Complete])
```

## Orchestrator Slash Commands

MAP provides **10 workflow commands** for different scenarios:

**Primary workflows:**
1. **`/map-efficient`** — implement features, refactor code, complex tasks (recommended default)
2. **`/map-debug`** — debug issues, fix bugs
3. **`/map-fast`** — small, low-risk changes with minimal overhead
4. **`/map-debate`** — multi-variant synthesis with Opus arbiter

**Supporting commands:**
5. **`/map-review`** — review changes before commit
6. **`/map-check`** — quality gates and verification
7. **`/map-plan`** — architecture decomposition only
8. **`/map-release`** — release workflow with validation gates
9. **`/map-resume`** — resume interrupted workflows
10. **`/map-learn`** — extract and preserve lessons (optional learning step)

The **Orchestrator** is NOT a separate agent template; it is the coordination logic implemented in these slash commands.

## Critical Rules Enforcement

### Rule 1: Mandatory Reflector invocation

**PROHIBITED:**

- ❌ “Analyze success manually” and write lessons yourself
- ❌ “Skip Reflector for simple tasks”
- ❌ “Manually create playbook bullets”

**REQUIRED:**

- ✅ Call `Task(subagent_type="reflector", ...)`
- ✅ Verify `mcp__mem0__map_tiered_search` usage in the output
- ✅ Let Reflector extract patterns from agent outputs

**Why:** The Reflector template contains instructions to search for existing patterns. Manual work won't call `mcp__mem0__map_tiered_search` → knowledge gets duplicated.

### Rule 2: Mandatory Curator invocation

**PROHIBITED:**

- ❌ “Apply Reflector insights to playbook yourself”
- ❌ “Edit `.claude/mem0 MCP` manually”
- ❌ “Skip playbook updates for small changes”

**REQUIRED:**

- ✅ Call `Task(subagent_type="curator", ...)`
- ✅ Verify `mcp__mem0__map_tiered_search` is used for deduplication
- ✅ Apply Curator delta operations (ADD/UPDATE/DEPRECATE)
**Why:** The Curator template enforces searching for duplicates BEFORE adding bullets.

### Rule 3: Verify MCP Tool Usage

After invoking Reflector or Curator, the orchestrator **MUST VERIFY** MCP tool usage:

**Reflector output must show:**

- Evidence of `mcp__mem0__map_tiered_search` calls (tool logs, JSON, or narrative with search results)
- Confirmation that search results informed the reasoning (phrasing may vary)

**Curator output must show:**

- Reasoning about deduplication via `mcp__mem0__map_tiered_search`
**If missing:** The agent skipped mandatory MCP calls → investigate (skip tools, mis-reporting, template updates).

## Memory System

### Playbook (Project Memory)

- **Location:** `.claude/mem0 MCP`
- **Purpose:** Structured, categorized patterns for THIS project
- **Format:** Bullets with code examples, tags, helpful/harmful counts
- **Scope:** Single project

## Recitation Pattern — Context Engineering

**Mechanism:**

1. **Step 2.5:** **Orchestrator** creates a recitation plan after TaskDecomposer

   ```bash
   mapify recitation create "$TASK_ID" "$ARGUMENTS" "$SUBTASKS_JSON"
   ```

2. **Step 3.1.5:** **Orchestrator** updates status BEFORE EACH Actor invocation

   ```bash
   mapify recitation update <subtask_id> in_progress
   PLAN_CONTEXT=$(mapify recitation get-context)
   ```

3. **Actor Template:** Receives `{{plan_context}}` via Handlebars in the `<recitation_plan>` section
4. **After completion:** Cleanup removes the `.map/` directory

   ```bash
   mapify recitation clear
   ```

**Progress markers:**

- `[✓]` = completed
- `[→]` = in_progress (current task)
- `[☐]` = pending
- `[✗]` = failed

**Error integration:**

- On Monitor rejection: plan updates with retry attempt number
- Display: “⚠️ Retry attempt 2 — review previous errors”
- Implements patterns `qual-0001` (WHAT/WHERE/HOW/WHY) and `arch-0005` (three-failure threshold)

**Sources:** `CONTEXT-ENGINEERING-IMPROVEMENTS.md` Phase 1.1 (lines 276–289), `.claude/commands/map-efficient.md`

## Actor–Monitor Retry Loop

**Mechanism:**

- Monitor validates Actor output for quality, safety, and correctness
- **IF invalid:** feedback → Actor (re-implementation)
- **Limit:** maximum 3–5 iterations
- **Escalation:** On 3 failures → escalate to user

**Flow:**

```bash
Actor → Monitor (iteration 1)
  IF invalid: Actor → Monitor (iteration 2)
    IF invalid: Actor → Monitor (iteration 3)
      IF invalid: ESCALATE TO USER
  IF valid: → Predictor
```

**Gate:** “You can ONLY reach this step if Monitor returned valid: true”

## MCP Integration in Workflow

MAP uses **5 core MCP tools** to extend workflow capabilities:

1. **`mcp__mem0__map_tiered_search`** — search similar patterns in a semantic memory base
2. **`sequential-thinking`** — complex chains of reasoning
3. **`context7 (resolve-library-id + get-library-docs)`** — up-to-date library documentation
4. **`deepwiki (read_wiki_structure + ask_question)`** — learn from GitHub repositories
5. **`claude-reviewer (request_review)`** — professional code review

## Self-Check Verification

Before completing any MAP workflow subtask the orchestrator **MUST** check 2 questions:

1. ❓ Did I call `Task(subagent_type="reflector", ...)` or "learn" manually?
2. ❓ Did I call `Task(subagent_type="curator", ...)` or update the playbook manually?

**Violations:**

- If "Did it myself" on 1–2 → workflow violation; redo the subtask

## Workflow Logger — Observability

**MapWorkflowLogger** — detailed logging of MAP workflows.

**Activation:** Logging is optional and enabled via:

- CLI flag: `--debug` (e.g., `mapify init --debug`, `mapify check --debug`)
- Environment variable: `MAP_DEBUG=true`

**Actual event names:**

- `session_start`, `session_end`
- `agent_invocation`
- `error`, `timing`
- `recitation_plan_created`, `recitation_subtask_updated`, `recitation_context_retrieved`
- Custom events via `log_event` (e.g., `command_start`)

**Format:** JSON Lines (`.map/logs/workflow_TIMESTAMP.log`)

**Each line includes:**

- `timestamp` (ISO 8601)
- `event` (event name)
- `task_id` (correlates with RecitationManager)
- Event-specific fields (e.g., `prompt_preview`, `response_preview` for agent_invocation)

**Usage:**

- Post-mortem debugging: which agent was called? what prompts were sent?
- Workflow replay: save successful logs as test fixtures
- Event correlation: `task_id` ties events to `.map/current_plan.json`

## Context Engineering Optimizations

### Top-K Playbook Filtering

- **Config:** `.claude/mem0 MCP` → `metadata.top_k = 5`
- **Mechanism:** For every subtask, Actor receives only the 5 most relevant bullets
- **Benefit:** With 25 bullets total, top-5 filtering prevents context distraction

### Principles of Context Engineering

1. **Append-Only Context** — NEVER edit previous messages in history (preserves KV-cache efficiency)
2. **External Storage as Context Extension** — `.map/progress.md` as external memory
3. **Focusing Attention (“Beacon” pattern)** — keeps goals “fresh” in recent tokens via recitation

## Exception: Non-MAP Tasks

These rules apply **ONLY** when using MAP framework commands (`/map-efficient`, `/map-debug`, `/map-fast`, `/map-debate`, `/map-review`, `/map-check`, `/map-plan`, `/map-release`, `/map-resume`, `/map-learn`).

For ordinary tasks (bug fixes, docs, simple changes) you can work directly without the full agent chain.
