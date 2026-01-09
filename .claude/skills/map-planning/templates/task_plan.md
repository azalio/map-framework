# Task Plan: [Brief Description]
<!--
  WHAT: This is your roadmap for the MAP workflow. Think of it as your "working memory on disk."
  WHY: After 50+ tool calls, your original goals can get forgotten. This file keeps them fresh.
  WHEN: Create this FIRST via init-session.sh. Update after each phase completes.
-->

## Goal
<!--
  WHAT: One clear sentence describing what you're trying to achieve.
  WHY: This is your north star. Re-reading this keeps you focused on the end state.
  EXAMPLE: "Implement JWT authentication for the API with refresh token support."
-->
[One sentence describing the end state]

## Current Phase
<!--
  WHAT: Which phase you're currently working on (e.g., "ST-001", "Phase 2").
  WHY: Quick reference for where you are in the task. Update this as you progress.
-->
Phase 1

## Phases
<!--
  WHAT: Break your task into phases (from task-decomposer or manual).
  WHY: Breaking work into phases prevents overwhelm and makes progress visible.
  WHEN: Update status after completing: pending → in_progress → complete

  TERMINAL STATES (Stop hook accepts these):
  - complete: Phase finished successfully
  - blocked: Waiting on external dependency
  - won't_do: Decided not to implement
  - superseded: Replaced by different approach
-->

### Phase 1: Research & Analysis
<!--
  WHAT: Understand what needs to be done, explore codebase.
  WHY: Starting without understanding leads to wasted effort.
-->
- [ ] Understand requirements
- [ ] Explore relevant code
- [ ] Document findings
- **Status:** in_progress

### Phase 2: Implementation
<!--
  WHAT: Build the solution.
  WHY: This is where the work happens.
-->
- [ ] Implement changes
- [ ] Follow existing patterns
- [ ] Test incrementally
- **Status:** pending

### Phase 3: Validation
<!--
  WHAT: Verify everything works.
  WHY: Catching issues early saves time.
-->
- [ ] Run tests
- [ ] Verify requirements met
- [ ] Fix any issues
- **Status:** pending

### Phase 4: Review & Delivery
<!--
  WHAT: Final review and handoff.
  WHY: Ensures nothing is forgotten.
-->
- [ ] Review changes
- [ ] Document what was done
- [ ] Mark terminal state
- **Status:** pending

## Decisions Made
<!--
  WHAT: Technical and design decisions with reasoning.
  WHY: You'll forget why you made choices. This table helps remember.
  EXAMPLE:
    | Use existing auth library | Reduces complexity, tested code |
-->
| Decision | Rationale |
|----------|-----------|
|          |           |

## Errors Encountered
<!--
  WHAT: Every error encountered with attempt number and resolution.
  WHY: Logging errors prevents repeating mistakes.
  EXAMPLE:
    | ImportError | 1 | Install missing dependency |
-->
| Error | Attempt | Resolution |
|-------|---------|------------|
|       | 1       |            |

## Terminal State
<!--
  WHAT: Final status of the task.
  WHY: Stop hook requires terminal state to exit.

  VALUES:
  - pending: Task not finished (blocks exit)
  - complete: All phases finished successfully
  - blocked: Cannot proceed (needs external input)
  - won't_do: Task intentionally cancelled
  - superseded: Replaced by different approach
-->
**Status:** pending
Reason: [Not yet complete]

---
<!--
  REMINDERS:
  - Update phase status as you progress: pending → in_progress → complete
  - PreToolUse hook shows this file before Write/Edit/Bash
  - Stop hook blocks exit until terminal state reached
  - Log ALL errors - they help avoid repetition
-->
*PreToolUse hook shows this before actions. Stop hook validates terminal state.*
