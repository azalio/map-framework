---
name: map-plan
description: |
  ARCHITECT phase only: produce an upfront plan by decomposing a complex task into atomic subtasks with clear dependencies, via task-decomposer. Use when the user asks to plan, create a structured plan, break down, decompose, or stage work — e.g. planning a feature, refactor, migration, API/versioning upgrade, or incremental/phased rollout into smaller independent steps before any code is written. Trigger on phrasing like "plan a…", "create a plan for…", "decompose…into tasks", "break this into steps", "roll out incrementally", or "smaller independent steps". Do NOT use to execute work; use map-task or map-efficient.
effort: high
argument-hint: "[task description]"
---
# /map-plan - ARCHITECT Phase (Decomposition Only)

Purpose: plan and decompose complex tasks into atomic subtasks. This command records artifacts and then stops; it does not implement or verify.

Use compact evidence-first examples from [Evidence-First Output Examples](../../references/map-output-examples.md). Use the shared [XML Prompt Envelope](../../references/map-xml-prompt-envelopes.md) for long prompts so source artifacts appear before task instructions and output contracts.

Use [plan-reference.md](plan-reference.md) for spec templates, architecture graph examples, full output examples, and troubleshooting. When a workflow step points to a reference section, read that section before executing the step; supporting files are not assumed to be in context automatically.

## Effort and Parallelism Policy

```yaml
thinking_policy: high/adaptive
parallel_tool_policy: discovery_only
```

- Use deeper reasoning for workflow-fit decisions, requirement conflicts, hard/soft constraints, and decomposition boundaries.
- Do not over-plan tiny work: honor the workflow-fit off-ramp when the task is a direct edit or `/map-fast` fit.
- Parallelize only independent discovery reads/searches. Keep interview decisions, spec writing, decomposition, blueprint validation, and state initialization sequential.

## When to use

- Starting a feature, refactor, or complex bug fix.
- Need a spec and task boundaries before execution.
- Need reviewable contracts with clear validation criteria.

## What this command does

- Records workflow fit before planning.
- Optionally runs discovery.
- Writes `.map/<branch>/spec_<branch>.md`.
- Calls task-decomposer to produce `.map/<branch>/blueprint.json`.
- Validates blueprint contract metadata.
- Writes `.map/<branch>/task_plan_<branch>.md`.
- Initializes planning artifacts and stops at a checkpoint.

## What this command cannot do

- Execute implementation.
- Verify completion.
- Edit code directly except planning artifacts.

## Workflow Steps

### Pre-flight: Resume Detection

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
echo "findings:    $(test -f .map/${BRANCH}/findings_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "spec:        $(test -f .map/${BRANCH}/spec_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "task_plan:   $(test -f .map/${BRANCH}/task_plan_${BRANCH}.md && echo EXISTS || echo MISSING)"
echo "state:       $(test -f .map/${BRANCH}/step_state.json && echo EXISTS || echo MISSING)"
```

Resume rules:
- Existing `findings`: reuse discovery only if the file has an `Already Implemented` section; if it predates that format, re-run discovery (see Step 0).
- Existing `spec`: skip interview/spec writing.
- Existing `task_plan`: skip decomposition and plan creation.
- Existing `step_state.json`: plan is complete; print checkpoint and STOP.

### Pre-flight: Workflow-Fit Gate

Decide whether MAP planning is warranted before discovery or interview.

Signals:
- `expected_diff_size`: tiny | small | medium | large
- `has_new_invariants`: true | false
- `needs_independent_review`: true | false
- `has_clear_acceptance_criteria`: true | false
- `test_first_required`: true | false

Persist the decision:

```bash
python3 .map/scripts/map_step_runner.py record_workflow_fit "<direct-edit|map-fast|map-plan>" "<tiny|small|medium|large>" "<true|false>" "<true|false>" "<true|false>" "<true|false>" "<one-sentence decision summary>"
```

Outcomes:
- `direct-edit`: explain MAP is not needed and STOP.
- `map-fast`: recommend `/map-fast` and STOP.
- `map-plan`: continue.

### Step 0: Quick Discovery (Optional but Recommended)

If `.map/<branch>/findings_<branch>.md` exists, read it and skip discovery — but ONLY if it contains an `Already Implemented` section (the format this skill now requires). A findings file written before this format existed lacks that section; in that case re-run discovery with the prompt below so the Step 0.5 gate has the evidence it requires. Otherwise (no findings file at all) run discovery to find relevant files, existing patterns, risks, and confirmed new files.

```text
Task(
  subagent_type="research-agent",
  description="Quick discovery for planning",
  prompt="""
<documents>
  <document source="user-request"><document_content>$ARGUMENTS</document_content></document>
</documents>
<task>Locate relevant code and return verified existing files, new files confirmed absent, patterns, risks, and unknowns. Also determine, with `file:line` evidence, which parts of the request are ALREADY IMPLEMENTED in the codebase (whole feature, or specific behaviors/acceptance criteria) versus genuinely missing. Do not assume absence — search for existing implementations before reporting a part as missing.</task>
<expected_output>Markdown sections: Already Implemented (each entry cites the feature part + `file:line` proof), Existing Files, Files to Create, Patterns Found, Risks / Unknowns. If nothing matching the request exists, write "Already Implemented: none found (searched: <queries>)".</expected_output>
"""
)
```

Save findings to `.map/<branch>/findings_<branch>.md`.

### Step 0.5: Already-Implemented Gate (MANDATORY when discovery ran)

Before interviewing or writing the spec, reconcile the request against the discovery `Already Implemented` section. Do not plan work the codebase already does. This gate runs whenever Step 0 produced findings; if discovery was intentionally skipped (greenfield or fully-provided spec), state that the gate was skipped and why. If the findings file lacks an `Already Implemented` section (it predates this format), do NOT run the gate on incomplete evidence — re-run Step 0 discovery first.

Classify the request:

- **Whole feature already implemented** — every observable behavior the user asked for exists, with `file:line` proof. Off-ramp: report what already satisfies the request (cite the evidence), state that no plan is needed, and STOP. Do not write a spec or blueprint. If the user may want changes to the existing implementation, ask them to restate the gap rather than re-planning what exists.
- **Partially implemented** — some behaviors/acceptance criteria exist, others are missing. Carry the already-done parts into the spec's **Out of Scope** under an `Already Implemented` subsection (with `file:line` evidence) so decomposition plans ONLY the remaining work. Re-scope the request to the gap before continuing.
- **Not implemented** — nothing matching exists (or only unrelated patterns). Continue normally.

When in doubt about whether an existing implementation truly satisfies a request, treat it as partially implemented and surface the ambiguity in the interview or Open Questions — never silently re-plan code that already exists, and never silently assume an existing file already covers a behavior.

### Step 1: Assess Scope and Decide Interview Depth

Interview is required when the user explicitly invites clarification (`ask if unclear`, `do not assume`, `спрашивай`, `уточняй`, etc.) or when requirements are broad, vague, risky, or underspecified.

Skip interview only when the task is already well-defined with clear acceptance criteria and no critical open product decisions.

**Auto-Mode reconciliation.** Auto-mode tells the harness to "minimize interruptions"; this skill tells you to interview on vague scope. Both rules hold — auto-mode does NOT override the interview gate when scope is truly vague. Resolution:

- Roadmap-class input (>3 acceptance criteria absent, multiple feature ideas in one prompt, "explore options X/Y") → interview is REQUIRED even under auto-mode. Use a single batched `AskUserQuestion` (3-5 high-leverage questions at once) rather than a back-and-forth dialog so you minimize round-trips while still resolving ambiguity.
- Narrow task with explicit ACs / clear file scope → interview SKIPPED, proceed straight to spec/blueprint.
- When in doubt, batched interview wins; a wrong skip cascades into 12 subtasks of misaligned work.

### Step 2: Deep Interview (Spec Discovery)

Ask only non-obvious questions. Cover technical choices, UX, tradeoffs, risks, scope, integration, contract clarity, and durable state lifecycle for operations longer than one request.

Write `.map/<branch>/spec_<branch>.md`. The full spec template is in [plan-reference.md](plan-reference.md#spec-template); the active spec must include decisions, contradiction, invariants, constraints, edge cases, acceptance criteria, security boundaries, out of scope, and open questions.

### Step 2a: Write Spec (when interview was skipped)

Write the same spec artifact from the provided requirements and discovery evidence. Do not invent unresolved decisions; put them in Open Questions.

### Step 2a.5: Validate Spec Citations (MANDATORY)

Before the devil's-advocate review, gate on `file:line` citation correctness — stale citations in the spec ship to every downstream phase (research, Actor, Monitor) and cause real bugs (e.g., the hogback-gap ST-002 cited `src/mapify_cli/__init__.py:96` for `MAP_DEBUG` when the symbol had moved to :207). The validator finds every `<path>:<line>[-<line>]` pattern, checks the path exists and line is in range, and — when a backticked identifier sits next to the citation — verifies the cited line contains it.

```bash
python3 .map/scripts/validate_spec_citations.py --branch "$BRANCH"
```

- Exit 0 + `"passed": true` → proceed to Step 2b.
- Exit 1 + `"failures": [...]` with `status` in `{stale-citation, error}` → fix the spec (correct the line number, update the symbol name, or remove the citation) and re-run. Do NOT proceed to decomposition with red failures.
- Exit 2 → invocation error (missing branch / spec file); fix invocation, do not skip.

### Step 2b: Devil's Advocate Review (SPEC_REVIEW)

Run Monitor as a spec reviewer before decomposition.

```text
Task(
  subagent_type="monitor",
  description="Review spec before decomposition",
  prompt="""
<documents>
  <document source="spec"><document_content>{spec_content}</document_content></document>
  <document source="findings"><document_content>{findings_content}</document_content></document>
</documents>
<task>
Review the spec for ambiguity, missing invariants, impossible acceptance criteria, and risky assumptions.
Evidence first: for every finding, quote the spec or findings before judgment.
HIGH-severity findings must cite the exact spec section.
</task>
<expected_output>
Return JSON with evidence before verdict fields, issues, and required spec revisions.
</expected_output>
"""
)
```

Fix blocking spec issues before decomposition.

### Step 3: Create Branch Directory

```bash
mkdir -p ".map/${BRANCH}"
```

### Step 4: Explore Approaches + Architecture Graph

Add an architecture graph to the spec or plan when the implementation has multiple components, state boundaries, or dependencies. See [plan-reference.md](plan-reference.md#architecture-graph) for examples.

### Step 5: Call Task Decomposer

```text
Task(
  subagent_type="task-decomposer",
  description="Decompose approved spec",
  prompt="""
<documents>
  <document source="spec"><document_content>{spec_content}</document_content></document>
  <document source="findings"><document_content>{findings_content}</document_content></document>
</documents>
<task>
Break the spec into atomic subtasks. Include an `evidence` array before `subtasks` so every boundary is grounded in the spec or repo findings.
</task>
<constraints>
Each subtask must include expected_diff_size, concern_type, one_logical_step, validation_criteria, dependencies, complexity_score, risk_level, test_strategy, and aag_contract.
Split large subtasks unless split_rationale explains why the user payoff requires that scope in one subtask.
Split mixed-concern subtasks unless concern_justification explains why separation would lose user value.
Top-level coverage_map must map each acceptance criterion, invariant, and cross-cutting requirement to an owning subtask. Each key must appear as a bracketed tag in that subtask's validation_criteria, e.g. VC1 [AC-1]: retryable checkout timeout.
Top-level hard_constraints are non-negotiable: every hard_constraints id must appear in coverage_map and bracketed validation_criteria.
Top-level soft_constraints are negotiable only with coverage or tradeoff_rationale.
Do NOT create subtasks for behavior listed under the spec's "Out of Scope > Already Implemented" subsection; that work already exists in the codebase. Plan only the remaining gap.
</constraints>
<expected_output>Return only blueprint JSON.</expected_output>
"""
)
```

### Step 5.5: Save Blueprint JSON

Write decomposer output to `.map/<branch>/blueprint.json` exactly once. Preserve evidence and metadata.

### Step 5.6: Post-Save Blueprint Validation (MANDATORY)

```bash
python3 .map/scripts/map_step_runner.py validate_blueprint_contract
```

Do not proceed until this passes. The validator protects `coverage_map`, `validation_criteria`, bracket tags like `[AC-1]`, hard/soft constraints, `tradeoff_rationale`, `expected_diff_size`, `concern_type`, `one_logical_step`, `split_rationale`, and `concern_justification`.

### Step 5.7: Decomposition Coverage Check

Read validation output and confirm every acceptance criterion/invariant has an owning subtask and executable validation criteria.

### Step 6: Create Human-Readable Plan

Write `.map/<branch>/task_plan_<branch>.md`.

Required plan shape:

```markdown
# Task Plan: [Brief Title]

## Overview
- Goal: ...
- Source spec: .map/<branch>/spec_<branch>.md

## Subtasks

### ST-001: [Subtask Title]
- **Status:** in_progress
- **Expected Diff Size:** small|medium|large
- **Concern Type:** runtime|tests|docs|...
- **One Logical Step:** true
- **AAG Contract:** Actor -> Action -> Goal
- **Validation Criteria:** VC1 [AC-1]: ...
- **Dependencies:** []

## Execution Order
- ST-001 -> ST-002

## Spec Coverage
- AC-1 -> ST-001

## Notes
- risks, assumptions, or tradeoffs
```

### Step 6.5: Validate Constraints

Rerun blueprint validation after writing the human-readable plan if any decomposition data was transformed.

### Step 7: Record Planning Artifacts (Do This Last)

Record planning artifacts in the branch manifest after spec, blueprint, and task plan exist. Use the named CLI — don't introspect the script:

```bash
python3 .map/scripts/map_step_runner.py record_plan_artifacts
```

`/map-plan` deliberately stops BEFORE `INIT_STATE` (that step belongs to `/map-efficient`), so `plan_status: "ready"` requires only `task_plan_<branch>.md` + `blueprint.json` — `step_state.json` will land later. Don't be alarmed by `has_step_state: false` in the response; it's the expected planning-complete state.

Runner functions you'll commonly need from `/map-plan`:

| Function | Purpose |
|---|---|
| `record_plan_artifacts` | Persist spec/blueprint/task-plan into `artifact_manifest.json`. |
| `record_workflow_fit <workflow> [--diff-size SIZE] [--has-new-invariants 0\|1] [--needs-independent-review 0\|1] [--has-clear-acceptance-criteria 0\|1] [--test-first-required 0\|1] [--summary "..."]` | Persist the workflow-fit decision. Use the named flags — bool order is easy to confuse otherwise. |
| `validate_blueprint_contract <path>` | Run schema + semantic checks on `blueprint.json`. |
| `list_plans` | List per-branch plan artifacts under `.map/` to pick scope from a multi-roadmap workspace. |
| `save_research <branch> <subtask_id>` | Persist research-agent findings for a subtask (stdin-fed). |

### Step 8: Output Checkpoint

Print a concise checkpoint:

```text
PLAN COMPLETE
Spec: .map/<branch>/spec_<branch>.md
Blueprint: .map/<branch>/blueprint.json
Task plan: .map/<branch>/task_plan_<branch>.md
Next: /map-efficient or /map-task for a selected subtask
```

### Step 8.5: Execution Handoff Note

Name the recommended execution workflow and any high-risk first subtask. Do not start implementation.

### Step 9: Context Distillation + STOP

Summarize decisions, constraints, and next command. Then STOP.

## Design Rationale

Detailed rationale moved to [plan-reference.md](plan-reference.md#design-rationale). The key runtime rule remains: planning moves engineering judgment earlier and stops before implementation.

## Related Commands

- `/map-efficient`: implement an approved plan.
- `/map-task`: execute one selected subtask.
- `/map-check`: verify completion.
- `/map-review`: review the diff.
- `/map-learn`: preserve reusable learnings.

## State Machine Integration

Planning artifacts become the inputs for `/map-efficient` state initialization. Do not edit state directly.

## Hook Enforcement

Hooks may enforce read-only planning boundaries and later implementation boundaries. If a hook blocks expected planning artifact writes, report the exact command and blocker.

## Examples

See [plan-reference.md](plan-reference.md#examples) for complete planning transcripts and generated task-plan examples.

## Troubleshooting

See [plan-reference.md](plan-reference.md#troubleshooting) for stale artifacts, failed blueprint validation, unsupported direct-edit off-ramp, and spec-review failures.

## Success Criteria

- Workflow-fit decision recorded.
- Already-implemented gate ran (or was explicitly skipped with a reason): whole-feature duplicates off-ramped, partial duplicates moved to spec "Out of Scope > Already Implemented".
- Spec exists or is intentionally reused.
- Blueprint exists and `validate_blueprint_contract` passed.
- Human-readable task plan includes scope metadata and coverage.
- The command stops with a clear execution handoff.
