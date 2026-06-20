# /map-plan Supporting Reference

This file holds templates, examples, and troubleshooting for `/map-plan` so the invoked `SKILL.md` stays focused on the active planning flow.

## Spec Template

````markdown
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

## Requirements Index

This block IS the visible, authoritative requirements section — NOT a hidden parallel artifact.
Do not maintain a separate list elsewhere; update this block whenever criteria change.
Downstream tooling (the forward-completeness gate) locates the index ONLY by the sentinel pair
below; a sentinel-shaped string in prose outside the fenced block is ignored.

Rules:
- `kind` is a CLOSED vocabulary: `acceptance_criterion` | `invariant` | `hard_constraint` | `cross_cutting`
- `id` is canonical: prefix in {AC, INV, HC, CCR}, a hyphen, then digits with NO leading zeros, uppercase prefix
  (e.g. `AC-1` not `ac-01`, `INV-2` not `INV-02`)

<!-- mapify:requirements-index:v1 -->
```yaml
requirements:
  - id: AC-1
    kind: acceptance_criterion
  - id: INV-1
    kind: invariant
  - id: HC-1
    kind: hard_constraint
```
<!-- /mapify:requirements-index:v1 -->

## Security Boundaries
- Trust boundaries and sensitive flows.

## Out of Scope
- Explicit exclusions.

### Already Implemented
- Feature parts the request asked for that already exist, each with `file:line` proof. The decomposer must NOT create subtasks for these (see Step 0.5: Already-Implemented Gate).

## Open Questions
- Questions that must be answered before decomposition or execution.
````

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

## Verify Live/Runtime State

Detail for **Step 0.6** (gated on `depends_on_runtime_state=true`). Static discovery (Step 0 / Step 0.5) reads only the repo; it cannot see prod row counts, the enum labels actually present in a live DB, a column that already exists, the applied migration head, or a live feature-flag value. When a plan's correctness rests on those, verify them empirically or record the exact check — never copy them from a design doc as fact.

**Signals that the plan depends on runtime state** (any one arms the gate):
- a DB schema/data migration or a data backfill;
- "measured on prod" / "currently" / "as of" numbers in the source request;
- count-based acceptance criteria **referencing current state** (e.g. "migrate the 10k existing rows"), not a forward design target ("handle 1k RPS");
- a feature-flag / config cutover, or capacity / latency assumptions about the running system;
- "this column/table/enum value already exists" claims.

**Contract per assumption:**

| Situation | Action |
|---|---|
| Verifiable read-only now | Confirm via an approved read-only source (read replica, dashboard, runbook, `INFORMATION_SCHEMA` / `pg_enum` / migration-head introspection). Record the **fact** + its source. |
| Prod unreachable / not checked | Record an `Unverified Runtime Assumption` under spec Open Questions / Risks with the **exact read-only check** + safe source; mark dependent subtasks `provisional`. |

**Safety guardrails (the gate suggests checks; it does not run them):**
- Prefer bounded / metadata queries (`INFORMATION_SCHEMA`, `pg_class` reltuples estimate, `EXISTS (SELECT 1 … LIMIT 1)`, migration-head table, flag-service lookup) over full scans / `COUNT(*)` on large tables.
- Never write, mutate, enqueue jobs, flip flags, or run migrations. Read-only, on a replica where possible, with a timeout.
- Cite the derived fact, not the raw rows. Do NOT paste PII, secrets, credentials, or bulky output into the spec or `.map/<branch>/` artifacts — they may be committed.
- No isolation-level / `NOLOCK` / dirty-read hints.

Runtime state is broader than SQL: feature flags, dashboards, external-service config, cloud resources, deployment/cutover state, and observability data all count.

**Example — record an unverified runtime assumption (prod unreachable):**

```text
Unverified Runtime Assumption (-> spec Open Questions / Risks):
  - Claim:   `type` enum has 15 labels (taken from the Go constants).
    Why it matters: ST-002 abort-on-unmapped mapping enumerates the labels.
    Status:  UNVERIFIED (no prod access this session).
    Check:   read-only `SELECT enumlabel FROM pg_enum
             JOIN pg_type t ON t.oid=enumtypid WHERE t.typname='type';`
             run on a read replica.
    Impact:  ST-002, ST-003 marked provisional until the live label set is confirmed.
```

**Example — verified read-only:**

```text
Verified Runtime Fact:
  - `priority` column already exists on `items` (source: INFORMATION_SCHEMA on read replica).
    Impact: migration uses ADD COLUMN IF NOT EXISTS; ST-006 must not overwrite existing values.
```

## Troubleshooting

- Plan depends on runtime/production state: set `depends_on_runtime_state=true` at the Workflow-Fit Gate and run Step 0.6 (Verify Live/Runtime State). Verify each assumption read-only, or record it as an `Unverified Runtime Assumption` with the exact check and mark dependent subtasks `provisional`. Remember Step 0.5 (`file:line`) proves the code exists, not that the migration/flag is applied in prod.
- Existing `step_state.json`: planning already completed; print checkpoint and stop — but only when the Resume-Detection `verdict` is `resume`. The `.map/<branch>/` layout is single-plan-per-branch, so a branch can host several sequential plans over its lifetime; `check_plan_resume "$ARGUMENTS"` compares the prior plan's goal against the current request and returns `goal_mismatch` when they differ. On `goal_mismatch`, do NOT report "plan complete" and do NOT overwrite the prior `spec`/`blueprint`/`task_plan`; archive or rename the existing `.map/<branch>/` artifacts (or plan on a fresh branch) with operator confirmation, then plan the new goal.
- `validate_blueprint_contract` fails: fix decomposer output before task plan creation.
- Coverage key missing from validation criteria: add bracketed criteria such as `VC1 [AC-1]: ...`.
- Hard constraint uncovered: add it to `coverage_map` and owning validation criteria.
- Soft constraint intentionally skipped: include `tradeoff_rationale`.
- Request (or part) already implemented: see Step 0.5 Already-Implemented Gate — off-ramp the whole-feature case, or move partial duplicates to spec "Out of Scope > Already Implemented" so decomposition skips them.
