---
name: map-prd-review
description: |
  PRD/requirements-quality review before /map-plan. Use when you have a product brief, PRD, or requirements note and need to verify its quality before starting planning. Reviews across 11 dimensions and returns a verdict: ready_for_plan, needs_prd_revision, needs_user_decision, or route_to_wayfind. Writes durable artifacts to .map/<branch>/prd-review.{json,md}. Do NOT use as a substitute for /map-plan, or on well-scoped engineering tasks that have no PRD.
effort: low
disable-model-invocation: true
argument-hint: "[path/to/prd.md or inline requirements text]"
---
# MAP PRD / Requirements-Quality Review

Reviews the quality of a supplied PRD, product brief, or requirements note **before**
`/map-plan` transforms it into a spec. A weak PRD causes MAP to invent product decisions,
produce unmeasurable acceptance criteria, and miss security or operational concerns.

**This skill does NOT write code or start planning.** It produces a quality verdict and
blocking findings that the user resolves before calling `/map-plan`.

## Input

Provide one of:
- A path to a Markdown file: `/map-prd-review path/to/feature.md`
- Inline text pasted after the command.

## Verdicts

| Verdict | Meaning | Next step |
|---------|---------|-----------|
| `ready_for_plan` | Input is ready for `/map-plan` | Call `/map-plan` |
| `needs_prd_revision` | Fixable missing fields; PRD should be amended | Revise PRD, re-run |
| `needs_user_decision` | Product/design choices must be answered | Answer questions, re-run |
| `route_to_wayfind` | Input too foggy for a PRD review | Call `/map-wayfind` first |

## Review Dimensions

The reviewer inspects these dimensions and reports findings:

1. **measurable_acceptance_criteria** — Are AC items pass/fail testable?
2. **user_job_clarity** — Is the target user and job-to-be-done explicit?
3. **explicit_out_of_scope** — Is what is NOT included stated?
4. **non_functional_requirements** — Are NFRs present when implied by domain/risk?
5. **data_model_lifecycle** — Is data shape, ownership, and lifecycle clear?
6. **ux_states_failure_states** — Are loading, empty, error, and edge UX states covered?
7. **security_trust_boundaries** — Are authentication, authorization, and trust surfaces stated?
8. **dependencies_integrations** — Are external systems and contracts named?
9. **contradictions_assumptions** — Are hidden assumptions or contradictions present?
10. **testability** — Can "done" be verified mechanically?
11. **migration_rollout** — Are migration/rollout/operational concerns addressed when relevant?

## Effort and Parallelism Policy

```yaml
thinking_policy: low/direct
parallel_tool_policy: sequential_by_default
```

- Run a single focused review; do not spawn sub-reviewers unless the PRD is multi-component.
- Do not write code, modify files outside `.map/<branch>/`, or start planning.

## Workflow

### Step 1: Read the PRD

Read the supplied file or text. If the argument is a file path that does not exist, report an error and stop.

### Step 2: Review Against Dimensions

For each of the 11 dimensions, decide:
- Does the PRD address this dimension adequately?
- If not, classify severity: `critical` (blocks planning), `major` (serious gap), `minor` (nice-to-have), `info` (note).
- Provide a concrete finding description and a suggested revision when applicable.

### Step 3: Determine Verdict

Apply this decision logic:

1. Any `critical` finding → candidate for `needs_prd_revision` or `needs_user_decision`.
2. If the input is so vague/strategic that a PRD review cannot even identify the target user or feature → `route_to_wayfind`.
3. If there are concrete product/design choices that ONLY the human can make → `needs_user_decision` (must produce at least one blocking question).
4. If findings are fixable revisions (missing sections, vague AC) → `needs_prd_revision`.
5. No `critical` or `major` findings → `ready_for_plan`.

### Step 4: Write Artifacts

Call the step runner to persist results:

```
python3 .map/scripts/map_step_runner.py write_prd_review <verdict> \
  --findings '<findings JSON>' \
  --blocking-questions '<blocking questions JSON>' \
  --suggested-revisions '<suggested revisions JSON>' \
  --summary "<one-paragraph summary>" \
  --prd-source "<file path or label>"
```

**findings JSON format:**
```json
[
  {
    "dimension": "measurable_acceptance_criteria",
    "severity": "major",
    "description": "AC-2 says 'fast response' but does not specify a latency budget.",
    "suggested_revision": "Define latency budget, e.g. p95 < 200ms under 100 RPS."
  }
]
```

**blocking-questions JSON format (for needs_user_decision):**
```json
[
  {
    "question": "Should the feature support unauthenticated users or require login?",
    "category": "security_trust_boundaries"
  }
]
```

**suggested-revisions JSON format (for needs_prd_revision):**
```json
[
  "Add an explicit out-of-scope section listing what this feature does NOT cover.",
  "Replace 'should be fast' in AC-3 with a measurable latency target."
]
```

### Step 5: Report to User

Show a summary of the verdict and key findings. If `ready_for_plan`, suggest calling `/map-plan`.

## Artifacts Written

- `.map/<branch>/prd-review.json` — machine-readable verdict and findings
- `.map/<branch>/prd-review.md` — human-readable review report

## Examples

```
/map-prd-review docs/feature-brief.md
/map-prd-review We want to add a notification system that sends emails when orders ship.
```

## Troubleshooting

- **File not found**: If you pass a path, confirm the file exists relative to the project root before invoking.
- **`route_to_wayfind` returned unexpectedly**: The input is too vague or strategic to review as a PRD. Call `/map-wayfind` first to resolve open decisions, then re-run.
- **Artifact not written**: Check that `.map/<branch>/` is writable and `map_step_runner.py` is present in `.map/scripts/`.

## Non-Goals

- Do not replace `/map-plan`. This reviews the INPUT to planning, not the plan itself.
- Do not block tiny direct edits or well-scoped engineering tasks that have no PRD.
- Do not run multiple agent sub-reviews unless the PRD is unusually large.
- Do not store raw customer data or secrets in `.map/` artifacts.
