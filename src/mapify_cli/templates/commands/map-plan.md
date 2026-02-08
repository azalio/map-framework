# /map-plan — ARCHITECT Phase (Decomposition Only)

**Purpose:** Plan and decompose complex tasks into atomic subtasks. This command ONLY plans - it does NOT execute or verify.

**When to use:**
- Starting a new feature, refactoring, or complex bug fix
- Need to break down work into manageable pieces
- Want to establish clear task boundaries before execution

**What this command does:**
- Optionally runs a short discovery pass (research-agent) to identify key files/patterns
- Calls task-decomposer agent to break down the user's request into subtasks
- Creates `.map/<branch>/task_plan_<branch>.md` with subtask list
- Initializes `.map/<branch>/workflow_state.json` with subtask sequence
- **STOPS** after planning (forces context flush)

**What this command CANNOT do:**
- ❌ Execute implementation
- ❌ Verify completion (use /map-check for that)
- ❌ Edit code directly

---

## Workflow Steps

### Step 0: Quick Discovery (Optional but Recommended)

If the request touches an existing codebase (most do), do a short discovery pass to avoid planning in a vacuum.

Use research-agent to find:
- the most relevant files/dirs
- existing patterns to follow
- obvious integration points and risks

Example:

```
Task(
  subagent_type="research-agent",
  description="Quick discovery for planning",
  prompt=f"""
Locate the most relevant code for this request and return:
- 5-15 key file paths (with 1-line why each matters)
- any existing similar implementations/patterns
- risks/unknowns and what to verify

User request:
{user_requirements}
"""
)
```

If discovery is not needed (new greenfield code or already-provided spec), skip to Step 1.

### Step 1: Assess Scope and Decide Interview Depth

Read the user's requirements and decide if deep interview is needed.

**Interview REQUIRED when:**
- Large increment: 2+ features in one request
- Vague product idea without clear technical approach
- New project (stack + features undefined)
- Batch of bugs/issues to fix together
- User's requirements have obvious gaps or unstated assumptions

**Interview SKIPPED when:**
- Task is already well-defined with clear acceptance criteria
- Small isolated change (single bug fix, test update)
- User explicitly provided a spec or detailed description

If interview is not needed, skip to Step 3.

### Step 2: Deep Interview (Spec Discovery)

Use AskUserQuestionTool to systematically interview the user. The goal is to surface non-obvious decisions and tradeoffs BEFORE planning.

**Rules:**
- Questions must be NON-OBVIOUS (don't ask what the user already stated)
- Cover all dimensions: technical implementation, UI/UX, risks, tradeoffs, edge cases, data model, performance, security
- Ask in small rounds (1-2 high-signal questions; up to 2-4 if needed) using AskUserQuestionTool
- Continue iterating until all critical decisions are captured
- After each round, assess: are there still unresolved architectural decisions?

**Interview dimensions checklist:**
1. **Technical:** Stack choices, data model, API contracts, state management
2. **UX:** User flows, error states, edge cases, accessibility
3. **Tradeoffs:** Performance vs simplicity, flexibility vs speed, build vs buy
4. **Risks:** What can break? What's the blast radius? Rollback strategy?
5. **Scope:** What's explicitly OUT of scope? Minimal scope vs extended scope?
6. **Integration:** How does this interact with existing code? Migration needed?
7. **Contract Clarity:** Are ALL goals stated as outcomes (not processes)? Reject "improve auth" — require "AuthService returns 401 for expired tokens". Every goal must be verifiable.

**Example AskUserQuestionTool call:**
```
AskUserQuestionTool(questions=[
  {
    "question": "Should refresh tokens be stored server-side (Redis/DB) or stateless (signed JWT)?",
    "header": "Token store",
    "options": [
      {"label": "Server-side (Redis)", "description": "More secure, revocable, but adds infra dependency"},
      {"label": "Stateless JWT", "description": "No infra needed, but harder to revoke"},
      {"label": "Hybrid", "description": "Access=stateless, Refresh=server-side"}
    ],
    "multiSelect": false
  },
  {
    "question": "What happens when a user's session expires mid-action (e.g., filling a form)?",
    "header": "Session UX",
    "options": [
      {"label": "Silent refresh", "description": "Auto-refresh token in background, user doesn't notice"},
      {"label": "Modal prompt", "description": "Show re-login dialog, preserve form state"},
      {"label": "Redirect", "description": "Redirect to login, lose form state"}
    ],
    "multiSelect": false
  }
])
```

**After interview is complete**, write the spec to `.map/<branch>/spec_<branch>.md`:

```markdown
# Spec: [Title]

**Date:** $(date -u +%Y-%m-%d)
**Branch:** ${BRANCH}

## Decisions Made

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Token storage | Server-side (Redis) | Need revocation support |
| 2 | Session expiry UX | Silent refresh | Better UX, no data loss |

## Out of Scope

- [Explicitly excluded items]

## Open Questions

- [Anything still unresolved]
```

### Step 3: Create Branch Directory

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
mkdir -p .map/${BRANCH}
```

### Step 4: Explore Approaches + Architecture Graph

If there are multiple valid designs (and the user didn't specify the approach), propose 2-3 approaches with tradeoffs and capture the chosen direction before decomposition.

Skip approach exploration if the approach is obvious or the task is a clear bug fix with a known solution.

**Architecture Graph (REQUIRED for complexity >= 3):**
Before calling the decomposer, write a brief architecture graph to `spec_<branch>.md` (append if spec exists, create if not). This gives the decomposer a "skeleton" to attach subtasks to.

```markdown
## Architecture Graph

```
UserModel -[has_many]-> Project -[has_one]-> ArchiveState
ProjectService -[calls]-> ProjectModel.update()
api/routes/projects.py -[uses]-> ProjectService
GET /projects -[filters_by]-> archived_at
```

Format: `ClassA -[relationship]-> ClassB` (arrow notation)
Relationships: has_many, has_one, calls, extends, uses, creates
Keep under 200 tokens — only include nodes touched by the feature.
```

### Step 5: Call Task Decomposer

Use the task-decomposer agent to break down the work. Pass spec, discovery, and architecture graph as context:

```
Task(
  subagent_type="task-decomposer",
  description="Decompose task into subtasks",
  prompt=f"""
Break down this task into atomic, testable subtasks:

{user_requirements}

{"Spec with decisions + Architecture Graph: .map/<branch>/spec_<branch>.md" if spec_exists else ""}

{"Discovery notes from research-agent are available in this chat" if discovery_done else ""}

Output requirements:
- Each subtask MUST include an aag_contract: "Actor -> Action(params) -> Goal"
- Each subtask should be completable within ~4000 tokens (SFT comfort zone)
- Include acceptance criteria for each
- Each subtask should include an explicit verification approach (tests/commands)
- Identify dependencies between subtasks
- Estimate complexity (low/medium/high)
- Use architecture_graph_summary to map subtasks to affected modules
"""
)
```

### Step 6: Create Human-Readable Plan

Write the plan to `.map/<branch>/task_plan_<branch>.md`. Wrap content in `<MAP_Plan_v1_0>` semantic brackets for machine-parseable handoff to executors:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
cat > .map/${BRANCH}/task_plan_${BRANCH}.md <<EOF
<MAP_Plan_v1_0 branch="${BRANCH}" created="$(date -u +%Y-%m-%d)">

# Task Plan: [Brief Title]

**Workflow:** map-plan

## Overview

[1-2 sentence description of the overall goal]

## Subtasks

### ST-001: [Subtask Title]
- **AAG Contract:** `Actor -> Action(params) -> Goal`
- **Complexity:** [low/medium/high]
- **Dependencies:** [none | ST-XXX, ST-YYY]
- **Description:** [What needs to be done]
- **Acceptance Criteria:**
  - [ ] Criterion 1
  - [ ] Criterion 2
- **Verification:**
  - [ ] Tests added/updated for new/changed behavior
  - [ ] Test command(s) to run: [e.g., pytest -k ...]

### ST-002: [Next Subtask]
...

## Execution Order

1. ST-001 → ST-002 (ST-002 depends on ST-001)
2. ST-003 (can run in parallel)

## Notes

[Any important context, gotchas, or design decisions]

</MAP_Plan_v1_0>
EOF
```

**AAG Contract is REQUIRED** for every subtask. Copy directly from task-decomposer output's `aag_contract` field. This is the primary handoff to the Actor agent — without it, the Actor reasons instead of compiles.

### Step 7: Initialize Workflow State (Do This Last)

Create `.map/<branch>/workflow_state.json` with the decomposition results. Wrap in `<MAP_State_v1_0>` comment for executor parsing.

Do this AFTER writing `task_plan_<branch>.md` so planning artifacts are created before the state gate becomes active.

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed 's/\//-/g')
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > .map/${BRANCH}/workflow_state.json <<EOF
{
  "_semantic_tag": "MAP_State_v1_0",
  "workflow": "map-plan",
  "started_at": "${STARTED_AT}",
  "current_subtask": null,
  "current_state": "INITIALIZED",
  "completed_steps": {},
  "pending_steps": {},
  "subtask_sequence": ["ST-001", "ST-002", "ST-003"],
  "aag_contracts": {
    "ST-001": "Actor -> Action(params) -> Goal",
    "ST-002": "Actor -> Action(params) -> Goal"
  }
}
EOF
```

**IMPORTANT:**
- Replace `subtask_sequence` with actual IDs from the decomposition
- Populate `aag_contracts` map with each subtask's AAG contract from the decomposer output — executors read this to set context for each subtask

### Step 8: Output Checkpoint

Print a clear checkpoint showing the plan is complete:

```
═══════════════════════════════════════════════════
WORKFLOW CHECKPOINT: PLAN PHASE COMPLETE
═══════════════════════════════════════════════════
✅ Deep interview completed (N decisions captured)
✅ Architecture graph written to spec_${BRANCH}.md
✅ Task decomposed into N subtasks with AAG contracts
✅ workflow_state.json initialized (with aag_contracts map)
✅ Plan written to .map/${BRANCH}/task_plan_${BRANCH}.md
✅ Context distilled (plan files ≤4000 tokens per subtask)

Next Steps:
1. Review the plan in task_plan_${BRANCH}.md
2. If approved, start executing subtasks sequentially
3. After completing all subtasks, verify:
   /map-check

📋 Subtask Sequence: [ST-001, ST-002, ST-003]
═══════════════════════════════════════════════════
```

**Note:** If interview was skipped (small/well-defined task), the spec line will not appear.

### Step 8: Context Distillation + STOP

**Before stopping, verify the distilled state is self-contained.** The next session starts fresh — it will ONLY see files, not this conversation. Ensure these files contain everything needed:

```
DISTILLATION CHECKLIST:
  [x] task_plan_<branch>.md — has AAG contracts for every subtask
  [x] workflow_state.json   — has aag_contracts map + subtask_sequence
  [x] spec_<branch>.md      — has architecture graph + decisions (if interview was done)
  [x] findings_<branch>.md  — has research pointers (if discovery was done)

TARGET: Executor reads ≤4000 tokens of distilled state to start any subtask.
If plan files exceed this, condense — remove redundant descriptions, keep AAG contracts + criteria.
```

**This phase ends here.** Do NOT proceed to execution. The context should be flushed, and execution will start fresh with focused attention on individual subtasks.

---

## Design Rationale

**Why deep interview before decomposition?**

1. **Surface Hidden Decisions:** Users often have unstated assumptions. Non-obvious questions force these to the surface before code is written.

2. **Self-Checklist Effect:** The interview benefits the user as much as the AI — it's a structured walkthrough of factors that are easy to forget.

3. **Reduce Rework:** Decisions made during interview prevent costly pivots mid-implementation.

**Why separate planning from execution?**

1. **Context Isolation:** Planning requires broad analysis; execution requires deep focus. Mixing them causes attention dilution.

2. **Forced Checkpoint:** By stopping after planning, we ensure the plan is reviewed before execution begins.

3. **Token Efficiency:** Planning context can be large (requirement analysis, codebase exploration). Execution doesn't need this context.

4. **Cognitive Load:** LLMs perform better on single-phase tasks. Multi-phase instructions get semantically compressed.

---

## Related Commands

- **/map-check** - Verify all subtasks completed successfully
- **/map-efficient** - Monolithic workflow (all phases in one command)

---

## State Machine Integration

This command transitions workflow_state.json through these states:

```
(none) → INITIALIZED
```

Subtask execution will transition:
```
INITIALIZED → IN_PROGRESS → ... → SUBTASK_COMPLETE
```

Final /map-check will transition:
```
SUBTASK_COMPLETE (all subtasks) → WORKFLOW_COMPLETE
```

---

## Hook Enforcement

workflow-gate.py is designed to prevent code edits during execution phases until required steps are complete.

/map-plan should:
- avoid editing repo code (outside `.map/`)
- finish writing planning artifacts (spec/task_plan) before creating `workflow_state.json`

---

## Example Usage

```bash
# User wants to add authentication to their app
User: "Add JWT authentication with refresh tokens"

# You call /map-plan (this command)
# Result:
# - .map/main/spec_main.md with architecture graph + decisions
# - .map/main/task_plan_main.md with 5 subtasks + AAG contracts:
#   ST-001: Add JWT library dependency
#     AAG: PackageConfig -> add_dependency(pyjwt) -> import succeeds
#   ST-002: Implement token generation service
#     AAG: TokenService -> generate(user_id, ttl) -> returns signed JWT
#   ST-003: Add middleware for token validation
#     AAG: AuthMiddleware -> validate(request) -> 401|passes with user_id
#   ST-004: Implement refresh token rotation
#     AAG: TokenService -> refresh(old_token) -> new access+refresh pair
#   ST-005: Add integration tests
#     AAG: TestSuite -> test_auth_flow() -> all 12 assertions pass

# After planning phase completes, user reviews and starts execution
```

---

## Troubleshooting

**Q: Task-decomposer created too many subtasks (10+)?**
A: Subtasks are too granular. Ask task-decomposer to group related work into larger chunks (aim for 3-7 subtasks).

**Q: User changed requirements after planning?**
A: Re-run /map-plan. It will overwrite task_plan_<branch>.md and reset workflow_state.json.

---

## Success Criteria

This command succeeds when:
- ✅ Deep interview completed (if scope warranted it) with spec_<branch>.md written
- ✅ Architecture graph written in spec_<branch>.md (for complexity >= 3)
- ✅ task_plan_<branch>.md exists with AAG contracts for every subtask
- ✅ workflow_state.json exists with valid subtask_sequence + aag_contracts map
- ✅ CHECKPOINT shows subtask count and IDs
- ✅ Context distilled (plan files self-contained for fresh session)
- ✅ You STOPPED (did not proceed to execution)
