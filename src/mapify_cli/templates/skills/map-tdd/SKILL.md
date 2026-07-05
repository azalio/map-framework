---
name: map-tdd
description: |
  TDD MAP workflow: write tests from the spec FIRST, then implement, so tests validate intent not implementation. Use when correctness is critical (auth, payments, data integrity). Do NOT use without a spec; use map-efficient instead.
effort: medium
disable-model-invocation: true
argument-hint: "[task description]"
---
# /map-tdd — Test-Driven Development Workflow

**Purpose:** Enforce test-first development where tests are written from the SPECIFICATION (not from implementation), ensuring tests validate intent rather than confirming implementation bugs.

**When to use:**
- Features where correctness is critical (auth, payments, data integrity)
- When you want tests that truly validate behavior, not mirror implementation
- When AI-written tests tend to pass trivially (testing what was written, not what was specified)

**Key insight:** If implementation is in context when writing tests, AI writes tests that confirm the implementation — including its bugs. By writing tests FIRST from the spec only, tests become an independent correctness oracle.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

When `tdd.enforce: true` is set in `.map/config.yaml`, this law is mandatory — not advisory. Code written before a failing test is **deleted**. Not refactored. Not adapted. Deleted. Start over.

### RED-GREEN-REFACTOR (mandatory cycle)

| Phase | Action | Verification |
|-------|--------|--------------|
| **RED** | Write a failing test | VERIFY it fails for the right reason — not import error, not typo |
| **GREEN** | Write minimal code to pass | VERIFY all tests pass |
| **REFACTOR** | Clean up | VERIFY tests still pass after each change |

Never skip the RED phase. A test that is "obviously going to fail" still needs a run to confirm it fails for the right reason.

### Red Flags (self-detection)

Stop immediately and restart if you notice any of these:
1. Writing implementation before running any test
2. "Just this once" — there are no exceptions
3. "This is different because..." — it is not different
4. "The test is obvious" — then it takes 30 seconds
5. "I'll add tests after" — you will not, or they will confirm bugs
6. "The spec is clear enough" — tests make it executable
7. "TDD slows me down" — you are paying for it later
8. "This is configuration, not code" — configuration breaks too
9. "I already know it works" — the test proves it
10. "I'll refactor into testability later" — now is later
11. Writing tests AFTER implementation and calling it TDD
12. Fixing tests to match buggy implementation
13. "There's no way to test this" — extract the testable core
14. Checking "tests pass" without checking they fail first

### Rationalization Table

| Rationalization | Counter |
|-----------------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll add tests after, I promise" | You won't. Or they'll confirm your bugs. |
| "Deleting N hours of work is wasteful" | Sunk cost fallacy. The waste was writing untested code. |
| "TDD is dogmatic" | TDD IS pragmatic — it forces a debuggable interface. |
| "I don't know how to test this yet" | That's a spec clarity problem. Clarify the spec first. |
| "The test would just mock everything" | Mock the boundary, not the behavior. Restructure. |
| "Tests slow down the deadline" | Debugging untested code slows it down more. |
| "The framework handles this" | Prove it with a test. |
| "I need to spike first" | Spikes are throwaway. Write the test on the real implementation. |
| "This is an integration concern" | Extract the unit. Integration tests come after unit tests. |
| "The existing codebase doesn't have tests" | You're adding tests now. One change at a time. |

**What this command does NOT do:**
- Does NOT replace /map-efficient — it augments the Actor/Monitor loop with test-first phases
- Does NOT work without a spec or plan — requires spec_<branch>.md or clear acceptance criteria

## Effort and Parallelism Policy

```yaml
thinking_policy: medium/adaptive
parallel_tool_policy: sequential_red_green_gate
```

- Spend reasoning on the behavior contract and the red/green boundary, not on implementation details during test authoring.
- Keep TEST_WRITER, TEST_FAIL_GATE, Actor, and Monitor sequential so tests remain an independent contract before implementation.
- Parallelize only independent artifact reads or read-only spec inspection before writing the test contract.

---

## Execution Flow

```
Non-TDD baseline:  DECOMPOSE → ACTOR (code+tests) → MONITOR   (= /map-efficient, shown for contrast — NOT a /map-tdd mode)
Targeted TDD:      DECOMPOSE → TEST_WRITER → TEST_FAIL_GATE → CONTRACT_HANDOFF → STOP
Targeted Resume:   /map-task ST-001 → ACTOR (code only) → MONITOR
Full-workflow TDD: DECOMPOSE → TEST_WRITER → TEST_FAIL_GATE → ACTOR (code only) → MONITOR
```

**Task:** $ARGUMENTS

---

## Step 0: Parse Arguments and Detect Mode

```bash
TASK_ARGS="$ARGUMENTS"
SUBTASK_ID=$(echo "$TASK_ARGS" | grep -oE 'ST-[0-9]+' | head -1)
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
```

**Two modes:**
- **Single-subtask mode** (`/map-tdd ST-001`): Write tests, persist a red-phase contract, then resume implementation separately
- **Full workflow mode** (`/map-tdd "task description"`): TDD for all subtasks

### Single-Subtask Mode (when `$SUBTASK_ID` is detected)

```bash
RESULT=$(python3 .map/scripts/map_orchestrator.py resume_single_subtask "$SUBTASK_ID" --tdd)
STATUS=$(echo "$RESULT" | jq -r '.status')

if [ "$STATUS" = "error" ]; then
  echo "$RESULT" | jq -r '.message'
  # If no plan: "Run /map-plan first"
  # If subtask not found: shows available IDs
  exit 1
fi
```

Then proceed directly to **Step 1: State Machine Loop** below. In single-subtask mode, the workflow should pause after `TEST_FAIL_GATE` once the persisted contract artifacts are written.

### Full Workflow Mode (no subtask ID)

Verify that a plan or spec exists for this branch:

```bash
echo "spec:        $(test -f .map/${BRANCH}/spec_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "task_plan:   $(test -f .map/${BRANCH}/task_plan_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "step_state:  $(test -f .map/${BRANCH}/step_state.json && echo EXISTS || echo MISSING)"
if [ -f ".map/${BRANCH}/step_state.json" ]; then
  echo "status:      $(python3 -c "import json; d=json.load(open('.map/${BRANCH}/step_state.json')); print(d.get('workflow_status', d.get('current_step_phase', 'UNKNOWN')))")"
fi
```

- If **no spec and no task_plan**: Run `/map-plan` first. TDD requires clear acceptance criteria.
- If **step_state.json EXISTS and status is COMPLETE or INITIALIZED**: Previous workflow finished or only plan exists. You MUST reinitialize for TDD by running `python3 .map/scripts/map_orchestrator.py resume_single_subtask "$SUBTASK_ID" --tdd` (single subtask) or `python3 .map/scripts/map_orchestrator.py resume_from_plan` then enable TDD mode (full workflow). Do NOT attempt edits without reinitializing — the workflow gate will block edits when current_step_phase is empty/INITIALIZED/COMPLETE.
- If **step_state.json EXISTS and status is IN_PROGRESS**: Resume from checkpoint (same as /map-efficient resume logic). Check `current_step_phase` — if empty, reinitialize with `resume_from_plan`.
- If **task_plan EXISTS but no step_state**: Run `python3 .map/scripts/map_orchestrator.py resume_from_plan` then enable TDD mode.

### Enable TDD Mode (full workflow only)

After state is initialized (either fresh or resumed):

```bash
python3 .map/scripts/map_orchestrator.py set_tdd_mode true
```

This inserts TEST_WRITER (2.25) and TEST_FAIL_GATE (2.26) phases before ACTOR (2.3) in the step sequence.

### Check tdd.enforce Configuration

```bash
TDD_ENFORCE=$(python3 -c "
import sys; sys.path.insert(0,'src')
try:
    from mapify_cli.config.project_config import load_map_config
    from pathlib import Path
    cfg = load_map_config(Path('.map/config.yaml'))
    print('true' if cfg.tdd_enforce else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo 'false')
```

When `TDD_ENFORCE=true`:
- The Iron Law applies: any code written before a failing test is **deleted**
- Spec compliance reviewer and code quality reviewer run after each ACTOR phase (mandatory)
- Monitor enforces the TDD violation check
- The rationalization table above is your reference — no excuse survives it

---

## Step 1: State Machine Loop

Follow the same state machine loop as /map-efficient. The orchestrator handles phase routing.
Call `get_next_step` and execute based on the returned phase.

```bash
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
PHASE=$(echo "$NEXT_STEP" | jq -r '.phase')
```

Route to the appropriate executor based on `$PHASE`. All phases from /map-efficient work identically.
The two TDD-specific phases are described below.

---

## Phase: TEST_WRITER (2.25)

Write tests ONLY — no implementation code. Tests are derived from the SPECIFICATION.

```python
Task(
  subagent_type="actor",
  description="TDD: Write tests for subtask [ID]",
  prompt=f"""You are in TDD TEST_WRITER mode.


<MAP_Contract>
[AAG contract from decomposition]
</MAP_Contract>

<TDD_Mode>test_writer</TDD_Mode>

Code-only rules:
1. Write ONLY test files. Do NOT create or modify implementation files.
2. Tests must be derived from the SPECIFICATION (AAG contract + validation_criteria + test_strategy).
3. You have NO knowledge of the implementation. Do not assume implementation details.
4. Tests should assert BEHAVIOR described in the contract, not implementation structure.
5. Use standard test patterns for the project's language/framework.
6. Each validation_criteria item (VCn:) must have at least one corresponding test.
7. Include edge cases from the spec's Edge Cases section if available.
8. Cover scenario dimensions from test_strategy: write tests for at minimum
   happy_path, error, edge_case, and security dimensions (use "N/A" if not applicable).
   Each dimension should have at least one dedicated test or test case.
9. Test files MUST be lint-clean. Use proper imports at the top of the file
   (not inside type annotations). Run the project linter (ruff/eslint/golangci-lint)
   on test files before finishing. Fix any lint errors in your test files.
10. Do NOT add temporal or state-marking comments about test failure status
   (e.g., "currently FAILS", "expected to FAIL until fix is applied",
   "will PASS once fix is implemented", "Red phase"). Write tests as permanent,
   clean code. The Red/Green state is transient — it must NOT leak into comments.

TEST QUALITY REQUIREMENTS — avoid "2+2=4" tests:
- Every test must verify SEMANTIC BEHAVIOR, not just that a single branch executes.
  Bad: "returns error when input is nil" (trivial nil-check).
  Good: "returns NotFound error and does NOT call downstream API when input is nil".
- Tests must assert MULTIPLE CONSEQUENCES of an action (side effects, return values,
  state changes, calls to dependencies). A test that asserts only one thing from
  a single if-branch is trivial — combine it with assertions about what else
  should or should NOT happen.
- Prefer scenario-based tests that exercise a CHAIN of behavior (setup → action →
  verify multiple outcomes) over unit-level tests that check one field.
- For each test ask: "Would this test catch a real bug, or does it just confirm
  the obvious?" If the answer is "obvious", merge it into a richer scenario or drop it.
- Aim for at least 60% of tests being full semantic scenarios (multi-step, multi-assert).

Output:
- Test files written via Edit/Write tools
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

**First: lint-check test files.** ACTOR cannot fix test files later, so they must be clean now.

```bash
# Lint-check ONLY the test files created by TEST_WRITER

if command -v ruff &> /dev/null; then
  LINT_OUTPUT=$(ruff check <test_files> 2>&1) || true
elif command -v eslint &> /dev/null; then
  LINT_OUTPUT=$(eslint <test_files> 2>&1) || true
elif command -v golangci-lint &> /dev/null; then
  LINT_OUTPUT=$(golangci-lint run <test_files> 2>&1) || true
fi
```

- **Lint errors found** → Go back to TEST_WRITER with feedback: "Fix lint errors in test files: <errors>. ACTOR cannot modify test files, so they must be lint-clean now."

**Then evaluate test results:**

- **Tests FAIL with assertion/import errors** → GOOD. This is the expected TDD state ("Red" phase). But also run the quality check below before proceeding.
- **Tests PASS** → PROBLEM. Tests are trivial or not testing real behavior. Go back to TEST_WRITER with feedback: "Tests pass without implementation. Tests must assert behavior that requires code to be written."
- **Tests have syntax errors** → Go back to TEST_WRITER with feedback to fix syntax.

**Quality gate (run even if tests correctly fail):**

Review the test files and classify each test as:
- **Semantic** — tests real behavior with multi-step scenario or multi-assert verification
- **Trivial ("2+2=4")** — tests a single if-branch or obvious nil-check with one assert

If more than 40% of tests are trivial, go back to TEST_WRITER with feedback:
"Too many trivial tests. [N] of [M] tests are single-branch checks. Merge trivial
tests into richer scenarios that verify multiple consequences. Each test should catch
a real bug, not just confirm one obvious branch."

```bash
python3 .map/scripts/map_orchestrator.py validate_step "2.26"
```

**Single-subtask mode only: persist the red-phase contract before any implementation starts.**

When `$SUBTASK_ID` is non-empty, write `.map/${BRANCH}/test_contract_${SUBTASK_ID}.md` with:
- the subtask ID and title
- the AAG contract
- the test files created by TEST_WRITER
- the failing test command
- the behavior locked by the tests
- any constraints ACTOR must preserve

Then record the machine-readable handoff and stop this session:

```bash
python3 .map/scripts/map_step_runner.py record_test_contract_handoff "$SUBTASK_ID" "<failing test command>" "<comma-separated test files>" "<one-sentence contract summary>" "<optional notes>"
python3 .map/scripts/map_orchestrator.py mark_contract_ready "$SUBTASK_ID"
```

After that, STOP and tell the user to resume implementation with:

```text
/map-task ST-001
```

That follow-up command will detect `test_handoff_${SUBTASK_ID}.json` and resume at `ACTOR` with the persisted contract, instead of re-running research or test writing.

When `$SUBTASK_ID` is empty (full-workflow mode), do **not** write `test_contract_.md`, do **not** call `mark_contract_ready ""`, and do **not** stop the workflow here. In full-workflow mode, `TEST_FAIL_GATE` continues directly into `ACTOR` for the current subtask.

---

## Phase: ACTOR in TDD Mode (2.3)

When implementation resumes from the persisted TDD contract, Actor receives a modified prompt:

```python
Task(
  subagent_type="actor",
  description="TDD: Implement subtask [ID] to make tests green",
  prompt=f"""You are in TDD CODE_ONLY mode.

<MAP_Contract>
[AAG contract from decomposition]
</MAP_Contract>

<TDD_Mode>code_only</TDD_Mode>

<TDD_Tests>
{test_files_list}
</TDD_Tests>

STRICT RULES:
1. Write ONLY implementation code. Do NOT modify test files (the files in <TDD_Tests> are READ-ONLY).
2. Your goal: make ALL existing tests pass (turn Red → Green).
3. Read the test files first to understand what behavior is expected.
4. Implement the minimum code needed to satisfy the tests.
5. Follow the AAG contract as your specification.

Output: standard Actor output (approach + code + trade-offs)
"""
)
```

After Actor returns, run the spec compliance reviewer and code quality reviewer (if `tdd.enforce: true`), then run the TDD Refactor step, then call Monitor (2.4).

### Spec Compliance Reviewer (adversarial, MANDATORY when tdd.enforce=true)

Spawn this BEFORE code quality review. The two reviews cannot be swapped.

**Adversarial framing:** The implementer finished suspiciously quickly. Do NOT trust the Actor summary. Read the actual code.

```python
Task(
  subagent_type="actor",
  description="Spec compliance review: subtask [ID]",
  prompt=f"""You are an adversarial spec compliance reviewer.

You have been told the implementer finished subtask [ID]. Do NOT trust their summary.
Read the actual code diff. Compare every requirement in the spec to the actual diff.

<subtask_spec>
[paste AAG contract + validation_criteria from decomposition]
</subtask_spec>

<actual_diff>
[paste git diff for this subtask]
</actual_diff>

Check EVERY requirement:
1. Is each requirement implemented? Show file:line evidence.
2. Is there extra work not in the spec? (Scope creep, gold-plating)
3. Are there misunderstandings? (Implemented the wrong thing)
4. Are all edge cases from the spec covered?

Output:
- SPEC-COMPLIANT: YES or NO
- If NO: list each gap with exact file:line reference and the spec line it violates
"""
)
```

**Gate**: If the reviewer returns `SPEC-COMPLIANT: NO`, route back to ACTOR with the specific gaps listed. Do NOT proceed to code quality review until spec passes.

### Code Quality Reviewer (runs ONLY after spec reviewer passes)

```python
Task(
  subagent_type="actor",
  description="Code quality review: subtask [ID]",
  prompt=f"""You are a code quality reviewer. Spec compliance is already verified.

Review the implementation quality only.

<actual_diff>
[paste git diff for this subtask]
</actual_diff>

Check:
1. **File responsibility**: Does each file do one thing?
2. **Unit decomposition**: Are functions small and independently testable?
3. **Plan conformance**: Does structure match the architectural plan?
4. **Size discipline**: No functions > 40 lines without documented justification
5. **Error handling**: All error paths handled explicitly
6. **Type safety**: No untyped `Any` without justification
7. **Naming**: Names describe behavior, not structure

Output:
**Strengths**: (what is done well — be specific)
**Issues**:
- CRITICAL: [blocks proceeding — must fix before Monitor]
- IMPORTANT: [should fix in this subtask]
- MINOR: [acceptable to defer]
**Assessment**: PASS | PASS_WITH_MINOR | FAIL
"""
)
```

**Sequential gate**: Spec compliance review MUST complete with `SPEC-COMPLIANT: YES` before code quality review starts. Running them in parallel bypasses the gate.

If code quality review returns `FAIL` (CRITICAL issues), route back to ACTOR. Once it returns `PASS` or `PASS_WITH_MINOR`, proceed to TDD Refactor and then Monitor.

### TDD Refactor: Clean Stale Red-Phase Comments

After ACTOR completes and tests pass (Green), scan the test files created by TEST_WRITER for stale Red-phase markers. This is the **Refactor** step of Red-Green-Refactor.

Look for and clean up:
- Comments containing "currently FAILS", "expected to FAIL", "will PASS once", "Red phase", "TDD Red"
- File-level docstrings saying tests "are expected to fail against current implementation"
- Any temporal language that references the transient Red/Green state

Rewrite matched comments as permanent, implementation-neutral descriptions. If a comment is only a state marker with no semantic value, remove it entirely.

**This cleanup is done by the orchestrating agent (you), NOT by Actor.** Actor in code_only mode cannot modify test files, but you can.

```bash
# Validate Actor step, then get_next_step will return MONITOR (2.4)
python3 .map/scripts/map_orchestrator.py validate_step "2.3"
NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
# NEXT_STEP.phase should be "MONITOR" — execute it before proceeding
```

Monitor verifies both implementation correctness AND that all tests pass.

---

## Differences from /map-efficient

| Aspect | /map-efficient | /map-tdd |
|--------|---------------|----------|
| Test authoring | Actor writes code + tests together | TEST_WRITER writes tests first, Actor writes code only |
| Test independence | Tests may mirror implementation | Tests derived from spec only |
| Phase count | 6 phases | 8 phases (+TEST_WRITER, +TEST_FAIL_GATE) |
| Token cost | Lower | ~20-30% higher (extra Actor call for tests) |
| Best for | General development | Correctness-critical features |

## Artifact Model

`/map-tdd` uses the same branch-scoped execution artifacts as `/map-efficient` because it runs through the same orchestrated state machine with extra TDD phases:

- `code-review-00N.md`
- `qa-001.md`
- `pr-draft.md`
- `test_contract_ST-00N.md`
- `test_handoff_ST-00N.json`

In TDD mode, `TEST_WRITER` and `TEST_FAIL_GATE` still write into the same branch workspace, but they must now leave behind a persisted contract that `/map-task` can resume from in a clean implementation session.

---

## When NOT to use /map-tdd

- Simple refactoring (no new behavior to test)
- Documentation-only changes
- Config/infrastructure changes without testable behavior
- When test framework doesn't exist and adding one is out of scope

---

## Related Commands

- **/map-plan** — Create spec with invariants and acceptance criteria (recommended before /map-tdd)
- **/map-task ST-001** — Resume implementation from a persisted TDD contract or execute a normal single subtask
- **/map-efficient** — Standard workflow without test-first constraint
- **/map-check** — Final verification after all subtasks complete
- **/map-learn** — Extract lessons from completed TDD workflow


## Examples

```
/map-tdd ST-003                         # write spec-derived tests for one planned subtask, then stop
/map-tdd add idempotency keys to the payment capture endpoint
```

## Troubleshooting

- **Issue:** Invoked without a spec or acceptance criteria. **Fix:** Run `/map-plan` first, or use `/map-efficient` (see "What this command does NOT do").
- **Issue:** Tests pass trivially / mirror the implementation. **Fix:** Ensure TEST_WRITER derives tests from the spec only, before any implementation is in context (see "Key insight").
- **Issue:** The session was interrupted between the red-phase contract and implementation. **Fix:** Resume with `/map-task ST-00N`.
