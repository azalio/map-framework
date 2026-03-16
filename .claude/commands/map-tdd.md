---
description: TDD workflow — test-first development with spec-driven tests written before implementation
---

# /map-tdd — Test-Driven Development Workflow

**Purpose:** Enforce test-first development where tests are written from the SPECIFICATION (not from implementation), ensuring tests validate intent rather than confirming implementation bugs.

**When to use:**
- Features where correctness is critical (auth, payments, data integrity)
- When you want tests that truly validate behavior, not mirror implementation
- When AI-written tests tend to pass trivially (testing what was written, not what was specified)

**Key insight:** If implementation is in context when writing tests, AI writes tests that confirm the implementation — including its bugs. By writing tests FIRST from the spec only, tests become an independent correctness oracle.

**What this command does NOT do:**
- Does NOT replace /map-efficient — it augments the Actor/Monitor loop with test-first phases
- Does NOT work without a spec or plan — requires spec_<branch>.md or clear acceptance criteria

---

## Execution Flow

```
Standard:  DECOMPOSE → ACTOR (code+tests) → MONITOR
TDD:       DECOMPOSE → TEST_WRITER → TEST_FAIL_GATE → ACTOR (code only) → MONITOR
```

**Task:** $ARGUMENTS

---

## Step 0: Prerequisites

Verify that a plan or spec exists for this branch:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
echo "spec:        $(test -f .map/${BRANCH}/spec_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "task_plan:   $(test -f .map/${BRANCH}/task_plan_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "step_state:  $(test -f .map/${BRANCH}/step_state.json && echo EXISTS || echo MISSING)"
```

- If **no spec and no task_plan**: Run `/map-plan` first. TDD requires clear acceptance criteria.
- If **step_state.json EXISTS**: Resume from checkpoint (same as /map-efficient resume logic).
- If **task_plan EXISTS but no step_state**: Run `python3 .map/scripts/map_orchestrator.py resume_from_plan` then enable TDD mode.

### Enable TDD Mode

After state is initialized (either fresh or resumed):

```bash
python3 .map/scripts/map_orchestrator.py set_tdd_mode true
```

This inserts TEST_WRITER (2.25) and TEST_FAIL_GATE (2.26) phases before ACTOR (2.3) in the step sequence.

---

## Step 1: State Machine Loop

Follow the same state machine loop as /map-efficient. The orchestrator handles phase routing.
Call `get_next_step` and execute based on the returned phase.

```bash
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
```

Route to the appropriate executor based on `$PHASE`. All phases from /map-efficient work identically.
The two NEW phases are described below.

---

## Phase: TEST_WRITER (2.25)

Write tests ONLY — no implementation code. Tests are derived from the SPECIFICATION.

```python
Task(
  subagent_type="actor",
  description="TDD: Write tests for subtask [ID]",
  prompt=f"""You are in TDD TEST_WRITER mode.

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

<MAP_Contract>
[AAG contract from decomposition]
</MAP_Contract>

<TDD_Mode>test_writer</TDD_Mode>

STRICT RULES:
1. Write ONLY test files. Do NOT create or modify implementation files.
2. Tests must be derived from the SPECIFICATION (AAG contract + validation_criteria + test_strategy).
3. You have NO knowledge of the implementation. Do not assume implementation details.
4. Tests should assert BEHAVIOR described in the contract, not implementation structure.
5. Use standard test patterns for the project's language/framework.
6. Each validation_criteria item (VCn:) must have at least one corresponding test.
7. Include edge cases from the spec's Edge Cases section if available.

Output:
- Test files written via Edit/Write tools
- Evidence file: .map/<branch>/evidence/test_writer_<subtask_id>.json

Evidence JSON must include:
  "phase": "TEST_WRITER",
  "subtask_id": "<id>",
  "timestamp": "<ISO 8601>",
  "test_files_created": ["path/to/test_file.py"],
  "validation_criteria_covered": ["VC1", "VC2", "VC3"],
  "status": "applied"
"""
)
```

After TEST_WRITER returns:
```bash
python3 .map/scripts/map_orchestrator.py validate_step "2.25"
```

---

## Phase: TEST_FAIL_GATE (2.26)

Run the tests written by TEST_WRITER. They MUST fail (implementation doesn't exist yet).

```bash
# Run tests — expect failures
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')

if [ -f "pytest.ini" ] || [ -f "setup.py" ] || [ -f "pyproject.toml" ]; then
  TEST_OUTPUT=$(pytest --tb=short 2>&1) || true
elif [ -f "package.json" ]; then
  TEST_OUTPUT=$(npm test 2>&1) || true
elif [ -f "go.mod" ]; then
  TEST_OUTPUT=$(go test ./... 2>&1) || true
elif [ -f "Cargo.toml" ]; then
  TEST_OUTPUT=$(cargo test 2>&1) || true
else
  echo "WARNING: No test runner detected. Set TEST_OUTPUT manually for your project."
  TEST_OUTPUT="NO_TEST_RUNNER_FOUND"
fi
```

**Evaluate results:**

- **Tests FAIL with assertion/import errors** → GOOD. This is the expected TDD state ("Red" phase). Proceed to ACTOR.
- **Tests PASS** → PROBLEM. Tests are trivial or not testing real behavior. Go back to TEST_WRITER with feedback: "Tests pass without implementation. Tests must assert behavior that requires code to be written."
- **Tests have syntax errors** → Go back to TEST_WRITER with feedback to fix syntax.

Write evidence file:

```json
{
  "phase": "TEST_FAIL_GATE",
  "subtask_id": "<id>",
  "timestamp": "<ISO 8601>",
  "tests_ran": true,
  "tests_failed": true,
  "failure_type": "assertion_errors",
  "status": "gate_passed"
}
```

```bash
python3 .map/scripts/map_orchestrator.py validate_step "2.26"
```

---

## Phase: ACTOR in TDD Mode (2.3)

When TDD mode is active, Actor receives a modified prompt:

```python
Task(
  subagent_type="actor",
  description="TDD: Implement subtask [ID] to make tests green",
  prompt=f"""You are in TDD CODE_ONLY mode.

<MAP_Packet subtask="[ID]" v="1.0" risk="[risk_level]">
[paste from .map/<branch>/current_packet.xml]
</MAP_Packet>

<MAP_Contract>
[AAG contract from decomposition]
</MAP_Contract>

<TDD_Mode>code_only</TDD_Mode>

<TDD_Tests>
[List test files created by TEST_WRITER]
</TDD_Tests>

STRICT RULES:
1. Write ONLY implementation code. Do NOT modify test files.
2. Your goal: make ALL existing tests pass (turn Red → Green).
3. Read the test files first to understand what behavior is expected.
4. Implement the minimum code needed to satisfy the tests.
5. Follow the AAG contract as your specification.

Test files (READ-ONLY):
{test_files_list}

Output: standard Actor output (approach + code + trade-offs)
Evidence file: .map/<branch>/evidence/actor_<subtask_id>.json"""
)
```

After ACTOR, proceed to MONITOR as usual. Monitor verifies both implementation AND that tests pass.

---

## Differences from /map-efficient

| Aspect | /map-efficient | /map-tdd |
|--------|---------------|----------|
| Test authoring | Actor writes code + tests together | TEST_WRITER writes tests first, Actor writes code only |
| Test independence | Tests may mirror implementation | Tests derived from spec only |
| Phase count | 16 phases | 18 phases (+TEST_WRITER, +TEST_FAIL_GATE) |
| Token cost | Lower | ~20-30% higher (extra Actor call for tests) |
| Best for | General development | Correctness-critical features |

---

## When NOT to use /map-tdd

- Simple refactoring (no new behavior to test)
- Documentation-only changes
- Config/infrastructure changes without testable behavior
- When test framework doesn't exist and adding one is out of scope

---

## Related Commands

- **/map-plan** — Create spec with invariants and acceptance criteria (recommended before /map-tdd)
- **/map-efficient** — Standard workflow without test-first constraint
- **/map-check** — Final verification after all subtasks complete
- **/map-learn** — Extract lessons from completed TDD workflow
