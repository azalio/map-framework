# /map-plan Supporting Reference

This file holds templates, examples, and troubleshooting for `/map-plan` so the invoked `SKILL.md` stays focused on the active planning flow.

## Spec Template

```markdown
# Spec: [Title]

## Decisions Made
| # | Question | Decision | Rationale |

## Contradiction
State the core design tension.

## Invariants
- Non-negotiable system truths.

## Constraints
- Hard and soft constraints with rationale.

## Edge Cases
- Failure and boundary cases.

## Acceptance Criteria
- AC-1: Observable outcome.

## Security Boundaries
- Trust boundaries and sensitive flows.

## Out of Scope
- Explicit exclusions.

### Already Implemented
- Feature parts the request asked for that already exist, each with `file:line` proof. The decomposer must NOT create subtasks for these (see Step 0.5: Already-Implemented Gate).

## Open Questions
- Questions that must be answered before decomposition or execution.
```

## Architecture Graph

Use a compact graph when components, state, or ownership boundaries matter:

```text
User Request -> API boundary -> Service -> Store
                  |              |
                  v              v
              Validation      Test seam
```

## Design Rationale

`/map-plan` exists to make scope and correctness reviewable before code is generated. The most important artifact is not prose; it is an executable contract that downstream Actor, Monitor, final-verifier, and reviewers can check.

## Examples

Authentication plan result:

```text
ST-001: Add token dependency
  AAG: PackageConfig -> add_dependency(pyjwt) -> import succeeds
ST-002: Implement token generation
  AAG: TokenService -> generate(user_id, ttl) -> signed JWT
ST-003: Add middleware validation
  AAG: AuthMiddleware -> validate(request) -> 401|passes with user_id
```

Direct-edit off-ramp:

```text
Decision: direct-edit
Reason: tiny isolated typo, clear acceptance criteria, no new invariants.
Next: edit directly; MAP planning is not needed.
```

Already-implemented off-ramp (whole feature):

```text
Decision: already-implemented (no plan)
Evidence:
  - "retry on 429" -> src/client/http.py:142-167 (backoff loop, max_retries)
  - "configurable timeout" -> src/client/config.py:38 (timeout_s field)
The request is already satisfied by existing code. No spec/blueprint written.
Next: if you want changes to the existing behavior, restate the specific gap.
```

Partial-implementation re-scope (continue planning the gap only):

```text
Already Implemented (-> spec Out of Scope):
  - "JWT validation" -> src/auth/middleware.py:51 (validate_token)
Remaining gap (planned):
  - token refresh endpoint + rotation (no existing implementation found)
```

## Troubleshooting

- Existing `step_state.json`: planning already completed; print checkpoint and stop — but only when the Resume-Detection `verdict` is `resume`. The `.map/<branch>/` layout is single-plan-per-branch, so a branch can host several sequential plans over its lifetime; `check_plan_resume "$ARGUMENTS"` compares the prior plan's goal against the current request and returns `goal_mismatch` when they differ. On `goal_mismatch`, do NOT report "plan complete" and do NOT overwrite the prior `spec`/`blueprint`/`task_plan`; archive or rename the existing `.map/<branch>/` artifacts (or plan on a fresh branch) with operator confirmation, then plan the new goal.
- `validate_blueprint_contract` fails: fix decomposer output before task plan creation.
- Coverage key missing from validation criteria: add bracketed criteria such as `VC1 [AC-1]: ...`.
- Hard constraint uncovered: add it to `coverage_map` and owning validation criteria.
- Soft constraint intentionally skipped: include `tradeoff_rationale`.
- Request (or part) already implemented: see Step 0.5 Already-Implemented Gate — off-ramp the whole-feature case, or move partial duplicates to spec "Out of Scope > Already Implemented" so decomposition skips them.
