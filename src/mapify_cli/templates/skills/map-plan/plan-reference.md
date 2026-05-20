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

## Troubleshooting

- Existing `step_state.json`: planning already completed; print checkpoint and stop.
- `validate_blueprint_contract` fails: fix decomposer output before task plan creation.
- Coverage key missing from validation criteria: add bracketed criteria such as `VC1 [AC-1]: ...`.
- Hard constraint uncovered: add it to `coverage_map` and owning validation criteria.
- Soft constraint intentionally skipped: include `tradeoff_rationale`.
