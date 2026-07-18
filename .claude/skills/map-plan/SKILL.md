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

### Pre-flight: Mode Detection

Read `$ARGUMENTS` for mode flags **before any other action**. Strip detected flags from `$ARGUMENTS` before using the remainder as the task description.

| Flag | Mode | Effect |
|------|------|--------|
| `--light` | LIGHT | Spec-only, no research. **Skip** Step 0, Step 0.5 (Always-Implemented Gate), and Step 2b (Devil's Advocate Review). Limit decomposition to 2–5 minimal subtasks. Fastest plan mode — use when scope is small and well-understood. |
| `--deep` | DEEP | Full research + architecture review. Add extended research sweep **before** Step 0 and an architecture review step **after** Step 4. Use when scope is large or risk is high. |
| `--force-full` | DEEP alias | Identical to `--deep`. Overrides any scale auto-advisory toward maximum planning depth. |
| `--force-fast` | FAST exit | Recommend `/map-fast` and STOP. Use when the task is clearly trivial and MAP planning overhead is not warranted. |

If **no flag** is present (standard mode), run all steps as written. The Scale Advisory in the Workflow-Fit Gate may suggest a mode when scope is clear from the task description.

### Pre-flight: Resume Detection

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')
python3 .map/scripts/map_step_runner.py check_plan_resume "$ARGUMENTS"
```

This reports the existing artifacts (`plan__discovery` or legacy `findings`/`spec`/`task_plan`/`step_state`) AND a `verdict` that compares the prior plan's goal against the current request — so a branch that already hosts a *completed* plan for a different goal is not mistaken for "this plan is done". Branch on `verdict`:

- `no_plan` → no prior artifacts; plan fresh from Step 0.
- `goal_mismatch` → the branch already holds a plan for a **different** goal (a single branch can host several sequential plans over its lifetime). Do **NOT** print "plan complete" and do **NOT** overwrite the prior `spec`/`blueprint`/`task_plan`. Follow the `recommendation`: archive or rename the existing `.map/<branch>/` artifacts (or run `/map-plan` on a fresh branch) — confirm with the operator first — then plan the new goal.
- `resume` → the request matches the existing plan (or no request text was supplied to compare). Apply the per-artifact resume rules below.

Per-artifact resume rules (only when `verdict` is `resume`):
- Existing plan discovery: prefer `.map/<branch>/research/plan__discovery.md`. If only legacy `.map/<branch>/findings_<branch>.md` exists, read it as a compatibility fallback and migrate it to the canonical research path only if it has an `Already Implemented` section. If the discovery artifact predates that format, re-run discovery (see Step 0).
- Existing `spec`: skip interview/spec writing.
- Existing `task_plan`: skip decomposition and plan creation.
- Existing `step_state.json`: plan is complete; print checkpoint and STOP.

### Pre-flight: Wayfinding Handoff (optional)

If a `/map-wayfind` map already resolved the key decisions, seed this plan from its handoff instead of re-deciding them.

**Precedence over resume:** a handoff seeds a *fresh* plan, so this step only applies when the Resume Detection verdict is `no_plan` (or `goal_mismatch` after you archive the prior artifacts). On a `resume` verdict the branch already has a `spec`/`task_plan` — that existing artifact wins and the handoff is NOT re-consumed (re-seeding would silently overwrite in-progress work). To plan from a handoff, run `/map-plan --wayfind <slug>` on a branch with no in-progress plan (or archive/rename the existing `.map/<branch>/` artifacts first, with operator confirmation).

- If `$ARGUMENTS` contains `--wayfind <slug>`, read `.map/wayfind/<slug>/handoff.json` (repo-level, not branch-scoped).
- Otherwise run `python3 .map/scripts/wayfind_runner.py list_handoffs`. If exactly one completed handoff exists, OFFER it to the user ("found a completed wayfinding map `<slug>` — seed the plan from it?") and use it only on an explicit yes. Never match a handoff to the request by guessing; with zero or multiple handoffs and no explicit `--wayfind`, skip this step.

When a handoff is used, pre-seed the spec: `decisions[]` → **Decisions Made** (settled — the interview must NOT re-ask them; carry them as a do-not-re-ask list), `out_of_scope[]` → **Out of Scope**, `remaining_risks[]` → **Open Questions**. Then continue below for anything the handoff did not settle. Do not modify the wayfinding map.

### Pre-flight: Workflow-Fit Gate

Decide whether MAP planning is warranted before discovery or interview.

Signals:
- `expected_diff_size`: tiny | small | medium | large
- `has_new_invariants`: true | false
- `needs_independent_review`: true | false
- `has_clear_acceptance_criteria`: true | false
- `test_first_required`: true | false
- `depends_on_runtime_state`: true | false — does the plan's **correctness** depend on **current production/runtime state** (applied migration head, a table/column/index/enum value that exists in the live DB, current row counts / backfill volume, the actual value of a feature flag or config, runtime capacity/traffic)? Ask the operator directly when unsure — **if unsure, set it true.** Set it `false` for refactors, tests, docs, and static-config edits: "the code will eventually run in prod" is NOT runtime-dependence. When true, Step 0.6 runs.

Persist the decision (use the keyword form so the new signal is unambiguous):

```bash
python3 .map/scripts/map_step_runner.py record_workflow_fit "<direct-edit|map-fast|map-wayfind|map-plan>" \
  --diff-size "<tiny|small|medium|large>" \
  --has-new-invariants <0|1> --needs-independent-review <0|1> \
  --has-clear-acceptance-criteria <0|1> --test-first-required <0|1> \
  --depends-on-runtime-state <0|1> \
  --summary "<one-sentence decision summary>"
```

Outcomes:
- `direct-edit`: explain MAP is not needed and STOP.
- `map-fast`: recommend `/map-fast` and STOP.
- `map-wayfind`: too foggy to specify — you cannot write sharp acceptance criteria because several core decisions are still unresolved and entangled (not merely "needs a little research"). Recommend `/map-wayfind chart "<loose idea>"` to resolve the decision frontier first, then return with `/map-plan --wayfind <slug>`. STOP. (This is the inverse of the Wayfinding Handoff pre-flight: that consumes a finished map; this sends you to create one.)
- `map-plan`: continue.

**Scale Advisory (standard mode only, when no `--light`/`--deep` flag was given):** After recording a `map-plan` outcome, estimate the task's scope (files to change, lines to add/modify) and run:

```bash
python3 .map/scripts/classify_scope.py --files ESTIMATED_FILES --lines ESTIMATED_LINES
```

If `auto_enabled: true` in the JSON result, surface an advisory based on `bracket` (do not block):

- `trivial` → advise `/map-fast` instead (already covered by the `map-fast` outcome above).
- `small` → advise re-invoking as `/map-plan --light` for a lighter-weight plan.
- `large` → advise re-invoking as `/map-plan --deep` for full research + architecture review.
- `medium` → no advisory; standard mode is appropriate.

The advisory is informational — the user's flags or your judgment prevail. If the user accepts, add the flag and restart; otherwise continue in standard mode.

### Step 0: Quick Discovery (Optional but Recommended; SKIP in LIGHT mode)

> **LIGHT mode:** Skip this step entirely — proceed directly to Step 1. The spec is written from the stated requirements without a prior research phase.
>
> **DEEP mode:** Before this step, run an extended research sweep (SOFA search if available, full codebase exploration, dependency and hotspot analysis). Dispatch a research-agent with a wider scope than the standard Step 0 prompt below; cover recent-change hotspots, dependency graph, existing test coverage gaps, and architectural friction points. Save findings to `.map/$BRANCH/research/plan__deep_discovery.md` in addition to the standard `plan__discovery.md`. Then continue with Step 0 as written.

Use `.map/<branch>/research/plan__discovery.md` as the canonical plan-scope discovery artifact. If it exists, read it and skip discovery — but ONLY if it contains an `Already Implemented` section (the format this skill now requires). If the canonical file is absent but legacy `.map/<branch>/findings_<branch>.md` exists, read that fallback and migrate it to the canonical path with `save_research "$BRANCH" plan discovery` only if it has the required section. A discovery file written before this format existed lacks that section; in that case re-run discovery with the prompt below so the Step 0.5 gate has the evidence it requires. Otherwise (no discovery file at all) run discovery to find relevant files, existing patterns, risks, and confirmed new files.

```text
Task(
  subagent_type="research-agent",
  description="Quick discovery for planning",
  prompt="""
<documents>
  <document source="user-request"><document_content>$ARGUMENTS</document_content></document>
</documents>
<task>Locate relevant code and return verified existing files, new files confirmed absent, patterns, risks, and unknowns. Also determine, with `file:line` evidence, which parts of the request are ALREADY IMPLEMENTED in the codebase (whole feature, or specific behaviors/acceptance criteria) versus genuinely missing. Do not assume absence — search for existing implementations before reporting a part as missing.

**MANDATORY artifact write:** When your research is complete, write the FULL detailed report (not a summary) directly to `.map/$BRANCH/research/plan__discovery.md` using the Write tool. Every `file:line` reference you found must appear in that file — downstream steps (Step 0.5 and Step 2a.5) read this file directly and will fail if it contains only a summary. After writing, confirm: "Written full discovery report to .map/$BRANCH/research/plan__discovery.md".</task>
<expected_output>Write `.map/$BRANCH/research/plan__discovery.md` containing Markdown sections: Already Implemented (each entry cites the feature part + `file:line` proof), Existing Files, Files to Create, Patterns Found, Risks / Unknowns. If nothing matching the request exists, write "Already Implemented: none found (searched: &lt;queries&gt;)". Then return a brief confirmation to the parent (not a re-summary — the file is the canonical artifact).</expected_output>
"""
)
```

**Note on continuation:** If you need the research agent to elaborate on its findings after the Task returns, use `SendMessage` to the agent's task id — do NOT spawn a new `Agent` call, which starts with no prior context and will produce a hallucinated unrelated report.

After the Task returns, verify the artifact was written directly (preferred path). Fall back to saving the returned text only if the agent did not write the file:

```bash
if [ ! -f ".map/$BRANCH/research/plan__discovery.md" ]; then
  printf '%s' "$PLAN_DISCOVERY" | \
    python3 .map/scripts/map_step_runner.py save_research "$BRANCH" plan discovery
fi
```

### Step 0.5: Already-Implemented Gate (MANDATORY when discovery ran; SKIP in LIGHT mode)

> **LIGHT mode:** Skip this step — no discovery was run, so there is no evidence base for the gate. Rely on the user's statement that the feature is new; if you discover overlap during spec writing, surface it there.

Before interviewing or writing the spec, reconcile the request against the discovery `Already Implemented` section. Do not plan work the codebase already does. This gate runs whenever Step 0 produced findings; if discovery was intentionally skipped (greenfield or fully-provided spec), state that the gate was skipped and why. If the findings file lacks an `Already Implemented` section (it predates this format), do NOT run the gate on incomplete evidence — re-run Step 0 discovery first.

Classify the request:

- **Whole feature already implemented** — every observable behavior the user asked for exists, with `file:line` proof. Off-ramp: report what already satisfies the request (cite the evidence), state that no plan is needed, and STOP. Do not write a spec or blueprint. If the user may want changes to the existing implementation, ask them to restate the gap rather than re-planning what exists.
- **Partially implemented** — some behaviors/acceptance criteria exist, others are missing. Carry the already-done parts into the spec's **Out of Scope** under an `Already Implemented` subsection (with `file:line` evidence) so decomposition plans ONLY the remaining work. Re-scope the request to the gap before continuing.
- **Not implemented** — nothing matching exists (or only unrelated patterns). Continue normally.

When in doubt about whether an existing implementation truly satisfies a request, treat it as partially implemented and surface the ambiguity in the interview or Open Questions — never silently re-plan code that already exists, and never silently assume an existing file already covers a behavior.

### Step 0.6: Verify Live/Runtime State Gate (MANDATORY when `depends_on_runtime_state=true`)

The runtime analogue of Step 0.5: that gate stops you re-planning code that already exists; this one stops you planning against **runtime facts that have drifted** from the design docs / memory the plan copied them from. Skip this step only when `depends_on_runtime_state=false`; if it is true, **read [plan-reference.md](plan-reference.md#verify-liveruntime-state) before Step 1** and run this gate.

Caution — Step 0.5 ≠ Step 0.6: code can exist in the repo (already-implemented) while its migration / feature-flag is **not yet applied in prod**. A `file:line` proof does not prove the live state; verify runtime separately.

For each assumption the plan's correctness rests on (counts, enum/label sets, an existing column, the applied migration head, a live flag/config value, capacity):

- **Verifiable now (read-only):** confirm it empirically through an approved read-only source (read replica, dashboard, runbook, metadata query such as `INFORMATION_SCHEMA` / `pg_enum` / migration-head introspection). Cite the **fact**, not the raw query result. Never write/mutate, and never paste PII, secrets, or bulky prod output into the spec or `.map/<branch>/` artifacts (they may be committed). This skill is a planning-time gate, **not** a runtime tool — it does not run the query itself; defer execution to the operator or an authorized sub-agent.
- **Prod unreachable / unverified:** do NOT bake the assumption in as fact. Record it under the spec's **Open Questions / Risks** as an `Unverified Runtime Assumption` with the **exact read-only check to run** (and the safe source), and mark every subtask that depends on it `provisional` until verified.

Do not hard-stop merely because prod is unreachable — record-the-check is the contract. If a runtime dependency only surfaces later (during decomposition), loop back and verify-or-record it the same way.

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

**Requirements Index (MANDATORY):** After writing the spec, populate the `mapify:requirements-index:v1` sentinel-wrapped fenced YAML block (defined in the spec template) with exactly ONE `{id, kind}` entry per acceptance criterion, invariant, hard constraint, and cross-cutting requirement. `kind` must be one of `acceptance_criterion | invariant | hard_constraint | cross_cutting`. IDs must be canonical: prefix in `{AC, INV, HC, CCR}`, no leading zeros, uppercase (e.g. `AC-1`, `INV-2`, `HC-3`). These IDs are **exactly** the keys the decomposer must map in `coverage_map` — the forward-completeness gate diffs the index IDs against `coverage_map` keys to detect uncovered requirements.

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

### Step 2b: Devil's Advocate Review (SPEC_REVIEW; SKIP in LIGHT mode)

> **LIGHT mode:** Skip this step. The spec is written from well-understood requirements; a lightweight self-review of the open-questions list and acceptance criteria suffices before decomposition.

Run Monitor as a spec reviewer before decomposition.

```text
Task(
  subagent_type="monitor",
  description="Review spec before decomposition",
  prompt="""
<documents>
  <document source="spec"><document_content>{spec_content}</document_content></document>
  <document source="plan-discovery"><document_content>{plan_discovery_content}</document_content></document>
</documents>
<task>
Review the spec for ambiguity, missing invariants, impossible acceptance criteria, and risky assumptions.
Evidence first: for every finding, quote the spec or plan discovery before judgment.
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

### Step 4.5: Architecture Review (DEEP mode only)

> **DEEP mode:** Before decomposition, dispatch Monitor as an architecture reviewer over the spec + deep discovery findings. Focus on component boundaries, dependency flow, state ownership, testability, and whether the proposed approach is consistent with the existing architecture documented in `docs/ARCHITECTURE.md`.

```text
Task(
  subagent_type="monitor",
  description="Architecture review before decomposition (DEEP mode)",
  prompt="""
<documents>
  <document source="spec"><document_content>{spec_content}</document_content></document>
  <document source="deep-discovery"><document_content>{deep_discovery_content}</document_content></document>
</documents>
<task>
Review the proposed architecture for: component boundary clarity, dependency direction violations, state ownership ambiguity, untestable seams, and conflicts with the existing system described in docs/ARCHITECTURE.md.
Evidence first: cite the spec or discovery before each finding.
CRITICAL findings must identify the exact spec section and the specific risk.
</task>
<expected_output>
Return JSON: {"valid": bool, "findings": [{"severity": "critical|high|medium", "section": "...", "finding": "...", "recommendation": "..."}], "summary": "..."}.
</expected_output>
"""
)
```

Fix any CRITICAL or HIGH findings before proceeding to Step 5. Add unresolved architecture risks to the spec's Open Questions.

> **Standard / LIGHT mode:** Skip this step.

### Step 5: Call Task Decomposer

```text
Task(
  subagent_type="task-decomposer",
  description="Decompose approved spec",
  prompt="""
<documents>
  <document source="spec"><document_content>{spec_content}</document_content></document>
  <document source="plan-discovery"><document_content>{plan_discovery_content}</document_content></document>
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
LIGHT mode: target 2–5 minimal, bite-sized subtasks. Prefer merging related concerns into one subtask rather than splitting them. Do not over-decompose well-understood small tasks.
</constraints>
<expected_output>Return only blueprint JSON.</expected_output>
"""
)
```

### Step 5.5: Save Blueprint JSON

Write decomposer output to `.map/<branch>/blueprint.json` exactly once. Preserve evidence and metadata.

### Step 5.55: Normalize Blueprint (MANDATORY)

```bash
python3 .map/scripts/map_step_runner.py normalize_blueprint
```

A deterministic repair pass that fixes the two self-consistency drifts the decomposer routinely emits — so you don't hand-edit `blueprint.json` between decompose and validate:

- **Forward-dependency ordering:** stably topologically sorts `subtasks[]` so every dependency is declared before its dependents (independent subtasks keep their order; a true cycle is left for the validator to reject).
- **coverage_map bracket-tags:** for every `coverage_map[req] = owner` whose owner's `validation_criteria` doesn't already cite `[req]`, appends a `[req]`-tagged criterion.

It never invents `coverage_map` ownership or rewrites dependency edges — genuine semantic gaps still fail Step 5.6. Idempotent (`changed: false` if nothing needed fixing).

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
| `record_workflow_fit <workflow> [--diff-size SIZE] [--has-new-invariants 0\|1] [--needs-independent-review 0\|1] [--has-clear-acceptance-criteria 0\|1] [--test-first-required 0\|1] [--depends-on-runtime-state 0\|1] [--summary "..."]` | Persist the workflow-fit decision. Use the named flags — bool order is easy to confuse otherwise. `--depends-on-runtime-state 1` arms Step 0.6 (defaults `0`; the legacy positional form always records it `0`). |
| `normalize_blueprint [<path>] [--check]` | Deterministically repair decomposer drift before validation: topo-sort `subtasks[]` so deps precede dependents + inject missing `coverage_map` bracket-tags. `--check` reports without writing. |
| `validate_blueprint_contract <path>` | Run schema + semantic checks on `blueprint.json`. |
| `list_plans` | List per-branch plan artifacts under `.map/` to pick scope from a multi-roadmap workspace. |
| `check_plan_resume "<request>" [--branch <b>]` | Resume preflight: reports existing artifacts + a `verdict` (`no_plan`/`resume`/`goal_mismatch`) comparing the prior plan's goal against the incoming request, so a branch hosting a *completed* plan for a different goal isn't falsely treated as "complete". |
| `save_research <branch> <subtask_id> [kind]` | Persist research-agent findings (stdin-fed). `/map-plan` uses `save_research "$BRANCH" plan discovery`; execution subtasks use `save_research "$BRANCH" "$SUBTASK_ID"`. |
| `validate_research <branch> <subtask_id>` | Validate strict JSON research evidence before `validate_step 2.2`. |

### Step 8: Output Checkpoint

Print a concise checkpoint:

```text
PLAN COMPLETE
Spec: .map/<branch>/spec_<branch>.md
Blueprint: .map/<branch>/blueprint.json
Task plan: .map/<branch>/task_plan_<branch>.md
Mode: [standard | light | deep]
Next: /map-efficient or /map-task for a selected subtask
```

Include the active mode (`light` / `deep` / `standard`) so the operator knows which steps ran.

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
- `/map-plan --light`: spec-only mode, no research, 2–5 minimal subtasks (small, well-understood tasks).
- `/map-plan --deep`: full research + architecture review mode (large or risky tasks). Also `--force-full`.
- `/map-plan --force-fast`: skip planning; recommend `/map-fast` and stop.

## State Machine Integration

Planning artifacts become the inputs for `/map-efficient` state initialization. Do not edit state directly.

## Hook Enforcement

Hooks may enforce read-only planning boundaries and later implementation boundaries. If a hook blocks expected planning artifact writes, report the exact command and blocker.

## Examples

See [plan-reference.md](plan-reference.md#examples) for complete planning transcripts and generated task-plan examples.

## Troubleshooting

See [plan-reference.md](plan-reference.md#troubleshooting) for stale artifacts, failed blueprint validation, unsupported direct-edit off-ramp, and spec-review failures.

## Success Criteria

- Mode flags detected and stripped from `$ARGUMENTS` before use.
- Workflow-fit decision recorded.
- Already-implemented gate ran (or was explicitly skipped with a reason): whole-feature duplicates off-ramped, partial duplicates moved to spec "Out of Scope > Already Implemented". (LIGHT mode: gate explicitly skipped — noted in checkpoint.)
- Live/runtime-state gate ran when `depends_on_runtime_state=true`: each runtime assumption was verified read-only, or recorded as an `Unverified Runtime Assumption` (Open Questions / Risks) with the exact check to run and dependent subtasks marked `provisional`.
- Spec exists or is intentionally reused.
- Blueprint exists and `validate_blueprint_contract` passed.
- Human-readable task plan includes scope metadata and coverage.
- DEEP mode: architecture review (Step 4.5) ran and any CRITICAL findings were resolved before decomposition.
- LIGHT mode: decomposition produced 2–5 minimal subtasks.
- The command stops with a clear execution handoff that names the active mode.
