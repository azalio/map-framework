---
name: map-plan
description: "ARCHITECT phase - decompose complex tasks into atomic subtasks with research, spec, and branch-scoped plan artifacts under .map."
---

# map-plan — ARCHITECT Phase (Decomposition Only)

**Purpose:** Plan and decompose complex tasks into atomic subtasks. This skill ONLY plans — it does NOT execute or verify.

**When to use:**
- Starting a new feature, refactoring, or complex bug fix
- Need to break work into manageable pieces with clear task boundaries

**Produces:**
- `.map/<branch>/research/plan__discovery.md` — plan-scope discovery notes (legacy `.map/<branch>/findings_<branch>.md` is read only as a compatibility fallback)
- `.map/<branch>/spec_<branch>.md` — spec with decisions, invariants, ACs
- `.map/<branch>/blueprint.json` — raw decomposer output (required by map-efficient)
- `.map/<branch>/task_plan_<branch>.md` — human-readable plan with AAG contracts
- `.map/<branch>/step_state.json` — initialized workflow state

**Related skills:** `$map-efficient` (execute approved plans), `$map-fast` (small changes), `$map-check` (post-execution verification)

---

## Pre-flight: Mode Detection

Read `$ARGUMENTS` for mode flags **before any other action**. Strip detected flags from `$ARGUMENTS` before using the remainder as the task description.

| Flag | Mode | Effect |
|------|------|--------|
| `--light` | LIGHT | Spec-only, no research. **Skip** Step 0, Step 0.5 (Already-Implemented Gate), and Step 2b (Devil's Advocate Review). Limit decomposition to 2–5 minimal subtasks. Fastest plan mode — use when scope is small and well-understood. |
| `--deep` | DEEP | Full research + architecture review. Add extended research sweep **before** Step 0 and an architecture review step **after** Step 3. Use when scope is large or risk is high. |
| `--force-full` | DEEP alias | Identical to `--deep`. Overrides any scale auto-advisory toward maximum planning depth. |
| `--force-fast` | FAST exit | Recommend `$map-fast` and STOP. Use when the task is clearly trivial and MAP planning overhead is not warranted. |

If **no flag** is present (standard mode), run all steps as written. The Scale Advisory in the Workflow-Fit Gate may suggest a mode when scope is clear from the task description.

---

## Pre-flight: Resume Detection

Before any step, detect which artifacts already exist AND whether the request matches the existing plan's goal:

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    echo "BRANCH=$BRANCH"
    python3 .map/scripts/map_step_runner.py check_plan_resume "$ARGUMENTS"
```

This reports the existing artifacts (`plan__discovery` or legacy `findings`/`spec`/`task_plan`/`step_state`) AND a `verdict` comparing the prior plan's goal against the current request — so a branch that already hosts a *completed* plan for a different goal is not mistaken for "this plan is done" (a single branch can host several sequential plans over its lifetime).

**Branch on `verdict`:**
- `no_plan` → no prior artifacts; plan fresh from Step 0
- `goal_mismatch` → the branch already holds a plan for a **different** goal. Do **NOT** print "plan complete" and do **NOT** overwrite the prior `spec`/`blueprint`/`task_plan`. Follow the `recommendation`: archive or rename the existing `.map/<branch>/` artifacts (or run `$map-plan` on a fresh branch) — confirm with the operator first — then plan the new goal
- `resume` → the request matches the existing plan (or no request text was supplied to compare); apply the per-artifact resume rules below

**Per-artifact resume rules (only when `verdict` is `resume`):**
- plan discovery EXISTS → prefer `.map/<branch>/research/plan__discovery.md`. If only legacy `.map/<branch>/findings_<branch>.md` exists, read it as a compatibility fallback and migrate it with `save_research "$BRANCH" plan discovery` ONLY if the file has an `Already Implemented` section; if it predates that format, re-run Step 0 so the Step 0.5 gate has its evidence
- `spec` EXISTS → skip Steps 1-2, read existing spec
- `task_plan` EXISTS → skip Steps 4-6, read existing plan
- `step_state.json` EXISTS → plan is complete, print checkpoint and STOP

---

## Pre-flight: Workflow-Fit Gate

Assess whether MAP planning is warranted. Evaluate these signals:

- `expected_diff_size`: tiny / small / medium / large
- `has_new_invariants`: introduces/changes domain contracts or schema rules?
- `needs_independent_review`: risky enough to require review?
- `has_clear_acceptance_criteria`: can be executed without a planning pass?
- `test_first_required`: TDD warranted because behavior contract matters?
- `depends_on_runtime_state`: does correctness depend on **current production/runtime state** (applied migration head, a table/column/index/enum value present in the live DB, current row counts / backfill volume, the actual value of a feature flag or config, runtime capacity/traffic)? Ask the operator when unsure — **if unsure, true.** False for refactors, tests, docs, static-config; "code will run in prod" is not runtime-dependence. When true, Step 0.6 runs.

Pick one outcome:
- `direct-edit` — tiny, isolated, clear acceptance criteria, no new invariants
- `map-fast` — small bounded change where MAP overhead is not justified
- `map-plan` — non-trivial; needs SPEC + PLAN before execution

Record the decision:

```
shell_command:
  cmd: |
    python3 .map/scripts/map_step_runner.py record_workflow_fit \
      "<direct-edit|map-fast|map-plan>" \
      --diff-size "<tiny|small|medium|large>" \
      --has-new-invariants <0|1> --needs-independent-review <0|1> \
      --has-clear-acceptance-criteria <0|1> --test-first-required <0|1> \
      --depends-on-runtime-state <0|1> \
      --summary "<one-sentence decision summary>"
```

- Outcome `direct-edit`: print off-ramp explanation and STOP.
- Outcome `map-fast`: recommend `$map-fast` and STOP.
- Outcome `map-plan`: continue below.

**Scale Advisory (standard mode only, when no `--light`/`--deep` flag was given):** After recording a `map-plan` outcome, estimate the task scope and run:

```
shell_command:
  cmd: python3 .map/scripts/classify_scope.py --files ESTIMATED_FILES --lines ESTIMATED_LINES
```

If `auto_enabled: true` in the JSON result, surface an advisory based on `bracket` (do not block):
- `small` → advise re-invoking as `$map-plan --light`.
- `large` → advise re-invoking as `$map-plan --deep`.
- `trivial` → advise `$map-fast` instead.
- `medium` → no advisory; standard mode is appropriate.

---

## Step 0: Quick Discovery (Optional but Recommended; SKIP in LIGHT mode)

**LIGHT mode:** Skip this step entirely — proceed directly to Step 1. The spec is written from stated requirements without a prior research phase.

**DEEP mode:** Before this step, run an extended research sweep (full codebase exploration, dependency and hotspot analysis). Dispatch a researcher with a wider scope than the standard Step 0 prompt below; cover recent-change hotspots, dependency graph, existing test coverage gaps, and architectural friction points. Save findings to `.map/$BRANCH/research/plan__deep_discovery.md` in addition to the standard `plan__discovery.md`.

Skip if `.map/<branch>/research/plan__discovery.md` already exists AND contains an `Already Implemented` section (resume rule above), or if the task is greenfield with a fully-provided spec. If the canonical file is absent but legacy `.map/<branch>/findings_<branch>.md` exists, read it as a fallback and migrate it to the canonical research path only if it has the required section. If an existing discovery file predates this format (no `Already Implemented` section), re-run discovery so the Step 0.5 gate has its evidence.

```
spawn_agent(
  agent_type="researcher",
  message="""Locate the most relevant code for this request and return:
- 5-15 key file paths (1-line reason each)
- existing similar implementations and patterns to follow
- risks, unknowns, and integration points
- which parts of the request are ALREADY IMPLEMENTED vs genuinely missing

For EVERY file path:
1. Use find/rg to verify it actually exists
2. If the spec says "create new file X" — confirm X is absent
3. Mark each path as EXISTING (verified) or NEW (confirmed not found)
4. For existing files: approximate LOC and key symbols

For the request itself: search for an existing implementation BEFORE
reporting a behavior as missing. For each asked-for behavior/acceptance
criterion, decide if it is already implemented and cite `file:line` proof.

User request:
<paste user_requirements here>

Output format:
## Already Implemented
- "<feature part>" -> `path/to/file.py:NN` — proof (or: "none found (searched: <queries>)")

## Existing Files (verified)
- `path/to/file.py` (NNN LOC) — ClassX, relevant because...

## Files to Create (confirmed absent)
- `path/to/new.py` — needed for...

## Patterns Found
- ...

## Risks / Unknowns
- ...
"""
)
```

Save discovery to the canonical research namespace:

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    python3 .map/scripts/map_step_runner.py save_research "$BRANCH" plan discovery << 'DISCOVERY_EOF'
<paste researcher output here>
DISCOVERY_EOF
```

---

## Step 0.5: Already-Implemented Gate (MANDATORY when discovery ran; SKIP in LIGHT mode)

> **LIGHT mode:** Skip this step — no discovery was run, so there is no evidence base for the gate. Surface any overlap during spec writing.

Reconcile the request against the discovery `Already Implemented` section BEFORE interview/spec. Do not plan work the codebase already does. If discovery was skipped (greenfield or fully-provided spec), state the gate was skipped and why. If the findings file lacks an `Already Implemented` section (it predates this format), re-run Step 0 first — do NOT run the gate on incomplete evidence.

- **Whole feature already implemented** — every asked-for behavior exists with `file:line` proof. Off-ramp: report the evidence, state no plan is needed, and STOP (no spec, no blueprint). If the user may want changes, ask them to restate the specific gap.
- **Partially implemented** — move already-done parts into the spec's **Out of Scope > Already Implemented** subsection (with `file:line` proof) so decomposition plans ONLY the remaining gap. Re-scope to the gap before continuing.
- **Not implemented** — nothing matching exists; continue normally.

When unsure whether existing code truly satisfies the request, treat it as partial and surface it in the interview / Open Questions — never silently re-plan code that already exists.

---

## Step 0.6: Verify Live/Runtime State Gate (MANDATORY when `depends_on_runtime_state=true`)

The runtime analogue of Step 0.5. Step 0.5 stops you re-planning code that already exists; Step 0.6 stops you planning against **runtime facts that have drifted** from the design docs / memory the plan copied them from. Skip only when `depends_on_runtime_state=false`.

Static discovery reads only the repo — it cannot see prod row counts, the enum labels actually present in a live DB, a column that already exists, the applied migration head, or a live feature-flag value. **Caution:** code can exist in the repo (Step 0.5 `file:line` proof) while its migration / feature flag is NOT yet applied in prod; verify runtime separately.

Signals that arm the gate: a DB migration / data backfill; "measured on prod" / "currently" / "as of" numbers in the source; count-based acceptance criteria referencing current state ("migrate the 10k existing rows"), not a forward target ("1k RPS"); a feature-flag / config cutover; capacity / latency assumptions; "this column/table/enum value already exists".

For each assumption the plan's correctness rests on:
- **Verifiable read-only now** — confirm via an approved read-only source (read replica, dashboard, runbook, `INFORMATION_SCHEMA` / `pg_enum` / migration-head introspection). Record the **fact** + source, not the raw rows.
- **Prod unreachable / unchecked** — record an `Unverified Runtime Assumption` under spec Open Questions / Risks with the **exact read-only check** + safe source, and mark dependent subtasks `provisional`. Do NOT bake the assumption in as fact.

Safety: this skill is a planning-time gate, NOT a runtime tool — it suggests checks, it does not run them (defer to the operator or an authorized sub-agent). Prefer bounded / metadata queries over full scans / `COUNT(*)`; never write, mutate, or flip flags; never paste PII, secrets, or bulky prod output into the spec or `.map/<branch>/` artifacts (they may be committed); no isolation-level / `NOLOCK` hints. Do not hard-stop merely because prod is unreachable — record-the-check is the contract. If a runtime dependency surfaces later during decomposition, loop back and verify-or-record it.

---

## Step 1: Assess Scope and Decide Interview Depth

Read the user's requirements and decide if a deep interview is needed.

**Interview REQUIRED when:**
- 2+ features in one request
- Vague product idea without clear technical approach
- New project (stack + features undefined)
- Batch of bugs/issues to fix together
- Obvious gaps or unstated assumptions in requirements

**Interview SKIPPED when:**
- Task is well-defined with clear acceptance criteria
- Small isolated change (single bug fix, test update)
- User explicitly provided a spec or detailed description

If skipping, go directly to Step 2a (write spec without interview).

---

## Step 2: Deep Interview (Spec Discovery)

Ask the user non-obvious questions to surface decisions and tradeoffs BEFORE planning. Use plain text questions. If the runtime supports `request_user_input`, use it; otherwise print questions and wait for answers.

**Rules:**
- Questions must be NON-OBVIOUS (do not re-ask what the user already stated)
- Ask in small rounds: 1-2 high-signal questions, up to 4 if needed
- Continue until all critical architectural decisions are captured

**Interview dimensions:**
1. **Technical:** Stack choices, data model, API contracts, state management
2. **UX:** User flows, error states, edge cases
3. **Tradeoffs:** Performance vs simplicity, flexibility vs speed, build vs buy
4. **Risks:** What can break? Blast radius? Rollback strategy?
5. **Scope:** What is explicitly OUT of scope?
6. **Integration:** Existing code interactions? Migration needed?
7. **Contract Clarity:** Every goal stated as a verifiable outcome (not process)

Example plain-text interview round:

```
Questions for this task:

1. [Token store] Should refresh tokens be stored server-side (Redis/DB — revocable,
   adds infra) or stateless JWT (no infra, harder to revoke)?

2. [Session UX] When a session expires mid-action, should the app: silent refresh
   in background / show a re-login modal preserving form state / redirect to login?

Please answer both before I proceed.
```

After answers are collected, write the spec:

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    mkdir -p .map/${BRANCH}
    cat > .map/${BRANCH}/spec_${BRANCH}.md << 'SPEC_EOF'
# Spec: [Title]

**Date:** $(date -u +%Y-%m-%d)
**Branch:** ${BRANCH}

## Decisions Made

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | [question] | [decision] | [rationale] |

## Invariants

Hard constraints — violating any invariant is a blocker.

- [e.g., "All API endpoints require auth except /health and /login"]

## Constraints

```yaml
constraints:
  max_files: null
  max_subtasks: null
  scope_glob: null
```

## Edge Cases

| # | Edge Case | Expected Behavior | Priority |
|---|-----------|-------------------|----------|
| 1 | [case] | [behavior] | must-handle |

Priority: must-handle / should-handle / won't-handle

## Acceptance Criteria

| ID | Criterion | Verification Method |
|----|-----------|-------------------|
| AC-1 | [criterion] | [test command or manual check] |

## Security Boundaries

*(Include for security-critical tasks; omit for cosmetic/internal changes)*

- Trust boundary: [...]
- Auth model: [...]

## Out of Scope

- [explicitly excluded items]

### Already Implemented

- ["<feature part>" -> `file:line` proof] — decomposer must NOT create subtasks for these (Step 0.5 gate)

## Open Questions

- [anything unresolved]
SPEC_EOF
```

**Requirements Index (MANDATORY):** After writing the spec, populate the `mapify:requirements-index:v1` sentinel-wrapped fenced YAML block (defined in the spec template) with exactly ONE `{id, kind}` entry per acceptance criterion, invariant, hard constraint, and cross-cutting requirement. `kind` must be one of `acceptance_criterion | invariant | hard_constraint | cross_cutting`. IDs must be canonical: prefix in `{AC, INV, HC, CCR}`, no leading zeros, uppercase (e.g. `AC-1`, `INV-2`, `HC-3`). These IDs are **exactly** the keys the decomposer must map in `coverage_map` — the forward-completeness gate diffs the index IDs against `coverage_map` keys to detect uncovered requirements.

---

## Step 2a: Write Spec (interview skipped)

If interview was skipped, still write `spec_<branch>.md` using the same template.
Populate from user requirements and discovery findings:

- **Decisions Made:** extract from user's request (may be short or N/A)
- **Invariants:** derive from existing code patterns found in discovery
- **Acceptance Criteria:** REQUIRED — must be testable, define "done"
- **Edge Cases:** from task description and affected code

**Completeness rule:** If the source defines explicit ACs, enumerate ALL of them — do NOT summarize N criteria as "key M". Every AC that is not listed will be silently dropped by the decomposer.

**Requirements Index (MANDATORY):** Same as above — populate the `mapify:requirements-index:v1` sentinel block with one `{id, kind}` entry per AC/INV/HC/CCR. IDs are the exact `coverage_map` keys the decomposer must map.

---

## Step 2b: Devil's Advocate Review (SPEC_REVIEW; always SKIP in LIGHT mode)

> **LIGHT mode:** Skip this step unconditionally.

**Skip if ALL true (standard/DEEP mode):**
- Source spec is under 200 lines
- Fewer than 5 subtasks expected
- No cross-cutting concerns (observability, security, concurrency, multi-service)

**ALWAYS run if ANY true:**
- Source spec exceeds 500 lines
- 10+ acceptance criteria defined
- Multiple services, subgraphs, or subsystems involved
- Task includes concurrency, recovery, or multi-transport requirements

```
spawn_agent(
  agent_type="monitor",
  message="""You are reviewing a SPECIFICATION (not code). Act as Devil's Advocate.

Read the spec at: .map/<branch>/spec_<branch>.md
(Use shell_command to cat the file.)

Check for:
1. Race conditions / concurrency gaps — shared resources without defined conflict resolution?
2. Ownership ambiguity — could two components both assume the other handles something?
3. Missing edge cases — invariant violations not covered by the Edge Cases section?
4. Contradictions — decisions that contradict invariants or acceptance criteria?
5. Security gaps — incomplete trust boundaries or unaddressed injection vectors?
6. Implicit assumptions — things assumed but not stated?

Output format (for each finding):
  SEVERITY: HIGH | MEDIUM | LOW
  CATEGORY: [concurrency|ownership|edge-case|contradiction|security|assumption]
  DESCRIPTION: [what the issue is]
  SUGGESTED FIX: [how to resolve]

If no HIGH-severity issues: output exactly "SPEC APPROVED" at the end.
If HIGH-severity issues exist: list them clearly — do not output "SPEC APPROVED".
"""
)
```

**After Devil's Advocate review:**
- `SPEC APPROVED` (no HIGH findings): proceed to Step 3.
- HIGH findings found: present them to the user in plain text and wait for resolution. Update the spec before proceeding. Do NOT silently proceed past HIGH findings.
- MEDIUM/LOW findings: add to spec's Open Questions section and proceed.

---

## Step 3: Create Branch Directory

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    mkdir -p .map/${BRANCH}
    echo "Working directory: .map/${BRANCH}"
```

If multiple valid designs exist and the user did not specify an approach, propose 2-3 options with tradeoffs and get confirmation before decomposition.

**Architecture Graph (REQUIRED for complexity >= 3):** Append to `spec_<branch>.md` before calling the decomposer:

```
## Architecture Graph

ComponentA -[calls]-> ComponentB -[has_many]-> ComponentC
api/routes/foo.py -[uses]-> FooService
GET /foo -[filters_by]-> archived_at
```

Format: `A -[relationship]-> B` (arrow notation). Keep under 200 tokens — only nodes touched by the feature. Relationships: has_many, has_one, calls, extends, uses, creates.

---

## Step 3.5: Architecture Review (DEEP mode only)

> **Standard / LIGHT mode:** Skip this step.

Before decomposition, dispatch a monitor agent to review the spec and discovery findings for architecture concerns: component boundary clarity, dependency direction violations, state ownership ambiguity, untestable seams, and conflicts with `docs/ARCHITECTURE.md`.

```
spawn_agent(
  agent_type="monitor",
  message="""You are reviewing a SPECIFICATION for architecture quality (not code). DEEP mode.

Read the spec at: .map/<branch>/spec_<branch>.md
Read deep discovery at: .map/<branch>/research/plan__deep_discovery.md (if present)
(Use shell_command to cat both files.)

Check for:
1. Component boundary clarity — are module/service responsibilities well-defined and non-overlapping?
2. Dependency direction — does the proposed flow violate layering or create circular dependencies?
3. State ownership — is shared mutable state owned by exactly one component?
4. Untestable seams — are there coupling points that make unit testing impractical?
5. Architecture conflicts — does this design contradict decisions in docs/ARCHITECTURE.md?

Output per finding:
  SEVERITY: CRITICAL | HIGH | MEDIUM
  CATEGORY: [boundary|dependency|state|testability|architecture-conflict]
  DESCRIPTION: [what the issue is, citing the spec section]
  RECOMMENDATION: [how to resolve]

If no CRITICAL or HIGH findings: output "ARCHITECTURE APPROVED" at the end.
"""
)
```

- `ARCHITECTURE APPROVED` (no CRITICAL/HIGH findings): proceed to Step 4.
- CRITICAL or HIGH findings: present them and update the spec before decomposition.
- Add unresolved risks to spec Open Questions.

---

## Step 4: Call Task Decomposer

```
spawn_agent(
  agent_type="decomposer",
  message="""Break down this task into atomic, testable subtasks.

USER REQUEST:
<paste user_requirements here>

SPEC FILE: .map/<branch>/spec_<branch>.md
(Cat the file with shell_command to read it.)

DISCOVERY: .map/<branch>/research/plan__discovery.md (or legacy .map/<branch>/findings_<branch>.md fallback if it exists and has not yet been migrated)

Output requirements per subtask:
- id: ST-NNN
- title: <imperative title>
- aag_contract: "Actor -> Action(params) -> Goal"  [REQUIRED for every subtask]
- description: what needs to be done
- affected_files: [list of file paths]
- dependencies: [] or [ST-NNN, ...]
- complexity_score: 1-10
- risk_level: low | medium | high
- expected_diff_size: tiny | small | medium | large
- concern_type: api | config | data | docs | infra | observability | refactor | release | runtime | security | tests | ui | mixed
- one_logical_step: true
- split_rationale: required when expected_diff_size is large, otherwise omit
- concern_justification: required when concern_type is mixed, otherwise omit
- validation_criteria: ["VC1 [AC-1]: ...", "VC2 [INV-1]: ..."]
- test_strategy: {unit: [...], integration: [...]}
- hard_constraints: [{id: "HC-1", description: "non-negotiable requirement"}]
- soft_constraints: [{id: "SC-1", description: "preference", tradeoff_rationale: "if not covered"}]

Target subtask size: completable within ~4000 tokens (SFT comfort zone).
Aim for 3-7 subtasks; flag if more than 10 are needed.
LIGHT mode: target 2-5 minimal bite-sized subtasks; prefer merging related concerns over splitting.

Coverage requirements:
- Do NOT create subtasks for behavior listed under the spec's "Out of Scope > Already Implemented" subsection — that work already exists. Plan only the remaining gap.
- Every spec AC must appear as a validation_criteria in exactly one subtask.
- Every validation_criteria item that proves a mapped requirement must cite the matching coverage_map key in brackets, e.g. `VC1 [AC-1]: ...`.
- Every hard_constraints id must appear in coverage_map and as a matching validation_criteria bracket tag.
- Every soft_constraints id must either appear in coverage_map or include tradeoff_rationale explaining the tradeoff.
- For cross-cutting requirements (observability, error handling, structured logging,
  budget tracking), create a dedicated subtask or add them as validation_criteria
  to the subtask that implements the relevant infrastructure.
- For each structured result type, ALL fields (including optional envelope fields
  like budget_state, deferred_work, recovery_state) must be in validation_criteria.
- Output a coverage_map field for every acceptance criterion, invariant, and cross-cutting requirement: {"AC-1": "ST-NNN", "AC-2": "ST-MMM", ...}

Return structured JSON:
{
  "summary": "<goal description>",
  "hard_constraints": [{"id": "HC-1", "description": "Non-negotiable requirement"}],
  "soft_constraints": [{"id": "SC-1", "description": "Preference", "tradeoff_rationale": "Only if not covered"}],
  "coverage_map": {"HC-1": "ST-001", "AC-1": "ST-001"},
  "subtasks": [{"id": "ST-001", "validation_criteria": ["VC1 [HC-1] [AC-1]: ..."]}]
}
"""
)
```

---

## Step 5: Save Blueprint JSON

Save the decomposer output as `.map/<branch>/blueprint.json`. This file is required by `$map-efficient` for parallel wave computation.

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    cat > .map/${BRANCH}/blueprint.json << 'BLUEPRINT_EOF'
<paste decomposer JSON output here>
BLUEPRINT_EOF
    echo "Saved blueprint.json"
```

If the decomposer returned markdown instead of JSON, construct the JSON from the subtask list. This step is mandatory — without `blueprint.json`, `$map-efficient` cannot compute parallel execution waves.

If `blueprint.json` already exists and only needs a partial update, use `apply_patch` instead of a full heredoc rewrite to avoid clobbering unchanged fields.

---

## Step 5.2: Post-Save Blueprint Validation (MANDATORY)

After writing `blueprint.json`, run this deterministic check. If it reports an
invalid blueprint, re-run Step 4 (the decomposer) BEFORE proceeding to Step 5.5.

```
shell_command:
  cmd: |
    python3 .map/scripts/map_step_runner.py validate_blueprint_contract
```

If the validator exits non-zero, return to Step 4 with the exact JSON `errors`
and `warnings`. Ask the decomposer to fix the oversized, mixed-concern,
untraceable, or malformed subtasks. After the second decomposer run, re-save
`blueprint.json` and re-run this validator. Two consecutive failures = STOP
and report the validator errors to the user.

---

## Step 5.5: Decomposition Coverage Check

Before writing the human-readable plan, verify coverage. The decomposer may silently drop requirements.

**1. AC mapping:** For each spec AC, identify which ST-NNN covers it. If an AC has no owner, add it to an existing subtask's validation_criteria or create a new subtask.

**2. Result schema check:** For each structured result type in the spec, verify ALL fields appear in at least one subtask's validation_criteria.

**3. Cross-cutting concerns scan:** Confirm these have an explicit owner:
- Observability / structured logging
- Error codes and structured error types
- Concurrency / locking
- Budget tracking and exhaustion
- Recovery state for write-capable workflows

**4. Invariant coverage:** Each spec invariant must have at least one subtask AC that would catch a violation.

**5. Edge case / overflow rules:** Each boundary condition in the spec must have a corresponding test in at least one subtask's test_strategy.

If gaps are found, update the decomposition before proceeding.

---

## Step 6: Create Human-Readable Plan

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    cat > .map/${BRANCH}/task_plan_${BRANCH}.md << 'PLAN_EOF'
<MAP_Plan_v1_0 branch="<branch>" created="YYYY-MM-DD">

# Task Plan: [Brief Title]

**Workflow:** map-plan

## Overview

[1-2 sentence description of the overall goal]

## Subtasks

### ST-001: [Subtask Title]
- **Status:** pending
- **AAG Contract:** `Actor -> Action(params) -> Goal`
- **Complexity:** [low/medium/high]
- **Expected Diff Size:** [tiny|small|medium|large]
- **Concern Type:** [api|config|data|docs|infra|observability|refactor|release|runtime|security|tests|ui|mixed]
- **One Logical Step:** [true|false]
- **Dependencies:** [none | ST-XXX]
- **Description:** [what needs to be done]
- **Acceptance Criteria:**
  - [ ] Criterion 1
- **Verification:**
  - [ ] Test command(s): [e.g., pytest -k test_name]

### ST-002: [Next Subtask]
...

## Execution Order

1. ST-001 (no deps)
2. ST-002 → ST-003 (ST-003 depends on ST-002)

## Spec Coverage

| Spec Section | Requirement ID | Description | Owner ST | Verified By |
|-------------|---------------|-------------|----------|-------------|
| MVP AC | AC-1 | [criterion] | ST-NNN | [test or check] |
| Invariant | INV-1 | [invariant] | ST-NNN | [test or check] |
| Cross-cutting | Observability | [structured logs] | ST-NNN | [check] |

Rules: every AC, invariant, result schema field, and cross-cutting concern must have a row.
A row with no Owner ST means the plan is incomplete.

## Notes

[Any important context, gotchas, or design decisions]

</MAP_Plan_v1_0>
PLAN_EOF
    echo "Saved task_plan_${BRANCH}.md"
```

**AAG Contract is REQUIRED for every subtask.** Copy from decomposer output's `aag_contract` field. Without it, executors reason instead of compile.

---

## Step 6.5: Validate Constraints

If the spec has a `## Constraints` section with non-null `scope_glob`, validate before finalizing the planning artifacts:

```
shell_command:
  cmd: |
    SCOPE_GLOB="<value from spec>"
    if echo "$SCOPE_GLOB" | grep -qE '(\.\.)|^/|\{'; then
      echo "ERROR: Invalid scope_glob '$SCOPE_GLOB'. Must be relative, no '..' or brace expansion."
      exit 1
    fi
    echo "scope_glob OK: $SCOPE_GLOB"
```

On validation failure: print error and STOP. Do not finalize the plan handoff.

---

## Step 7: Record Planning Artifacts

Do **NOT** create `step_state.json` in `$map-plan`.

`step_state.json` is the execution runtime state owned by `map_orchestrator.py`. Writing a planning-only state file here creates a contract mismatch with `$map-efficient` and can cause execution to skip the first subtask or bypass `resume_from_plan`.

`$map-plan` must stop after producing planning artifacts only:
- `spec_<branch>.md`
- `task_plan_<branch>.md`
- `blueprint.json`
- `artifact_manifest.json`
- optional `research/plan__discovery.md` (or legacy `findings_<branch>.md` fallback) and `workflow-fit.json`

The execution state must be initialized later by:

```
shell_command:
  cmd: python3 .map/scripts/map_orchestrator.py resume_from_plan
```

That runtime bootstrap comes from task_plan_<branch>.md and blueprint.json, not from parsing reviewer-facing markdown.

Record artifacts in the manifest:

```
shell_command:
  cmd: |
    python3 .map/scripts/map_step_runner.py record_plan_artifacts
```

---

## Step 8: Output Checkpoint

Print a clear checkpoint:

```
shell_command:
  cmd: |
    BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
    echo "==================================================="
    echo "WORKFLOW CHECKPOINT: PLAN PHASE COMPLETE"
    echo "==================================================="
    echo "[ok] Workflow-fit: map-plan"
    echo "[ok] Discovery completed (or skipped)"
    echo "[ok] Already-implemented gate: ran (or skipped with reason)"
    echo "[ok] Interview completed (or skipped)"
    echo "[ok] Devil's Advocate review completed (or skipped)"
    echo "[ok] Architecture graph written to spec_${BRANCH}.md"
    echo "[ok] Blueprint saved to .map/${BRANCH}/blueprint.json"
    echo "[ok] Coverage check passed"
    echo "[ok] Plan written to .map/${BRANCH}/task_plan_${BRANCH}.md"
    echo "[ok] artifact_manifest.json updated"
    echo "[ok] Mode: [standard | light | deep]"
    echo ""
    echo "Next steps:"
    echo "  1. Review .map/${BRANCH}/task_plan_${BRANCH}.md"
    echo "  2. Execute subtasks sequentially (map-task or map-efficient)"
    echo "  3. Verify completion: \$map-check"
    echo ""
    echo "Execution state intentionally deferred to $map-efficient / resume_from_plan"
    echo "==================================================="
```

---

## Step 9: Context Distillation + STOP

Before stopping, verify distilled state is self-contained. The next session starts fresh — it will ONLY see files, not this conversation. Runtime execution state will be rebuilt later via `resume_from_plan`.

```
DISTILLATION CHECKLIST:
  [x] task_plan_<branch>.md   — AAG contracts for every subtask + Spec Coverage table
  [x] blueprint.json          — raw decomposer output with coverage_map + per-subtask aag_contract (for map-efficient)
  [x] spec_<branch>.md        — architecture graph + decisions + COMPLETE acceptance criteria
  [x] artifact_manifest.json  — records workflow_fit + spec + plan stage artifacts
  [x] research/plan__discovery.md — plan-scope research pointers (if discovery was done)

TARGET: Executor reads <=4000 tokens of distilled state to start any subtask.
If plan files exceed this, condense descriptions — keep AAG contracts and criteria.
The Spec Coverage table MUST NOT be condensed — it is the review contract.
```

**This phase ends here.** Do NOT proceed to execution. The next invocation starts fresh with focused attention on individual subtasks (use `$map-task` or `$map-efficient`).
