---
description: Token-efficient MAP workflow with conditional optimizations
---

# MAP Efficient Workflow

## Execution Rules

1. Execute steps in order without pausing; only ask user if (a) `task-decomposer` returns blocking `analysis.open_questions` with no subtasks OR (b) Monitor sets `escalation_required === true` (sub-steps explicitly marked "parallel" may run concurrently)
2. Use exact `subagent_type` specified — never substitute `general-purpose`
3. Call each agent individually — no combining or skipping steps
4. Max 5 retry iterations per subtask

## ⛔ WORKFLOW ENFORCEMENT (Read Every Subtask)

**CRITICAL ANTI-DRIFT RULE:**

Before writing ANY implementation code, you MUST verify:

```text
┌─────────────────────────────────────────────────────────────────┐
│  ⚠️  SELF-CHECK: Am I about to write code myself?               │
│                                                                  │
│  If YES → STOP! You are violating workflow.                     │
│           Use Task(subagent_type="actor") instead.              │
│                                                                  │
│  If calling Task tool → Continue.                               │
└─────────────────────────────────────────────────────────────────┘
```

**BEFORE each Agent call, output this checkpoint:**
```text
CHECKPOINT: Calling [agent_name] for ST-XXX
```

**VIOLATION INDICATORS (If you see yourself doing these, STOP):**
- Writing code blocks without calling Actor first
- Describing implementation approach without Actor
- Saying "Let me implement..." without Task tool
- Writing function/class definitions directly

**CORRECT PATTERN:**
1. Output: `CHECKPOINT: Calling actor for ST-001`
2. Call: `Task(subagent_type="actor", ...)`
3. Wait for Actor output
4. Output: `CHECKPOINT: Calling monitor for ST-001`
5. Call: `Task(subagent_type="monitor", ...)`
6. Wait for Monitor output

**Task:** $ARGUMENTS

## Workflow Overview

```text
1. DECOMPOSE → task-decomposer
1.5. INIT PLANNING → generate .map/task_plan_<branch>.md from blueprint
2. FOR each subtask:
   a. CONTEXT → mem0 tiered search (Actor will run `mcp__mem0__map_tiered_search` per protocol; orchestrator MAY run additional mem0 searches to augment context)
   b. RESEARCH → if existing code understanding needed
   c. IF Self-MoA (--self-moa OR risk_level:high OR complexity_score>=7 OR security_critical:true):
      → 3 Actors (security/performance/simplicity)
      → 3 Monitors → Synthesizer → Final Monitor
   ELSE:
      → Actor → Monitor
   d. If invalid: retry with feedback (max 5)
   e. If risk_level ∈ {high, medium} OR escalation_required === true: → Predictor
   f. Apply changes
3. SUMMARY → optionally suggest /map-learn
```

## Step 1: Task Decomposition

```python
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt="Break down into ≤20 atomic subtasks and RETURN ONLY JSON matching task-decomposer schema v2.0 (schema_version, analysis, blueprint{subtasks[]}).

Task: $ARGUMENTS

Hard requirements:
- Use `blueprint.subtasks[].validation_criteria` (2-4 testable, verifiable outcomes)
- Use `blueprint.subtasks[].dependencies` (array of subtask IDs) and order subtasks by dependency
- Include `blueprint.subtasks[].complexity_score` (1-10) and `risk_level` (low|medium|high)
- Include `blueprint.subtasks[].security_critical` (true for auth/crypto/validation/data access)
- Include `blueprint.subtasks[].test_strategy` with unit/integration/e2e keys"
)
```

## Step 1.5: Initialize Planning Session

**REQUIRED**: Generate persistent plan file from task-decomposer blueprint.

```bash
# 1. Create .map/ directory and planning files
.claude/skills/map-planning/scripts/init-session.sh
```

```bash
# 2. Generate task_plan from blueprint JSON
# Get branch-scoped plan path
PLAN_PATH=$(.claude/skills/map-planning/scripts/get-plan-path.sh)

# Write plan content from blueprint:
# - Header: blueprint.summary as Goal
# - For each subtask: ## ST-XXX section with **Status:** pending
# - First subtask: **Status:** in_progress
# - Terminal State: **Status:** pending
```

**Plan file format** (`.map/task_plan_<branch>.md`):

```markdown
# Task Plan: [blueprint.summary]

## Goal
[blueprint.summary]

## Current Phase
ST-001

## Phases

### ST-001: [subtask.title]
**Status:** in_progress
Risk: [risk_level]
Complexity: [complexity_score]
Files: [affected_files]

Validation:
- [ ] [validation_criteria[0]]
- [ ] [validation_criteria[1]]

### ST-002: [subtask.title]
**Status:** pending
...

## Terminal State
**Status:** pending
```

**Why required:**
- Enables resumption after context reset
- Prevents goal drift in long workflows
- Provides explicit state tracking for orchestrator

## Step 1.6: Initialize Workflow State

**REQUIRED**: Create workflow state tracking file for enforcement.

```bash
# Get branch name (sanitized)
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')

# Create workflow state file
cat > .map/${BRANCH}/workflow_state.json <<'EOF'
{
  "workflow": "map-efficient",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": []
}
EOF
```

**State file schema** (`.map/<branch>/workflow_state.json`):

```json
{
  "workflow": "map-efficient",
  "started_at": "2026-01-27T10:30:00Z",
  "current_subtask": "ST-001",
  "current_state": "ACTOR_CALLED",
  "completed_steps": {
    "ST-001": ["xml_packet", "mem0_search", "actor"]
  },
  "pending_steps": {
    "ST-001": ["monitor", "predictor", "tests", "linter"],
    "ST-002": ["xml_packet", "mem0_search", "research", "actor", "monitor", "tests", "linter"]
  },
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"]
}
```

**Valid states:**
- `INITIALIZED` - Workflow started, no subtask active
- `XML_PACKET_CREATED` - AI packet created for subtask
- `CONTEXT_LOADED` - mem0 search completed
- `RESEARCH_DONE` - Research agent completed
- `ACTOR_CALLED` - Actor generated implementation
- `MONITOR_PASSED` - Monitor validated changes
- `PREDICTOR_ANALYZED` - Predictor assessed impact
- `TESTS_PASSED` - Test gate passed
- `LINTER_PASSED` - Linter gate passed
- `SUBTASK_COMPLETE` - Subtask fully done

**Why required:**
- Enables workflow-gate.py hook enforcement (blocks Edit without actor+monitor)
- Provides explicit state tracking for resumption
- Makes workflow adherence visible and verifiable
- Prevents step-skipping through filesystem-based enforcement

## Step 2: Subtask Loop

**Before each subtask**: Read current plan to prevent goal drift:
```bash
PLAN_PATH=$(.claude/skills/map-planning/scripts/get-plan-path.sh)
# Read Goal and current in_progress phase from $PLAN_PATH
```

**⚠️ CRITICAL: State Tracking Protocol**

After EVERY workflow step completion, you MUST update workflow_state.json using this pattern:

```python
import json
from pathlib import Path

# Load state
branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                       capture_output=True, text=True).stdout.strip().replace('/', '-')
state_file = Path(f".map/{branch}/workflow_state.json")
state = json.loads(state_file.read_text())

# Update for current subtask
subtask_id = state["current_subtask"]
state["completed_steps"][subtask_id].append("[step_name]")  # e.g., "actor", "monitor"
state["current_state"] = "[NEW_STATE]"  # e.g., "ACTOR_CALLED", "MONITOR_PASSED"

# Write back
state_file.write_text(json.dumps(state, indent=2))
```

**Required state updates:**
- After 2.0 (XML Packet): append "xml_packet", state="XML_PACKET_CREATED"
- After 2.1 (mem0 search): append "mem0_search", state="CONTEXT_LOADED"
- After 2.2 (Research): append "research", state="RESEARCH_DONE"
- After 2.4 (Actor): append "actor", state="ACTOR_CALLED"
- After 2.5 (Monitor): append "monitor", state="MONITOR_PASSED"
- After 2.6 (Predictor): append "predictor", state="PREDICTOR_ANALYZED"
- After 2.8 (Tests): append "tests", state="TESTS_PASSED"
- After 2.9 (Linter): append "linter", state="LINTER_PASSED"

**Enforcement:** workflow-gate.py hook will BLOCK Edit/Write until "actor" AND "monitor" are in completed_steps.

**⚠️ MANDATORY: Checkpoint Output Protocol**

Before EVERY agent call or tool use that modifies state, you MUST output this checkpoint block:

```
═══════════════════════════════════════════════════
WORKFLOW CHECKPOINT: [subtask_id] - [step_name]
═══════════════════════════════════════════════════
Current Subtask: [subtask_id]
Current State: [state from workflow_state.json]

Step Checklist:
□ Task Decomposition: [DONE/SKIPPED - reason]
□ XML Packet: [DONE/SKIPPED - reason]
□ mem0 Search: [DONE/SKIPPED - reason]
□ Research Agent: [DONE/SKIPPED - reason if 3+ files]
□ Actor Call: [DONE/SKIPPED - reason]
□ Monitor Validation: [DONE/SKIPPED - reason]
□ Predictor Analysis: [DONE/SKIPPED - reason if medium/high risk]
□ Tests Gate: [DONE/SKIPPED - reason]
□ Linter Gate: [DONE/SKIPPED - reason]

About to: [description of next action]

⚠️ SELF-VERIFICATION:
- Have I completed all required prior steps?
- If skipping ANY step: is there a VALID reason documented above?
- Am I following workflow, not just implementing solution directly?

If any required step is SKIPPED without valid reason: STOP and fix.
═══════════════════════════════════════════════════
```

**Valid skip reasons:**
- "Step not applicable for this subtask" (e.g., Research for 1-file change)
- "Already completed in previous iteration"
- "Dependency not met yet"

**Invalid skip reasons:**
- "I can do it myself" (use agents, don't bypass)
- "Too slow" (workflow > speed)
- "Seems redundant" (all steps required)

### 2.0 Build AI-Friendly Subtask Packet (XML Anchors)

Before calling any agents for the subtask, build a single **AI Packet** with unique XML-like tags (NO attributes).

**Rule:** Use the subtask ID as the anchor name. Convert `-` to `_` for XML tag safety:
- `ST-001` → `ST_001`

**AI Packet template:**

```xml
<SUBTASK_ST_001>
  <SUBTASK_ST_001__ID>ST-001</SUBTASK_ST_001__ID>
  <SUBTASK_ST_001__TITLE>...</SUBTASK_ST_001__TITLE>
  <SUBTASK_ST_001__DESCRIPTION>...</SUBTASK_ST_001__DESCRIPTION>
  <SUBTASK_ST_001__RISK_LEVEL>low|medium|high</SUBTASK_ST_001__RISK_LEVEL>
  <SUBTASK_ST_001__SECURITY_CRITICAL>true|false</SUBTASK_ST_001__SECURITY_CRITICAL>
  <SUBTASK_ST_001__COMPLEXITY_SCORE>1-10</SUBTASK_ST_001__COMPLEXITY_SCORE>

  <SUBTASK_ST_001__AFFECTED_FILES>path1;path2;...</SUBTASK_ST_001__AFFECTED_FILES>
  <SUBTASK_ST_001__VALIDATION_CRITERIA>...</SUBTASK_ST_001__VALIDATION_CRITERIA>
  <SUBTASK_ST_001__CONTRACTS>...</SUBTASK_ST_001__CONTRACTS>
  <SUBTASK_ST_001__TEST_STRATEGY>...</SUBTASK_ST_001__TEST_STRATEGY>

  <SUBTASK_ST_001__CONTEXT_PATTERNS>...</SUBTASK_ST_001__CONTEXT_PATTERNS>
  <SUBTASK_ST_001__RESEARCH_SUMMARY>...</SUBTASK_ST_001__RESEARCH_SUMMARY>
</SUBTASK_ST_001>
```

Pass this packet verbatim to Actor/Monitor/Predictor/Synthesizer. Do NOT rename tags mid-flow.

### 2.1 Get Context + Re-rank

```bash
# Optional prefetch: patterns from mem0 (branch → project → org)
# (Actor will still run its own `mcp__mem0__map_tiered_search` per protocol)
mcp__mem0__map_tiered_search(query="[subtask description]", top_k=5)
```

**Re-rank retrieved patterns** by relevance to current subtask:

```text
FOR each pattern in retrieved_patterns:
  relevance_score = evaluate:
    - Domain match: Does pattern's domain match subtask? (+2)
    - Technology overlap: Same language/framework? (+1)
    - Recency: Created within 30 days? (+1)
    - Success indicator: Marked validated/production? (+1)
    - Complexity alignment: Similar complexity_score? (+1)

  SORT patterns by relevance_score DESC
  PASS top 3 patterns to Actor as "context_patterns"
```

Pass `context_patterns` with relevance scores to Actor for informed decision-making.

### 2.2 Research (Conditional)

**Call if:** refactoring, bug fixes, extending existing code, touching 3+ files
**Skip for:** new standalone features, docs, config

```bash
# Get findings file path for map-planning integration
FINDINGS_PATH=$(.claude/skills/map-planning/scripts/get-plan-path.sh | sed 's/task_plan/findings/')
```

```python
Task(
  subagent_type="research-agent",
  description="Research for subtask [ID]",
  prompt="Query: [subtask description]
File patterns: [relevant globs]
Symbols: [optional keywords]
Intent: locate
Max tokens: 1500
Findings file: [FINDINGS_PATH]"
)
```

Pass `executive_summary` to Actor if `confidence >= 0.7`.

### 2.3 Self-MoA Check

```python
self_moa_enabled = (
    "--self-moa" in user_command OR
    subtask.risk_level == "high" OR
    subtask.security_critical == true OR
    subtask.complexity_score >= 7
)
```

**If Self-MoA enabled:** Execute Self-MoA Path
**Else:** Execute Standard Path

---

## Self-MoA Path

### 2.3a Parallel Actors

Call 3 Actors in parallel with different focuses:

```python
# Variant 1: Security Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Security (v1)",
  prompt="Implement with SECURITY focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: security, variant_id: v1, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)

# Variant 2: Performance Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Performance (v2)",
  prompt="Implement with PERFORMANCE focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: performance, variant_id: v2, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)

# Variant 3: Simplicity Focus
Task(
  subagent_type="actor",
  description="Implement subtask [ID] - Simplicity (v3)",
  prompt="Implement with SIMPLICITY focus:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Playbook Context:** [top context_patterns + relevance_score]
approach_focus: simplicity, variant_id: v3, self_moa_mode: true
Follow the Actor agent protocol output format. Ensure `decisions_made` is included for Synthesizer."
)
```

### 2.3b Parallel Monitors

Validate each variant:

```python
Task(
  subagent_type="monitor",
  description="Validate v1",
  prompt="Review variant v1 against requirements:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Proposed Solution:** [paste v1 Actor output]
**Specification Contract (optional):** [SpecificationContract JSON or null]
variant_id: v1, self_moa_mode: true

Return ONLY valid JSON following MonitorReviewOutput schema.
When in Self-MoA mode, include extension fields: variant_id, self_moa_mode, decisions_identified, compatibility_features, strengths, weaknesses, recommended_as_base.
If `validation_criteria` present: include `contract_compliance` + `contract_compliant`.
If a SpecificationContract is provided: include `spec_contract_compliant` + `spec_contract_violations`."
)
```

### 2.3c Synthesizer

```python
Task(
  subagent_type="synthesizer",
  description="Synthesize best implementation",
  prompt="Combine best parts from v1, v2, v3:

**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Variants (raw Actor outputs):**
<ACTOR_V1_ST_XXX>
[paste v1 Actor output]
</ACTOR_V1_ST_XXX>
<ACTOR_V2_ST_XXX>
[paste v2 Actor output]
</ACTOR_V2_ST_XXX>
<ACTOR_V3_ST_XXX>
[paste v3 Actor output]
</ACTOR_V3_ST_XXX>
**Monitor Results (MonitorReviewOutput JSON):**
<MONITOR_V1_ST_XXX>
[paste v1 Monitor output JSON]
</MONITOR_V1_ST_XXX>
<MONITOR_V2_ST_XXX>
[paste v2 Monitor output JSON]
</MONITOR_V2_ST_XXX>
<MONITOR_V3_ST_XXX>
[paste v3 Monitor output JSON]
</MONITOR_V3_ST_XXX>
**Specification Contract (optional):** [SpecificationContract JSON or null]
**Priority Policy:** [\"correctness\", \"security\", \"maintainability\", \"performance\"]

Return ONLY valid JSON following SynthesizerOutput schema."
)
```

### 2.3d Final Monitor

Validate synthesized code. If invalid: retry synthesis (max 2 iterations).

---

## Standard Path

```text
┌──────────────────────────────────────────────────────────────────┐
│  ⚠️ REMINDER: You are the ORCHESTRATOR, not the implementer.    │
│                                                                   │
│  DO NOT write implementation code yourself.                       │
│  DO call Task(subagent_type="actor") to get implementation.      │
│                                                                   │
│  This reminder appears because drift commonly occurs here.        │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 Actor

**PRE-STEP:** Output `CHECKPOINT: Calling actor for ST-XXX`

```python
Task(
  subagent_type="actor",
  description="Implement subtask [ID]",
  prompt="Implement:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Risk Level:** [risk_level]
**Playbook Context:** [top context_patterns + relevance_score]

Follow the Actor agent protocol output format."
)
```

### 2.4 Monitor (with Contract Validation)

**PRE-STEP:** Output `CHECKPOINT: Calling monitor for ST-XXX`

```python
Task(
  subagent_type="monitor",
  description="Validate implementation",
  prompt="Review against requirements:
**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]
**Proposed Solution:** [paste Actor output]
**Specification Contract (optional):** [SpecificationContract JSON or null]

Check: correctness, security, standards, tests.
If human review is required, set `escalation_required` + `escalation_reason` (per Monitor escalation protocol).

**Contract Validation**: Verify each validation_criterion as testable contract.

Return ONLY valid JSON following MonitorReviewOutput schema.
If validation_criteria present, include contract_compliance + contract_compliant fields."
)
```

### 2.5 Retry Loop (3-Strike Protocol)

**⚠️ ANTI-DRIFT CHECKPOINT:** On retry, you MUST still call Task(actor), NOT implement yourself!

If `valid === false`: provide feedback, retry Actor (max 5 iterations).

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⛔ CRITICAL: NEVER APPLY CHANGES WHEN valid === false                      │
│                                                                              │
│  Even if contract_compliant === true, you MUST NOT apply changes.           │
│  Even if "most issues are minor", you MUST NOT apply changes.               │
│  Even if you think "I'll note issues for later", you MUST NOT apply.        │
│                                                                              │
│  The ONLY condition for applying changes: valid === true                    │
│                                                                              │
│  If valid === false → retry Actor with Monitor feedback                     │
│  If 5 retries exhausted → escalate to user, do NOT apply partial solution   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**3-Strike Protocol** (for persistent failures):

```bash
# Get progress file path
PROGRESS_PATH=$(.claude/skills/map-planning/scripts/get-plan-path.sh | sed 's/task_plan/progress/')
```

```python
FOR attempt = 1 to 5:
  IF attempt >= 3:
    # Log to progress file
    Append to PROGRESS_PATH:
    | Timestamp | Subtask | Attempt | Error | Resolution |
    |-----------|---------|---------|-------|------------|
    | [ISO-8601] | [ST-XXX] | [attempt] | [Monitor feedback summary] | [pending] |

  Call Actor with Monitor feedback
  Call Monitor to validate

  IF valid === true:
    Update progress log: Resolution = "Fixed on attempt [N]"
    BREAK

  IF attempt === 3:
    # Escalate after 3 failed attempts
    AskUserQuestion(
      questions: [{
        header: "3-Strike Limit",
        question: "Subtask [ST-XXX] failed 3 attempts.\n\nLast error: [Monitor feedback]\n\nHow to proceed?",
        multiSelect: false,
        options: [
          { label: "CONTINUE", description: "Try 2 more attempts (max 5 total)" },
          { label: "SKIP", description: "Mark subtask as blocked, move to next" },
          { label: "ABORT", description: "Stop workflow, await manual fix" }
        ]
      }]
    )

    IF user selects "SKIP":
      Update task_plan: **Status:** blocked
      Update progress log: Resolution = "Marked blocked after 3 attempts"
      CONTINUE to next subtask

    IF user selects "ABORT":
      Update task_plan: **Status:** blocked
      Update Terminal State: **Status:** blocked
      EXIT workflow
```

### 2.5b Escalation Gate (AskUserQuestion)

If Monitor returns `escalation_required === true`, you MUST ask user for confirmation before proceeding (Predictor and/or Apply).

```python
AskUserQuestion(
  questions: [
    {
      header: "Escalation Required",
      question: "⚠️ Human review requested by Monitor.\n\nSubtask: [ST-XXX]\nReason: [escalation_reason]\n\nProceed anyway?",
      multiSelect: false,
      options: [
        { label: "YES - Proceed Anyway", description: "Continue (run Predictor if required, then apply changes)." },
        { label: "REVIEW - Show Details", description: "Show Actor output + Monitor JSON + affected files, then ask again." },
        { label: "NO - Abort Subtask", description: "Do not apply changes; wait for human review." }
      ]
    }
  ]
)
```

### 2.6 Conditional Predictor

**Call if:** `risk_level ∈ {high, medium}` OR `escalation_required === true`

```python
Task(
  subagent_type="predictor",
  description="Analyze impact",
  prompt="Analyze impact using Predictor input schema.

**AI Packet (XML):** [paste <SUBTASK_ST_XXX>...</SUBTASK_ST_XXX>]

Required inputs:
- change_description: [1-3 sentence summary of what the Actor change does]
- files_changed: [list of paths inferred from Actor output OR actual modified files]
- diff_content: [unified diff; if not available pre-apply, provide best-effort diff derived from proposed changes, and cap confidence]

Optional inputs:
- analyzer_output: [Actor output]
- user_context: [subtask requirements + risk trigger]

Return ONLY valid JSON following Predictor schema."
)
```

### 2.7 Apply Changes

**GATE CHECK (mandatory before applying):**
```text
IF Monitor.valid !== true:
    → DO NOT PROCEED. Return to Actor with feedback.
    → This is a HARD BLOCK, not a suggestion.
```

Apply via Write/Edit tools.

### 2.7.1 Update Plan Status

After Monitor returns `valid === true`:

```text
1. Read current task_plan from PLAN_PATH
2. Update current subtask: **Status:** in_progress → **Status:** complete
3. Check validation criteria checkboxes [x]
4. Set next pending subtask to **Status:** in_progress
5. Update "Current Phase" to next subtask ID
```

Proceed to next subtask.

### 2.8 Gate 2: Tests Available / Run

After applying changes for a subtask, run tests if available (do NOT install dependencies during this gate).

**Prefer** the commands implied by `<SUBTASK_...__TEST_STRATEGY>`. Otherwise:
- If `pytest` project: run `pytest` (or targeted tests if known)
- If `package.json` present: run `npm test` / `pnpm test` / `yarn test` (whichever is used in repo)
- If `go.mod` present: run `go test ./...`
- If `Cargo.toml` present: run `cargo test`

If no tests found: mark gate as skipped and proceed.

### 2.9 Gate 3: Formatter / Linter

After tests gate, run formatter/linter checks if available (do NOT install dependencies during this gate).

Prefer repo-standard commands first (e.g., `make lint`, `make fmt`, `make check`). Otherwise:
- Python: `ruff check`, `black --check`, `mypy` (if configured)
- JS/TS: `eslint`, `prettier -c` (if configured)
- Go: `gofmt` check + `golangci-lint run` (if configured)
- Rust: `cargo fmt --check`, `cargo clippy`

If none found: mark gate as skipped and proceed.

---

## Step 2.10: Self-Verification Before Completion

**⚠️ CRITICAL: Workflow Adherence Check**

Before proceeding to Step 3, you MUST verify you followed the complete workflow:

```
═══════════════════════════════════════════════════
WORKFLOW ADHERENCE SELF-AUDIT
═══════════════════════════════════════════════════

Question 1: Did I call task-decomposer for decomposition?
Answer: [YES/NO - if NO, explain why not]

Question 2: For EACH subtask, did I:
  - Create XML packet? [YES/NO per subtask]
  - Call mem0 search? [YES/NO per subtask]
  - Call research-agent if 3+ files? [YES/NO/N/A per subtask]
  - Call Actor agent? [YES/NO per subtask]
  - Call Monitor agent after Actor? [YES/NO per subtask]
  - Call Predictor if medium/high risk? [YES/NO/N/A per subtask]
  - Run tests gate? [YES/NO per subtask]
  - Run linter gate? [YES/NO per subtask]
Answer: [List each subtask and answers]

Question 3: Did I ever write code directly without Actor?
Answer: [YES/NO - if YES, this is a VIOLATION]

Question 4: Did I ever skip Monitor after Actor?
Answer: [YES/NO - if YES, this is a VIOLATION]

Question 5: Did I output CHECKPOINT blocks before agent calls?
Answer: [YES/NO - if NO, add them now]

Question 6: Did I update workflow_state.json after each step?
Answer: [YES/NO - if NO, update now]

EVALUATION CRITERIA:
✅ PASSED: All required steps completed, valid reasons for any skips
❌ FAILED: Missing required steps without valid reasons

If FAILED: DO NOT PROCEED. Go back and complete missing steps.

⚠️ REMINDER: You are evaluated on WORKFLOW ADHERENCE, not just
output quality. A perfect solution that skipped steps is WORSE
than an imperfect solution that followed all steps.
═══════════════════════════════════════════════════
```

**Action Required:**
- If self-audit PASSED: Proceed to Step 3
- If self-audit FAILED: Return to Step 2 and complete missing steps

---

## Step 3: Pre-Completion Checks

- Run tests if applicable
- Verify all subtasks marked complete in task_plan
- Confirm workflow_state.json shows all subtasks in "completed_steps"

---

## Step 3.5: Final Verification (Ralph Loop)

**REQUIRED**: After all subtasks complete, verify the ENTIRE task goal is achieved before marking as complete.

### 3.5a Circuit Breaker Check

```python
# Circuit breaker check MUST be concrete and self-contained (no mapify_cli imports).
# Use only:
# - `.claude/ralph-loop-config.json` (single source of truth)
# - `.map/<branch>/.tool_history.jsonl` (canonical tool call count)
# - `.map/<branch>/ralph_state.json` (started_at / plan_iteration)

# 1) Determine sanitized branch name (same sanitizer as hooks)
branch = Bash("python3 - <<'PY'\nimport re, subprocess\n\ntry:\n    raw = subprocess.run(['git','rev-parse','--abbrev-ref','HEAD'], capture_output=True, text=True).stdout.strip()\nexcept Exception:\n    raw = 'default'\n\ns = raw.replace('/', '-')\ns = re.sub(r'[^a-zA-Z0-9_.-]', '-', s)\ns = re.sub(r'-+', '-', s).strip('-')\nif '..' in s or s.startswith('.'): s = 'default'\nprint(s or 'default')\nPY").strip()

# 2) Compute limits + counters (prints JSON)
cb_json = Bash(f"python3 - <<'PY'\nimport json\nfrom datetime import datetime\nfrom pathlib import Path\n\nbranch = {branch!r}\nstate_file = Path(f'.map/{branch}/ralph_state.json')\nhistory_file = Path(f'.map/{branch}/.tool_history.jsonl')\nalerts_file = Path(f'.map/{branch}/thrashing_alerts.jsonl')\nconfig_file = Path('.claude/ralph-loop-config.json')\n\ncfg = {}\nif config_file.exists():\n    try:\n        cfg = json.loads(config_file.read_text(encoding='utf-8'))\n    except Exception:\n        cfg = {}\n\nrl = cfg.get('ralph_loop', {})\ncb = rl.get('circuit_breaker', {})\nredecomp = rl.get('re_decomposition', {})\n\nmax_iterations = int(cb.get('max_total_iterations', 50))\nmax_wall = int(cb.get('max_wall_time_minutes', 60))\nmax_redecomp = int(redecomp.get('max_iterations', 3))\n\n# Ensure state exists with started_at
state = {'plan_iteration': 1}\nif state_file.exists():\n    try:\n        state = json.loads(state_file.read_text(encoding='utf-8'))\n    except Exception:\n        state = {'plan_iteration': 1}\n\nif 'started_at' not in state:\n    state['started_at'] = datetime.now().isoformat()\n    state_file.parent.mkdir(parents=True, exist_ok=True)\n    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding='utf-8')\n\nplan_iteration = int(state.get('plan_iteration', 1))\n\n# Canonical tool call count from history JSONL
tool_count = 0\nif history_file.exists():\n    try:\n        tool_count = sum(1 for line in history_file.read_text(encoding='utf-8').splitlines() if line.strip())\n    except Exception:\n        tool_count = 0\n\n# Wall time from started_at
elapsed_minutes = 0.0\ntry:\n    started = datetime.fromisoformat(state['started_at'])\n    elapsed_minutes = (datetime.now() - started).total_seconds() / 60\nexcept Exception:\n    elapsed_minutes = 0.0\n\n# Thrashing (hook-level): any alerts in the last window
thrashing_detected = False\nthrash_cfg = rl.get('thrashing_detection', {})\nthrash_window = int(thrash_cfg.get('window_size', 3))\ntry:\n    if alerts_file.exists():\n        recent = [ln for ln in alerts_file.read_text(encoding='utf-8').splitlines() if ln.strip()][-thrash_window:]\n        thrashing_detected = len(recent) > 0\nexcept Exception:\n    thrashing_detected = False\n\nprint(json.dumps({\n  'branch': branch,\n  'tool_count': tool_count,\n  'max_iterations': max_iterations,\n  'elapsed_minutes': elapsed_minutes,\n  'max_wall_time_minutes': max_wall,\n  'plan_iteration': plan_iteration,\n  'max_redecompositions': max_redecomp,\n  'thrashing_detected': thrashing_detected\n}, ensure_ascii=True))\nPY").strip()

# 3) cb_json is now a JSON string. Explicit parsing happens in Step 3.5c.
#    See Step 3.5c for:
#    - json.loads(cb_json) to extract tool_count, max_iterations, elapsed_minutes, etc.
#    - Circuit breaker limit checks
#    - AskUserQuestion for RESET_LIMITS / ABORT if limits breached
```

### 3.5a.1 Universal Recovery on Hook Blocks

If ANY tool call (Edit/Write/Bash) is blocked by the Ralph circuit breaker hook (exit code 2, stderr JSON includes `hookSpecificOutput` with message containing `RESET_LIMITS`), you MUST:
- AskUserQuestion with options: `RESET_LIMITS (Recommended)` / `ABORT`
- If `RESET_LIMITS`: `Write(.map/<branch>/.ralph_reset_limits, "reset\n")` and retry the blocked tool ONCE
- If still blocked after retry: ABORT (do not loop)

### 3.5b Run Final Verifier Agent

```python
Task(
    subagent_type="final-verifier",
    description="Final verification of entire goal",
    prompt=f"""Verify that the ORIGINAL GOAL is fully achieved.

**Original Goal:** {original_goal_from_task_plan}
**Validation Criteria:** {validation_criteria_from_decomposition}
**Completed Subtasks:** {list_of_completed_subtask_ids}
**Branch:** {branch}

You MUST:
1. Run available tests (pytest, npm test, etc.)
2. Check MCP tools for ground-truth if available
3. Verify integration between subtasks
4. If FAILED: Provide Root Cause Analysis JSON

Write results to:
- .map/{branch}/final_verification.json (structured)
- .map/progress_{branch}.md (human-readable section)
"""
)
```

### 3.5c Evaluate Results and Decide

```python
# STEP 1: Parse circuit breaker data from cb_json (output of Step 3.5a)
# cb_json is JSON string - parse it into usable variables
cb_data = json.loads(cb_json)

# Extract all values explicitly (no mental parsing)
branch = cb_data["branch"]
tool_count = cb_data["tool_count"]
max_iterations = cb_data["max_iterations"]
elapsed_minutes = cb_data["elapsed_minutes"]
max_wall_time_minutes = cb_data["max_wall_time_minutes"]
plan_iteration = cb_data["plan_iteration"]
max_redecompositions = cb_data["max_redecompositions"]
thrashing_detected = cb_data["thrashing_detected"]

# STEP 2: Check circuit breaker limits BEFORE continuing
circuit_breaker_triggered = False
circuit_breaker_reason = None

if tool_count >= max_iterations:
    circuit_breaker_triggered = True
    circuit_breaker_reason = f"Tool call limit ({max_iterations}) reached"
elif elapsed_minutes >= max_wall_time_minutes:
    circuit_breaker_triggered = True
    circuit_breaker_reason = f"Wall time limit ({max_wall_time_minutes} min) reached"

if circuit_breaker_triggered:
    # Ask user for recovery action
    user_choice = AskUserQuestion(
        questions: [{
            header: "Circuit Breaker",
            question: f"{circuit_breaker_reason}.\n\nHow to proceed?",
            multiSelect: false,
            options: [
                { label: "RESET_LIMITS", description: "(Recommended) Reset limits and continue" },
                { label: "ABORT", description: "Mark as hard_stop and exit" }
            ]
        }]
    )

    if user_choice == "RESET_LIMITS":
        Write(file_path=f".map/{branch}/.ralph_reset_limits", content="reset\n")
        # Re-run Step 3.5a to get fresh cb_json after reset
        Go to Step 3.5a
    else:
        # ABORT - mark as hard_stop
        Update Terminal State: **Status:** hard_stop
        EXIT workflow

# STEP 3: Read verification result (after circuit breaker check passes)
verification_file = Path(f".map/{branch}/final_verification.json")
verification = json.loads(verification_file.read_text())

# STEP 4: Decision logic with explicit variable usage
IF verification["passed"] AND verification["confidence"] >= 0.7:
    # SUCCESS - Complete workflow
    Update Terminal State: **Status:** complete
    Generate success summary
    **Optional:** Run `/map-learn` to preserve patterns
    EXIT workflow

ELSE IF thrashing_detected from cb_json is true:
    # Thrashing detected - escalate
    AskUserQuestion(
        questions: [{
            header: "Thrashing Detected",
            question: "Oscillation detected across iterations.\n\nHow to proceed?",
            multiSelect: false,
            options: [
                { label: "FORCE_COMPLETE", description: "Accept current state as done" },
                { label: "CONTINUE", description: "Try one more re-decomposition" },
                { label: "ABORT", description: "Stop for manual review" }
            ]
        }]
    )

ELSE IF plan_iteration < max_redecompositions:
    # Can retry - go to re-decomposition
    Go to Step 3.5d

ELSE:
    # Max iterations reached - escalate
    AskUserQuestion(
        questions: [{
            header: "Max Iterations",
            question: f"Reached max re-decompositions ({max_redecompositions}).\n\nRoot cause: {verification.get('root_cause', {}).get('suggested_action', 'Unknown')}\n\nHow to proceed?",
            multiSelect: false,
            options: [
                { label: "RESET_LIMITS", description: "Reset limits and try again" },
                { label: "ABORT", description: "Mark as blocked" }
            ]
        }]
    )

    IF user_choice == "RESET_LIMITS":
        Write(file_path=f".map/{branch}/.ralph_reset_limits", content="reset\n")
        Go to Step 3.5a
```

### 3.5d Re-Decomposition

When Final Verification fails and retries remain:

```python
# Summarize previous failure for context pruning
failure_summary = f"Iteration {plan_iteration}: Failed. Root cause: {verification['root_cause']['fix_type']}. Issues: {verification['issues'][:3]}"

Task(
    subagent_type="task-decomposer",
    description="Re-decompose after verification failure",
    prompt=f"""MODE: re_decomposition

**Original Goal:** {original_goal}
**Previous Failure Summary:** {failure_summary}
**Root Cause Analysis:** {json.dumps(verification['root_cause'])}
**Iteration:** {plan_iteration + 1}

RULES:
1. PRESERVE subtasks NOT in root_cause.invalidated_subtasks (keep same ST-IDs)
2. CREATE new subtasks targeting root_cause.unmet_requirements
3. ADD verification criteria for previously failed aspects
4. UPDATE dependency graph if needed

Return JSON with:
- preserved_subtasks: [ST-IDs to keep]
- invalidated_subtasks: [ST-IDs to redo]
- new_subtasks: [new subtask definitions]
"""
)

# Update state
state["plan_iteration"] = plan_iteration + 1
state["failure_summaries"] = state.get("failure_summaries", []) + [failure_summary]
Write(file_path=state_file, content=json.dumps(state, indent=2))

# Update task_plan with new subtasks
# Go back to Step 2 (Subtask Loop) with updated plan
```

---

## Step 4: Summary

- **Update Terminal State** in task_plan:
  ```markdown
  ## Terminal State
  **Status:** complete
  Reason: All [N] subtasks implemented and validated. Final verification passed.
  ```
- Create commit (if requested)
- Report: features implemented, files changed, verification confidence

**Optional:** Run `/map-learn [summary]` to preserve valuable patterns for future workflows.

Begin now with efficient workflow.
