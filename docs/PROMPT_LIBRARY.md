# MAP Prompt Library

Copyable prompt recipes for common engineering tasks, grouped by SDLC phase.
Each recipe includes the typed prompt, fillable slots, recommended MAP surface,
prerequisites, why the pattern works, and what artifact to expect as a completion signal.

> **Origin note**: patterns are translated from [Claude Code Prompt Library](https://code.claude.com/docs/en/prompt-library.md)
> and cross-checked against MAP's shipped skills. Internal agent/skill prompt bodies
> are NOT changed here — only user-facing recipes and a source-coverage audit table.

---

## Quick-reference index

| Phase | Recipe | Role | Surface |
|---|---|---|---|
| [Understand](#understand) | Understand a module before touching it | Engineer | `/map-explain` |
| [Understand](#understand) | Impact analysis before deleting code | Engineer | `/map-explain` |
| [Understand](#understand) | Orient a new contributor to the repo | Maintainer | `/map-explain` |
| [Plan](#plan) | Plan a multi-file refactor before writing code | Engineer | `/map-plan` |
| [Plan](#plan) | Spec by interview: extract implicit requirements | Tech Lead | `/map-plan` |
| [Plan](#plan) | Map edge cases at plan time, not after | Engineer | `/map-plan` |
| [Build](#build) | Implement from an existing pattern | Engineer | `/map-efficient` |
| [Build](#build) | Fix a failing test: structured debug | Engineer | `/map-debug` |
| [Build](#build) | Test-first for a new module | Engineer | `/map-tdd` |
| [Build](#build) | Fast path for a tiny, low-risk change | Engineer | `/map-fast` |
| [Review](#review) | Review uncommitted changes before pushing | Tech Lead | `/map-review` |
| [Review](#review) | Quality gate after a rough session | Operator | `/map-check` |
| [Learn](#learn) | Persist lessons after a complex workflow | Engineer | `/map-learn` |
| [Learn](#learn) | Resume after context exhaustion | Engineer | `/map-resume` |

---

## Understand

### Recipe 1 — Understand a module before touching it

**Roles**: Engineer

```
/map-explain
Walk me through <MODULE_OR_FILE> so I can understand it before I change it.
Cover: what it does, its public API surface, its dependencies, and any non-obvious
invariants I should preserve. Stop at explanation — do not implement anything.
```

**Slots**

| Slot | Example |
|---|---|
| `<MODULE_OR_FILE>` | `src/mapify_cli/install_manifest.py`, `the delivery subsystem`, `the state-machine in map_orchestrator.py` |

**Prerequisites**: none

**Why it works**: Separates understanding from implementation. Asking the agent to explicitly stop at explanation prevents premature code changes and forces it to surface invariants you might otherwise violate.

**Completion signal**: The agent produces a narrative summary (no file changes, no `.map/` artifacts written).

---

### Recipe 2 — Impact analysis before deleting code

**Roles**: Engineer

```
/map-explain
Before I delete <SYMBOL_OR_FILE>, show me every caller, every test that covers it,
and any doc references. Include indirect callers (functions that call functions that
use it). After the report, stop — do not remove anything.
```

**Slots**

| Slot | Example |
|---|---|
| `<SYMBOL_OR_FILE>` | `build_manifest()`, `.claude/hooks/workflow-gate.py`, `the CodexProvider class` |

**Prerequisites**: none

**Why it works**: Deletion is irreversible. An explicit pre-deletion impact report surfaces hidden callers that file-search would miss and forces you to see the blast radius before committing to the change.

**Completion signal**: Agent lists callers and coverage with file:line references; nothing modified.

---

### Recipe 3 — Orient a new contributor to the repo

**Roles**: Maintainer, Tech Lead

```
/map-explain
Give a new contributor a 10-minute orientation to this repo.
Cover: primary purpose, directory layout, how to run tests, the main
data-flow from <ENTRY_POINT> to <KEY_OUTPUT>, and the three most important
invariants they must not break. Assume Python familiarity, no prior exposure
to this codebase.
```

**Slots**

| Slot | Example |
|---|---|
| `<ENTRY_POINT>` | `mapify init`, `the CLI entry point`, `the map_orchestrator` |
| `<KEY_OUTPUT>` | `the generated .claude/ tree`, `blueprint.json`, `the install manifest` |

**Prerequisites**: none

**Why it works**: A role-tagged prompt ("new contributor", "10-minute") constrains scope and audience, producing a structured digest rather than an exhaustive API dump. Naming the invariants forces the agent to surface load-bearing constraints.

**Completion signal**: Agent produces a bounded narrative. No files modified.

---

## Plan

### Recipe 4 — Plan a multi-file refactor before writing code

**Roles**: Engineer

```
/map-plan
I want to <DESCRIBE_GOAL>. Before touching any code:
1. Research which files are affected and what their current contracts are.
2. Decompose into atomic subtasks that each touch the fewest files possible.
3. Flag any subtask where a change in one file forces a change in another (coupling risk).
4. Stop at the blueprint — do not implement.
Target: the plan should be reviewable in under 5 minutes.
```

**Slots**

| Slot | Example |
|---|---|
| `<DESCRIBE_GOAL>` | `rename the ConfigEntry dataclass to OwnershipEntry across the codebase`, `split install_manifest.py into two modules`, `migrate from JSON to TOML config` |

**Prerequisites**: none

**Why it works**: Outcome-first framing ("research → decompose → flag coupling → stop") gives the agent an explicit checklist. The 5-minute reviewability constraint prevents over-decomposition.

**Completion signal**: `.map/<branch>/blueprint.json` + `spec_<branch>.md` written; no source files changed.

---

### Recipe 5 — Spec by interview: extract implicit requirements

**Roles**: Tech Lead

```
/map-plan
The goal is: <ROUGH_GOAL>
Before writing a spec, ask me up to 5 clarifying questions — one at a time —
to surface implicit requirements, stakeholder constraints, and non-goals.
After I answer, write a concise spec and then a blueprint. Do not assume answers;
wait for my response to each question before proceeding.
```

**Slots**

| Slot | Example |
|---|---|
| `<ROUGH_GOAL>` | `add an uninstall command to mapify`, `make the provider config merge reversible`, `add a prompt library to the docs` |

**Prerequisites**: none

**Why it works**: Sequential questioning prevents the agent from assuming answers to ambiguous requirements. Explicit "one at a time" avoids a wall of questions. This is especially useful when the spec author is also the implementer and tends to skip documenting unstated assumptions.

**Completion signal**: `spec_<branch>.md` captures the agreed-on requirements; blueprint follows.

---

### Recipe 6 — Map edge cases at plan time, not after

**Roles**: Engineer

```
/map-plan
For the goal "<FEATURE_OR_CHANGE>", before generating subtasks:
List every edge case that could cause a test to fail or a user to lose data.
Group them into: (a) must be handled, (b) should be documented, (c) out of scope.
Use this list as the basis for acceptance-criteria entries in the blueprint.
```

**Slots**

| Slot | Example |
|---|---|
| `<FEATURE_OR_CHANGE>` | `the mapify uninstall command`, `the config-entry scan at manifest build time`, `the MCP server removal logic` |

**Prerequisites**: none

**Why it works**: Edge cases found at plan time cost far less than edge cases found in review or production. The three-bucket grouping forces explicit scoping decisions rather than leaving them as implicit assumptions.

**Completion signal**: Acceptance criteria in `blueprint.json` contain edge-case coverage entries.

---

## Build

### Recipe 7 — Implement from an existing pattern

**Roles**: Engineer

```
/map-efficient
Implement <NEW_FEATURE> following the same pattern as <REFERENCE_IMPLEMENTATION>.
Before writing any code: read both files and confirm the pattern is actually applicable.
Match the naming conventions, error handling style, and test structure exactly.
Deviation from the pattern must be explicitly justified in a code comment.
```

**Slots**

| Slot | Example |
|---|---|
| `<NEW_FEATURE>` | `_scan_statusline_config_entry`, `the CodexProvider.install() method`, `the ReconcileResult dataclass` |
| `<REFERENCE_IMPLEMENTATION>` | `_scan_mcp_config_entries`, `ClaudeProvider.install()`, `InstallManifest` |

**Prerequisites**: A prior `/map-plan` is recommended for changes touching more than 3 files.

**Why it works**: A reference implementation anchors naming, structure, and error handling, dramatically reducing style drift. The explicit "read both files first" guard prevents the agent from guessing the pattern from context alone.

**Completion signal**: New code mirrors the pattern; tests follow the same fixture structure.

---

### Recipe 8 — Fix a failing test: structured debug

**Roles**: Engineer

```
/map-debug
This test is failing: <TEST_NAME_OR_FILE>
Error: <PASTE_ERROR_OR_DESCRIBE_SYMPTOM>

Investigate in phases — do not jump to a fix:
1. Reproduce: confirm you can make it fail deterministically.
2. Isolate: identify the exact line/condition causing the failure.
3. Fix: make the minimal change that makes it pass.
4. Verify: run the test suite to confirm no regressions.
```

**Slots**

| Slot | Example |
|---|---|
| `<TEST_NAME_OR_FILE>` | `tests/test_install_manifest.py::TestVC13ReconcileMcpRemove::test_removes_map_owned_server` |
| `<PASTE_ERROR_OR_DESCRIBE_SYMPTOM>` | `AssertionError: assert [] != []`, `KeyError: 'mcpServers'`, `the test passes locally but fails in CI` |

**Prerequisites**: none

**Why it works**: The four explicit phases prevent the most common debugging failure mode: jumping to a fix before understanding the root cause. Phase isolation means the agent cannot mark the task done until it has a reproducible failure and a verified fix.

**Completion signal**: Test passes; `/map-debug` verifies the full suite has no regressions.

---

### Recipe 9 — Test-first for a new module

**Roles**: Engineer

```
/map-tdd
I need to add <MODULE_OR_FEATURE>. The spec is in <SPEC_FILE_OR_INLINE_SPEC>.
Follow strict RED-GREEN-REFACTOR:
1. RED: write failing tests covering all acceptance criteria. Run them. Confirm each fails.
2. GREEN: write the minimal implementation that makes them pass.
3. REFACTOR: clean up only — no new behavior.
Do not write implementation code before step 2.
```

**Slots**

| Slot | Example |
|---|---|
| `<MODULE_OR_FEATURE>` | `reconcile_config`, `the ConfigEntry dataclass and its scan functions`, `the mapify uninstall command` |
| `<SPEC_FILE_OR_INLINE_SPEC>` | `.map/<branch>/spec_<branch>.md`, the acceptance criteria listed inline |

**Prerequisites**: A spec or plan (`/map-plan` output) is strongly recommended. `/map-tdd` reads `spec_<branch>.md` if present.

**Why it works**: Forcing the test to fail before writing implementation code prevents the common failure of writing tests that pass because they don't actually test the feature. Explicit phase naming prevents rationalizations like "the test is already conceptually passing."

**Completion signal**: `test_contract_ST-NNN.md` written in RED phase; tests green after GREEN phase; diff is minimal (no speculative additions).

---

### Recipe 10 — Fast path for a tiny, low-risk change

**Roles**: Engineer

```
/map-fast
Make the following small change: <CHANGE_DESCRIPTION>
Constraints: touch only <MAX_FILES> file(s); do not refactor anything outside
the change; run `make check` at the end and confirm it passes.
```

**Slots**

| Slot | Example |
|---|---|
| `<CHANGE_DESCRIPTION>` | `fix the typo in the ConfigEntry docstring`, `add a missing type annotation to read_manifest`, `update the version number in pyproject.toml` |
| `<MAX_FILES>` | `1`, `2` |

**Prerequisites**: Scope must be clearly bounded. If the change touches more than 3 files or involves any interface change, use `/map-efficient` instead.

**Why it works**: `/map-fast` skips Predictor and Reflector to save 40–50% of tokens. Stating the file-count constraint explicitly prevents the agent from expanding scope under the assumption that cleanup is "free."

**Completion signal**: `make check` passes; diff is narrow.

---

## Review

### Recipe 11 — Review uncommitted changes before pushing

**Roles**: Tech Lead, Engineer

```
/map-review
Review my uncommitted changes against the acceptance criteria in <SPEC_OR_ISSUE>.
Check in this order:
1. Spec compliance: does every acceptance criterion have a concrete implementation?
2. Test coverage: is each new behavior covered by at least one test?
3. Code quality: naming, error handling, no unnecessary complexity.
4. Regressions: anything in the diff that could silently break existing behavior?
Flag each finding with file:line. Stop if you find a P0 issue — do not summarize past it.
```

**Slots**

| Slot | Example |
|---|---|
| `<SPEC_OR_ISSUE>` | `.map/<branch>/spec_<branch>.md`, `GitHub issue #314`, the acceptance criteria stated inline |

**Prerequisites**: Changes staged or unstaged in the working tree; a spec or issue for compliance checking.

**Why it works**: Ordered review phases prevent code-quality commentary from drowning out spec-compliance failures. The "stop at P0" instruction prevents the agent from burying a showstopper in a list of minor suggestions.

**Completion signal**: `code-review-001.md` written to `.map/<branch>/`. Optionally creates `pr-draft.md`.

---

### Recipe 12 — Quality gate after a rough session

**Roles**: Operator, Engineer

```
/map-check
Run all quality gates: lint, type-check, and tests. Report:
- What passed
- What failed with file:line
- Whether any failure is new (not present on main) or pre-existing
Do not fix anything — only report. I will decide what to fix.
```

**Prerequisites**: none

**Why it works**: A read-only gate run is safe to run at any time and produces a clean baseline before any fix pass. The "do not fix" instruction prevents the agent from introducing additional changes while the workspace is in a partially-broken state.

**Completion signal**: `verification-summary.md` written; agent reports counts (N passed, M failed, K new failures).

---

## Learn

### Recipe 13 — Persist lessons after a complex workflow

**Roles**: Engineer, Maintainer

```
/map-learn
This workflow is complete. Extract the most important lessons into reusable rules.
Focus on:
- Anything that surprised you or caused a retry
- Invariants that weren't documented but turned out to matter
- Any pattern you'd want the next implementer to know before starting
Write rules that are specific enough to prevent the same mistake — not platitudes.
```

**Prerequisites**: A completed `/map-efficient`, `/map-debug`, or `/map-review` session. If `learning-handoff.md` exists in `.map/<branch>/`, it is loaded automatically.

**Why it works**: The specificity constraint ("not platitudes") is the critical part. Without it, post-workflow lessons tend toward generic advice ("test your code"). Naming the failure class and the concrete fix creates actionable rules that persist in `.claude/rules/learned/`.

**Completion signal**: Rules appended to the appropriate file in `.claude/rules/learned/` (e.g. `architecture-patterns.md`, `error-patterns.md`).

---

### Recipe 14 — Resume after context exhaustion

**Roles**: Engineer

```
/map-resume
Resume the workflow from the last checkpoint. Before continuing:
1. Read step_state.json and tell me which subtask we were on and its status.
2. Read the most recent diff to confirm what was committed vs. in-progress.
3. Continue from the next pending subtask.
Do not re-run subtasks that are already in state "completed".
```

**Prerequisites**: An in-progress `/map-efficient` session with `.map/<branch>/step_state.json` written. The branch must be checked out.

**Why it works**: Explicit state-read before continuation prevents the agent from re-running already-completed subtasks, which would produce duplicate edits or conflicts. Naming the "completed" check makes the guard explicit rather than implicit.

**Completion signal**: Agent reports the resume point and continues to the next pending subtask without re-doing prior work.

---

## Prompt-pattern audit table

This table classifies Claude Code Prompt Library source patterns against MAP's existing surfaces.

| Pattern | Description | MAP status | Evidence |
|---|---|---|---|
| Outcome-first framing | Describe what you want, not how to do it | **Implemented** | All MAP skill descriptions use goal-first language; `map-plan` prompt builder injects goal statement before decomposition instructions |
| Explicit verification loop | Tell the agent how to verify its work | **Implemented** | `validate_blueprint_contract`, `verify_prior_stage_consumption`, `map-check` gate, per-subtask verification criteria in `blueprint.json` |
| Reference/artifact handling | Point the agent at existing code or docs | **Implemented** | `research-agent` produces `ResearchEvidence`; Actor reads `research/<subtask>.md` before writing code |
| Measurable targets | Token budgets, file counts, test pass rates | **Implemented** | `token_budget.json`, `mapify minimality-report`, `map-tokenreport`, blueprint `acceptance_criteria` with numeric thresholds |
| Output format/audience | Specify the desired answer format | **Implemented** | All agent prompts specify JSON output contracts; `review-bundle.json` schema enforced; `SKILL.md` frontmatter |
| Prerequisite disclosure | Label required external tools | **Docs-only gap** | MAP skills do not consistently label prerequisites (`gh`, `git`, `claude` CLI) in their SKILL.md frontmatter. Recipe headers above fill this gap; SKILL.md frontmatter is a candidate follow-up enhancement via `mapify skill-eval`. |
| Memory/learning follow-up | Persist what you learned for next time | **Implemented** | `/map-learn`, `/map-memory-now`, `learning-handoff.md` auto-written after major workflows; `.claude/rules/learned/` persisted rule store |
| Role tags | Tag prompts by user role (engineer, PM, ops) | **Docs-only gap** | README and USAGE.md are command-centric; no explicit role-tagged prompt catalog existed before this file. |
| Phase/category grouping | Group prompts by SDLC phase | **Docs-only gap** | README lists commands sequentially; no phase-grouped prompt catalog existed before this file. |

**Legend**
- **Implemented** — pattern is active in MAP's shipped code or agent prompts
- **Docs-only gap** — missing from user-facing docs but not from internal agent prompts; safe to fill with documentation
- **Internal-prompt eval candidate** — a change to internal agent/skill prompt bodies; requires A/B or `mapify skill-eval` measurement before shipping

---

## Guardrails for prompt improvements

Before editing any internal agent or skill prompt body based on inspiration from this catalog or the source Prompt Library:

1. **Docs/examples only**: add recipes here, update USAGE.md, fix README. No agent prompt body changes needed.
2. **SKILL.md `description:` tuning**: use `mapify skill-eval` to measure trigger accuracy before and after.
3. **Internal MAP agent prompts** (Actor, Monitor, Decomposer, etc.): require an explicit A/B plan or whole-skill eval. See `docs/whole-skill-optimization-notes.md` for the methodology. Do not treat these as prose cleanup.
4. **Template changes**: edit `src/mapify_cli/templates_src/**/*.jinja`, then run `make render-templates` and `make check-render`.
