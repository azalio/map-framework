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

## Runner-witnessed acceptance proofs

Plan an executable public-interface proof for every spec AC, including criteria absent from the blueprint. Preserve exact spec IDs: `AC-1` and `AC-001` are not interchangeable. Keep the AC-to-test mapping in `.map` artifacts, never product code or shipped test names. Citation coverage is not execution proof.

After independent TEST_WRITER authoring and RED, freeze each proof **before Actor**. This applies to single-subtask, batch, wave and resumed workflows. The orchestrator opens the initial authoring checkpoint when it returns TEST_WRITER; do not bypass it by editing state files. Example (substitute the actual spec ID, owning subtask, command and files):

```bash
python3 .map/scripts/map_step_runner.py freeze_acceptance_contract --json '{"ac_id":"AC-1","command":["python3","-m","pytest","tests/test_login.py"],"proof_files":["tests/test_login.py"],"subtask_id":"ST-001","author":"test-writer","authoring_stage":"test_first","cwd":".","timeout":300}'
```

Commands are argv arrays, not silently parsed shell strings. Use an explicit interpreter/script when shell semantics are required. Manual criteria use `command: null` with `manual_reason`; they remain `unproven`, not successful receipts. Freeze proof content, mode, command, cwd and timeout before implementation; do not re-freeze Actor edits.

After each freeze/revision, write `test_contract_<subtask>.md` and record a **fresh** `record_test_contract_handoff` before `validate_step "2.26"` or Actor admission, including batch/wave flows. The handoff binds the current checkpoint, contract hashes and test-contract digest; an old handoff cannot authorize revised tests.

```bash
python3 .map/scripts/map_step_runner.py record_test_contract_handoff ST-001 'python3 -m pytest tests/test_login.py' 'tests/test_login.py' 'Login boundary contract' '' --authoring-result red
```

`--authoring-result` accepts `red`, `already_green` or `plan_authored`; non-red outcomes require `--authoring-justification` explaining why. These authoring outcomes are explicitly **self_reported**, not runner-witnessed RED. Final acceptance still requires the runner proof protocol; no universal RED executor is implied. JSON callers may supply the same handoff fields through `--json`.

A legitimate test change returns to an **independent test-first** step before Actor resumes:

```bash
python3 .map/scripts/map_orchestrator.py request_acceptance_revision ST-001 --reason 'Correct the independently reviewed boundary assertion'
python3 .map/scripts/map_orchestrator.py begin_acceptance_authoring ST-001 --author test-writer --authoring-stage independent_test_first
python3 .map/scripts/map_step_runner.py revise_acceptance_contract --json '{"ac_id":"AC-1","command":["python3","-m","pytest","tests/test_login.py"],"proof_files":["tests/test_login.py"],"author":"test-writer","reason":"Correct the independently reviewed boundary assertion","assessment":"equivalent","authoring_stage":"independent_test_first"}'
```

`request_acceptance_revision` re-enters TEST_WRITER but grants no authoring authority. Dispatch the independent test writer before opening that revision checkpoint. Record author/provenance, timestamp, reason, old/new command and assertion/proof-file diff, and invalidated contracts/receipts. Independently assess assertion removal or narrowed command scope as `weakening`, with explicit `weakening_justification`; unknown impact remains unresolved and blocks completion. Hashes detect changes, not semantic equivalence. Never silently relabel weakening as safe or give legacy work retroactive test-first provenance.

If a stored revision is unresolved, open a fresh independent-test-first checkpoint for an independent reviewer and append an assessment (do not overwrite the original revision):

```bash
python3 .map/scripts/map_step_runner.py assess_acceptance_revision --json '{"ac_id":"AC-1","revision":2,"author":"reviewer","assessment":"weakening","reason":"Independent review complete","weakening_justification":"Explain why the narrower assertion still satisfies the approved requirement"}'
```

Use the real revision number and matching checkpoint author. Detected removals/command changes cannot be relabeled `equivalent`; the report preserves the original diff/verdict and all later assessments.

For a strictly additive pytest revision, request `assessment: "additive"` in either revision API. The runner, not the author, must prove that every previous frozen file entry (bytes, mode and recorded hash) and argv argument remains unchanged, cwd is identical, timeout does not decrease, and the only extra argv tokens are distinct new test-file targets backed exactly by added frozen proofs. Recognized commands are `pytest` or a Python executable with `-m pytest`, explicit repository-relative `test_*.py` / `*_test.py` files, and unchanged verbosity flags (`-q`, `--quiet`, `-v`, `--verbose`). New targets must be beside existing targets and have distinct basenames to avoid expanding pytest configuration/conftest discovery or import-name collisions. Selectors, directories, shell wrappers and other options are unsupported and stay blocked. This is a mechanical target-superset proof, not semantic equivalence: test imports/plugins can still affect execution. Stored runner evidence and live frozen files are revalidated at handoff, admission and completion. A previously `unknown` revision can be recovered with `assess_acceptance_revision` using its exact revision number and `assessment: "additive"`; no re-freeze or state-file edits are needed.

After implementation, existing gates and the intended final code commit, execute and consume runner evidence:

```bash
python3 .map/scripts/map_step_runner.py run_acceptance_proofs --json '{}'
python3 .map/scripts/map_step_runner.py evaluate_acceptance --json '{}'
python3 .map/scripts/map_step_runner.py write_acceptance_report --json '{}'
```

Use `ac_ids` to select proofs and `rerun: true` for a new attempt. Generate `write_verification_summary` and only then request `mark_workflow_complete`; implementation exhaustion alone is not accepted completion. The evaluator lists every AC as `proven`, `failed`, `unproven` or `stale` with reason and evidence binding. It consumes the latest admitted attempt, never a historical success after a failed rerun. `acceptance.strict` (or `MAP_STRICT_ACCEPTANCE`) blocks unproven ACs when enabled; the default is warn-first. Failed/stale evidence, integrity violations and unresolved executions always block.

Receipts bind full HEAD/index/dirty/untracked product snapshots plus contract/inventory/policy hashes. A new commit or relevant local change makes previous proofs stale: rerun after the final intended commit, not before it. Mutable `.map` output is excluded from product snapshots and bound separately. Verifiers consume `evaluate_acceptance`; they cannot turn manual checkboxes into proof. Frozen tests prevent accidental substitution, not vacuous assertions or hostile same-user rewriting. Execution is non-hermetic; external edit/change-restore races and process-group escape limitations still apply. Keep independent semantic review.

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

## PRD-quality Preflight

Offer `/map-prd-review` only for a clear PRD/requirements artifact, not an ordinary task
description. If accepted, follow that skill with the original input. A non-ready review
must show its readiness score, top strengths, critical/major weaknesses, and
high-priority uncovered edge cases before asking whether to proceed or revise.

**Existing review short-circuit:** when `.map/<branch>/prd-review.json` already exists
for the same PRD source (its `prd_source` matches the current input), do NOT re-offer
the preflight. Surface the recorded verdict and readiness score, then follow the
matching reuse state:

- `ready_for_plan` — continue planning.
- `planning_decision: proceed_anyway` — continue planning and carry the recorded gaps
  as `PRD-GAP-N` entries, as if the decision had just been made.
- `planning_decision: stop_for_revision` — stop planning; the operator asked for a
  revised PRD first.
- non-ready review with **no** recorded `planning_decision` (the operator never
  answered) — summarize the stored review and ask the required proceed/stop decision
  WITHOUT re-running the review.

Re-offer the preflight only when the PRD source changed since the recorded review.
"Changed" means content, not just the path: an edited document at the same
`prd_source` path is a changed source — a stale review must not silently stand in for
a revised document.

For **continue planning anyway**, persist the explicit user override:

```bash
python3 .map/scripts/map_step_runner.py record_prd_review_decision proceed_anyway \
  --rationale "User explicitly chose to continue planning with the reported PRD score and verdict."
```

Then carry every finding, blocking question, uncovered edge case, suggested revision,
and route recommendation into the spec's Open Questions / Risks as stable `PRD-GAP-N`
entries. Deduplicate overlapping items without dropping their evidence or suggested
handling. For each dependent subtask, put `Provisional — blocked on PRD-GAP-N` in both
its description and validation criteria until the gap is resolved; do not invent an
unsupported blueprint field.

For **stop and revise**, persist the choice and stop planning:

```bash
python3 .map/scripts/map_step_runner.py record_prd_review_decision stop_for_revision \
  --rationale "User chose to stop planning and revise the PRD."
```

The artifact keeps `ready_for_plan: false`; `planning_decision: proceed_anyway` records
accepted uncertainty, not retroactive readiness.

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
