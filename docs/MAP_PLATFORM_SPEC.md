# MAP Framework Platform Refactor Spec

**Status:** Proposed  
**Date:** 2026-03-23  
**Target:** `map-framework` next major platform iteration

## Summary

MAP Framework has a strong execution model: specialized agents, explicit quality gates, branch-scoped workflow artifacts, and a usable `/map-plan` -> `/map-efficient` -> `/map-check` loop.

The main weakness is not execution quality. The main weakness is that too much product behavior is encoded in large prompt files, large installer codepaths, and hand-maintained runtime conventions. This makes the framework harder to evolve, harder to customize, and harder to extend beyond its current Claude Code-first delivery model.

This spec proposes a platform refactor that keeps MAP's workflow philosophy intact while making the system:

- declarative instead of prompt-hardcoded
- configurable instead of template-edited
- adapter-driven instead of delivery-coupled
- schema-validated instead of convention-only
- upgradable without blind overwrite

## Problem Statement

The current platform has five structural problems.

### 1. Workflow behavior is too hardcoded

Core behavior currently lives across:

- installer/runtime code in `src/mapify_cli/__init__.py`
- orchestrator logic in `src/mapify_cli/templates/map/scripts/map_orchestrator.py`
- long command prompts such as `.claude/commands/map-efficient.md`

This makes workflow changes expensive because behavior is split between Python, markdown prompts, hooks, and docs.

### 2. The execution engine is tightly coupled to Claude delivery

`mapify init` currently installs one concrete delivery shape: `.claude/agents`, `.claude/commands`, `.claude/hooks`, `.claude/settings.json`, `.claude/workflow-rules.json`.

That works, but it means the platform layer and the delivery layer are effectively the same thing. As a result:

- prompt structure becomes platform architecture
- update behavior is file-copy based
- future support for other assistants would multiply template debt

### 3. Customization requires source edits instead of configuration

Today, most meaningful customization still means editing shipped templates or project files directly.

MAP needs a first-class configuration layer for:

- workflow profile selection
- repo-specific context
- verification commands and gates
- risk thresholds
- research/guard defaults
- delivery toggles

### 4. `.map/<branch>/` is useful but under-specified as a platform contract

The `.map/<branch>/` directory already carries the right idea: persistent workflow state and artifacts that survive context resets.

However, only part of that contract is formally defined. The platform still relies on a mix of:

- JSON files with partial schema coverage
- markdown files with implicit structure
- runtime assumptions spread across hooks, commands, and scripts

This makes resume, migration, CI integration, and tooling interoperability less reliable than they should be.

### 5. Upgrade semantics are too coarse

`mapify upgrade` refreshes shipped files, but it does not provide a robust managed-update model:

- generated files do not have a complete metadata contract
- drift detection is limited
- local customization and generated content are not clearly separated
- upgrade behavior is closer to "refresh templates" than "reconcile managed artifacts"

## Goals

The refactor must achieve the following goals.

### G1. Introduce a declarative workflow model

MAP workflows must be representable as data, not only as prompt prose.

### G2. Separate platform engine from delivery adapters

The workflow runtime must be independent from the specific assistant integration layer.

### G3. Add first-class project configuration and profiles

Users must be able to tune behavior through config files, not prompt surgery.

### G4. Formalize `.map/<branch>/` as a stable artifact contract

Workflow state, planning outputs, validation results, and handoff artifacts must have explicit schemas and lifecycle rules.

### G5. Make updates managed and version-aware

Generated files must carry metadata so `mapify upgrade` can detect drift, refresh safely, and distinguish generated content from local edits.

### G6. Preserve MAP's existing strengths

The refactor must preserve:

- the MAP planning/execution/validation loop
- branch-scoped persistence
- state-gated orchestration
- guardrails and hooks
- the current default Claude Code experience

## Landscape Analysis: OpenSpec as Reference

OpenSpec (Fission-AI/OpenSpec) is an open-source spec framework that solves a related but different problem: it structures *what to build* before code is written. Analyzing OpenSpec reveals mature patterns that MAP can adopt for its platform layer without changing its workflow philosophy.

### What OpenSpec does well that MAP should learn from

**Schema-driven artifact DAGs.** OpenSpec defines workflow schemas as YAML files where artifacts form a directed acyclic graph with topological sort. Artifact state is determined by filesystem existence (BLOCKED → READY → DONE), not runtime flags. Dependencies are enablers, not gates. This is a proven implementation of the pattern MAP proposes in Section 1, and MAP should adopt a similar model for workflow phase graphs.

**Schema management CLI.** OpenSpec provides `schema init`, `schema fork`, `schema validate`, `schema which` with clear precedence resolution (CLI flag → change metadata → project config → default). MAP should consider an analogous `mapify workflow inspect` / `mapify workflow validate` surface.

**Context injection via structured config.** OpenSpec's `config.yaml` separates `context:` (injected into all artifacts) from `rules:` (per-artifact only). This is more reliable than freeform CLAUDE.md blocks because injection is deterministic. MAP's project config (Section 3) should adopt a similar structured injection model.

**Multi-tool delivery with capability metadata.** OpenSpec supports 20+ AI assistants via per-tool adapter metadata that declares path patterns and scope support per delivery surface (skills, commands). This validates MAP's adapter layer design (Section 5) and provides a concrete reference for capability metadata shape.

**Three-dimensional verification.** OpenSpec's `/opsx:verify` validates Completeness, Correctness, and Coherence as separate dimensions. MAP already has Monitor/Predictor agents doing similar work, but formalizing verification dimensions in the artifact contract would improve consistency.

**Migration with legacy detection.** OpenSpec detects legacy files, strips managed markers while preserving user content, and supports `--force` for CI. MAP's upgrade model (Section 9) should adopt similar precision.

### Where MAP and OpenSpec fundamentally differ

| Aspect | OpenSpec | MAP |
|--------|----------|-----|
| Core problem | Agree on *what* to build before code | Execute *how* to build with quality gates |
| Workflow model | Fluid actions, no phase gates | Structured phases with hard-stop gates |
| Agent architecture | Single AI assistant, human-guided | Multi-agent (Actor, Monitor, Predictor, Evaluator) |
| Quality enforcement | Verify is advisory, doesn't block | Monitor `valid=false` is a hard stop |
| Artifact scope | Specs, proposals, design docs | Execution state, blueprints, verification results |
| Branch awareness | Change folders (non-git) | `.map/<branch>/` (git-branch-scoped) |
| Orchestration | Dependency graph on artifacts | State-machine on execution phases |

### What MAP should NOT adopt from OpenSpec

- **Fluid/no-gate philosophy.** MAP's strength is structured gates. Making them advisory would weaken quality enforcement.
- **Delta spec model.** Irrelevant to MAP — MAP doesn't manage behavioral specifications, it manages execution artifacts.
- **Archive lifecycle.** MAP's branch-scoped artifacts already have clear lifecycle via git branch deletion.

## Non-Goals

This spec does not propose:

- replacing MAP's agent architecture
- removing Claude Code support or making it secondary
- building multi-assistant support in the first implementation phase
- redesigning every prompt from scratch
- changing the user-facing philosophy from structured execution to freeform specing

## Design Principles

### Declarative before procedural

Workflow sequencing, gates, retries, and artifact requirements should be declared in data and interpreted by runtime code.

### Thin prompts, thick runtime contracts

Prompt files should describe the local reasoning task. They should not be the primary storage location for orchestration rules.

### Managed generation with explicit ownership

Generated files should state:

- what generated them
- which workflow/profile they belong to
- which template version they came from
- whether local divergence exists

### Single source of truth per concern

- workflow sequencing: workflow schema + runtime state
- project defaults: project config
- branch execution state: `.map/<branch>/`
- delivery-specific rendering: adapter

## Proposed Architecture

## 1. Workflow Schema Layer

Introduce a workflow schema format, stored under a new directory such as:

```text
src/mapify_cli/workflows/
  core/
    plan.yaml
    efficient.yaml
    check.yaml
    resume.yaml
```

Each workflow schema should define:

- workflow id
- description
- entry command
- required artifacts
- phases
- phase ordering and dependency graph
- conditional phase rules
- retry policy
- stuck-recovery policy
- per-wave guard policy
- final verification policy
- resume semantics

### Phase dependency model (informed by OpenSpec's artifact DAG)

OpenSpec demonstrates that a dependency graph with topological sort and filesystem-based state detection is both sufficient and robust. MAP should adopt a similar model for phase ordering.

Key design choices:

- **Phases form a DAG**, not a linear sequence. Some phases can run in parallel when their dependencies are satisfied.
- **Phase state is derived from `.map/<branch>/` artifacts**, not runtime flags. A phase is DONE when its output artifact exists and validates. A phase is READY when all predecessor phases are DONE. A phase is BLOCKED otherwise.
- **Dependencies are hard gates in MAP** (unlike OpenSpec where they are enablers). If Monitor returns `valid=false`, the dependent phases cannot proceed.
- **Schema resolution precedence**: workflow schema defaults → project config overrides → CLI flags (highest priority).

### Schema validation and introspection

Following OpenSpec's `schema validate` / `schema which` pattern, MAP should expose:

- `mapify workflow list` — show available workflow schemas
- `mapify workflow show <id>` — display phase graph and dependencies
- `mapify workflow validate <id>` — check schema for circular dependencies, missing artifact producers, unreachable phases

Example shape:

```yaml
id: map-efficient
version: 1
entry: /map-efficient

requires:
  - blueprint
  - task_plan

phases:
  - id: research
    run_if: "risk == high or existing_files >= 3"
    actor: research-agent
    produces: repo_insight
    requires: []

  - id: actor
    actor: actor
    produces: implementation
    requires: [research]    # skipped if research was skipped

  - id: monitor
    actor: monitor
    produces: review_result
    requires: [actor]
    retry:
      max_attempts: 5
      stuck_recovery_at: 3
    gate: hard              # valid=false blocks downstream

guards:
  per_wave:
    checks:
      - tests
      - lint

final_verification:
  run_if: "has_high_risk_subtasks or subtask_count >= 5"

state_detection:
  method: artifact_existence  # check .map/<branch>/ for outputs
```

This layer is the biggest structural upgrade in the entire refactor.

## 2. Workflow Engine

Move orchestration into a dedicated runtime package, for example:

```text
src/mapify_cli/workflow_engine/
  loader.py
  validator.py
  graph.py
  executor.py
  state_store.py
  policies.py
```

Responsibilities:

- load workflow schemas
- validate them
- compute next executable phase
- enforce dependencies and retries
- persist and restore workflow state
- evaluate guard and recovery policies
- expose machine-readable commands for prompts/hooks

The existing `map_orchestrator.py` should become a thin CLI wrapper around this engine, not the canonical implementation.

## 3. Project Configuration

Introduce a project config file, for example:

```text
mapify.yaml
```

or:

```text
.map/config.yaml
```

Initial supported configuration should include:

- active profile
- enabled workflows
- repo context (injected into all agent prompts)
- per-phase rules (injected only into matching phase prompts)
- verification commands
- research defaults
- risk thresholds
- guard policy tuning
- MCP defaults
- delivery settings
- language preference

### Context injection model (informed by OpenSpec)

OpenSpec demonstrates that separating `context` (global) from `rules` (per-artifact) provides reliable, deterministic injection:

- **`context`** appears in every agent prompt — tech stack, conventions, constraints.
- **`rules`** appear only in the matching phase prompt — phase-specific guidance.
- Both are injected programmatically, not via freeform markdown that agents may or may not read.

This is more reliable than MAP's current approach of embedding context in CLAUDE.md blocks.

### Config validation

Following OpenSpec's pattern:

- Unknown phase IDs in `rules` should generate warnings.
- `context` should have a size limit (e.g., 50KB) to avoid prompt bloat.
- Invalid YAML should be reported with line numbers.
- `mapify doctor` should validate config and report issues.

Example:

```yaml
profile: core

context: |
  Python CLI project.
  Prefer deterministic shell commands.
  Keep .claude templates in sync with shipped templates.

rules:
  research:
    - Check for existing patterns before proposing new abstractions
    - Read tests first to understand expected behavior
  monitor:
    - Verify template sync between .claude/ and src/mapify_cli/templates/
    - Check for OWASP top-10 vulnerabilities

verification:
  checks:
    - make check
    - pytest tests/test_template_render.py -v

policies:
  research_threshold_existing_files: 3
  final_verify_subtask_threshold: 5
  actor_monitor_max_retries: 5

delivery:
  assistant: claude
  hooks: true
  mcp: essential

language: ru  # optional: agent response language
```

## 4. Profiles

Add built-in profiles to reduce default complexity:

- `core`: `/map-plan`, `/map-efficient`, `/map-check`, `/map-review`
- `full`: all advanced workflows (`map-fast`, `map-debug`, `map-tdd`, `map-release`, `map-learn`)
- `custom`: explicit workflow selection

Profiles should affect both generated delivery files and runtime defaults.

### Profile selection UX (informed by OpenSpec)

OpenSpec's `config profile` provides an interactive wizard with current-state summary before changes. MAP should follow a similar pattern:

- `mapify config profile` — interactive selection with preview
- `mapify config profile core` — fast preset switch
- `mapify update` — regenerate delivery files for current profile

### Workflow selection granularity

OpenSpec allows per-workflow toggle within profiles. MAP should support similar granularity:

```yaml
profile: custom
workflows:
  - map-plan
  - map-efficient
  - map-check
  - map-tdd        # user opted into TDD
  # map-debug etc. — omitted, not installed
```

This reduces generated file count and cognitive load for users who don't need every workflow.

This gives MAP a cleaner on-ramp and a cleaner upgrade path.

## 5. Delivery Adapter Layer

Split delivery generation from workflow semantics.

Example package shape:

```text
src/mapify_cli/delivery/
  base.py
  claude.py
```

### Per-tool capability metadata (informed by OpenSpec)

OpenSpec's multi-tool delivery model demonstrates that each adapter needs explicit capability metadata declaring what delivery surfaces it supports and where files go.

MAP should define adapter capability metadata even if initially only Claude is supported:

```python
@dataclass
class DeliveryCapability:
    tool_id: str                    # e.g., "claude"
    supports_agents: bool           # .claude/agents/
    supports_commands: bool         # .claude/commands/
    supports_hooks: bool            # .claude/hooks/
    supports_skills: bool           # .claude/skills/ (emerging standard)
    config_files: list[str]         # ["settings.json", "workflow-rules.json"]
    path_pattern: str               # ".claude/{surface}/{name}"
```

This metadata allows:
- Programmatic validation of adapter completeness
- Future adapters to declare their capabilities upfront
- `mapify doctor` to verify delivery state against capability declarations

### Delivery surfaces

OpenSpec distinguishes between **skills** (richer metadata, cross-tool compatible) and **commands** (tool-specific). MAP currently uses commands + agents. Consider adding skills support for forward compatibility:

| Surface | Current | Future |
|---------|---------|--------|
| Agents | `.claude/agents/*.md` | adapter-generated |
| Commands | `.claude/commands/*.md` | adapter-generated |
| Hooks | `.claude/hooks/` | adapter-generated |
| Skills | not used | `.claude/skills/map-*/SKILL.md` |
| Config | `.claude/settings.json` | adapter-generated |

The Claude adapter should generate:

- `.claude/agents/*`
- `.claude/commands/*`
- `.claude/hooks/*`
- `.claude/settings.json`
- `.claude/workflow-rules.json`

The workflow engine should not care where those files end up. It should only expose:

- workflow definitions
- prompt inputs
- state transitions
- artifact contracts

This keeps MAP Claude-first without making the platform Claude-dependent.

## 6. Managed File Metadata

Every generated file should include structured metadata, either in frontmatter or JSON fields.

Minimum metadata contract:

- `generated_by`: `mapify-cli`
- `generated_by_version`
- `template_id`
- `template_version`
- `workflow_id` or `profile`
- `managed: true`

This enables:

- drift detection
- targeted upgrade
- selective refresh
- future migration tooling

## 7. Branch Artifact Contract

Formalize `.map/<branch>/` into explicitly versioned artifacts.

Required machine-readable artifacts should include:

- `step_state.json`
- `blueprint.json`
- `verification_results_<branch>.json`
- `repo_insight_<branch>.json`
- `active-issues.json`

Recommended human-readable artifacts should include:

- `task_plan_<branch>.md`
- `findings_<branch>.md`
- `verification-summary.md`
- `pr-draft.md`
- `code-review-XXX.md`

Each artifact must define:

- producer
- consumer
- schema/version
- lifecycle
- overwrite/append semantics

## 8. Runtime Policy Extraction

Move these rules out of prompt text and into code/config:

- when research is required
- when final verification runs
- when guard checks run
- when stuck recovery triggers
- when predictor participates
- what counts as a blocking failure
- when resume should re-open or continue a subtask

Prompts should consume policy outputs, not embed policy logic themselves.

## 9. Verification Contract

Formalize verification as a structured contract, not just "run tests".

### Verification dimensions (informed by OpenSpec)

OpenSpec's `/opsx:verify` checks three independent dimensions. MAP's `/map-check` should adopt a similar structured model:

| Dimension | What it validates | MAP equivalent |
|-----------|------------------|----------------|
| **Completeness** | All subtasks done, all artifacts present | Task plan checkboxes, artifact existence |
| **Correctness** | Implementation matches intent, tests pass | `make check`, Monitor review |
| **Coherence** | Design decisions reflected in code, patterns consistent | Predictor analysis, cross-file consistency |

### Verification result schema

`verification_results_<branch>.json` should report per-dimension:

```json
{
  "branch": "feature-x",
  "timestamp": "2026-03-23T12:00:00Z",
  "dimensions": {
    "completeness": {
      "status": "pass",
      "subtasks_done": 5,
      "subtasks_total": 5,
      "artifacts_present": ["blueprint", "task_plan", "step_state"]
    },
    "correctness": {
      "status": "pass",
      "checks_passed": ["make check", "pytest"],
      "checks_failed": []
    },
    "coherence": {
      "status": "warning",
      "issues": ["Design mentions event-driven but implementation uses polling"]
    }
  },
  "overall": "pass_with_warnings",
  "blocking": false
}
```

## 10. Upgrade and Migration Model

Add a real migration path:

- `mapify doctor`
- `mapify upgrade`
- `mapify migrate`

### Migration approach (informed by OpenSpec)

OpenSpec's migration model demonstrates several best practices MAP should adopt:

**Legacy detection.** Automatically detect older generated files by presence of outdated metadata, missing version fields, or legacy file layouts. OpenSpec scans for legacy command directories and marker blocks — MAP should scan for pre-metadata generated files.

**Selective cleanup.** Remove only OpenSpec-managed files, preserve user content. MAP should:
- Strip managed content markers from generated files
- Preserve any user edits outside managed blocks
- Move deprecated files to a backup location before deletion

**Non-interactive mode.** Support `--force` flag for CI environments:
- `mapify upgrade --force` — skip confirmation prompts
- `mapify migrate --force` — auto-accept all migration steps

**User attention items.** When files require manual review (e.g., custom hooks that conflict with new schema), report them clearly without auto-deleting.

**Scope-aware cleanup.** If install scope or profile changes, track last-applied state and clean up stale files at previous locations.

Migration responsibilities:

- detect older generated file versions
- detect legacy artifact layouts
- reconcile old and new metadata
- regenerate safely when files are untouched
- warn when managed files were locally edited
- track last-applied scope/profile for drift detection

## Implementation Plan

## Phase 1. Extract Platform Boundaries

Create internal module boundaries without changing end-user behavior.

Deliverables:

- dedicated workflow engine package
- dedicated delivery package
- dedicated config package
- reduced responsibilities inside `src/mapify_cli/__init__.py`

Acceptance criteria:

- existing commands still work
- current tests still pass
- installer behavior remains unchanged for Claude projects

### Codebase analysis

**Current state.** `src/mapify_cli/__init__.py` is 2692 lines (41% of all source) and contains at least four distinct concerns: CLI wiring + UI widgets (~200 LOC), delivery/installer logic (~1500 LOC including 8 `create_*_content()` agent generators), config generation (~445 LOC for settings/MCP/permissions), and health checks (~370 LOC for doctor/check). State management is already well-separated into five modules (`workflow_state.py`, `ralph_state.py`, `dependency_graph.py`, `verification_recorder.py`, `schemas.py` — 1957 LOC total). The workflow engine (`map_orchestrator.py` + `map_step_runner.py`, 2556 LOC) lives in `templates/map/scripts/` as runtime code copied to user projects. An empty `validation/` directory already exists.

**Proposed decomposition of `__init__.py`:**

```
src/mapify_cli/
  __init__.py              → ~300 lines (CLI wiring, Typer commands, re-exports)
  cli_ui.py                → select_with_arrows(), StepTracker, show_banner()
  delivery/
    __init__.py
    installer.py           → init() orchestration logic
    agent_generator.py     → create_*_content() functions (8 agent generators)
    file_copier.py         → create_reference/command/skill/hook_files()
    health.py              → check(), doctor(), get_project_health()
  config/
    __init__.py
    settings.py            → settings merge logic
    mcp.py                 → MCP config generation
    permissions.py         → configure_global_permissions()
```

**Risks specific to this phase:** Refactoring a 2692-line file requires incremental moves with re-exports to avoid breaking existing imports. Existing tests import from `mapify_cli` top-level — backward-compatible re-exports are essential. The `templates/map/scripts/` runtime engine stays in-place (it is copied to user projects and runs independently).

## Phase 2. Workflow Schema for `map-plan` and `map-efficient`

Implement the workflow schema format and runtime loader.

Deliverables:

- schema format
- validator
- runtime phase graph
- migrated schemas for `map-plan` and `map-efficient`

Acceptance criteria:

- `map-plan` and `map-efficient` execute from workflow definitions
- orchestration decisions no longer rely on prompt-only phase descriptions

### Codebase analysis

**Triple redundancy problem.** The same orchestration rules are currently defined in three independent places that must be kept in sync manually:

1. `map_orchestrator.py` — phase ordering (`STEP_PHASES` dict, lines 99-110; `STEP_ORDER` list, lines 113-122; `TDD_STEP_ORDER`, lines 125-136), step instructions (lines 412-458), retry default (`max_retries=5`, line 278), skippable steps set (line 972).
2. `map-efficient.md` — re-describes the same phases and ordering in prose, embeds retry thresholds (5 main / 3 stuck trigger / 2 guard rework), run conditions (RESEARCH: "3+ existing files OR risk=high"), gate definitions (per-wave: tests + linter), confidence threshold (0.7), stuck recovery policy.
3. `workflow-gate.py` — independently defines `EDITING_PHASES = {"ACTOR", "APPLY", "TEST_WRITER"}` (line 32) for phase-to-permission mapping.

**What should become schema data (currently spread across 5+ files):**

| Rule | Current location | Current format |
|------|-----------------|---------------|
| 10 phase definitions and ordering | `map_orchestrator.py:99-136` | Python dict + list |
| Phase-to-agent mapping | `map-efficient.md` + `map_orchestrator.py:412-458` | Prose + Python strings |
| Retry thresholds (5/3/2) | `map-efficient.md:456-504` | Prose |
| RESEARCH run_if condition | `map-efficient.md:318` + `map_orchestrator.py:436` | Prose + instruction text |
| Per-wave gate checks | `map-efficient.md:525-575` | Prose |
| Phase edit permissions | `workflow-gate.py:32` | Python constant |
| Skippable steps set | `map_orchestrator.py:972` | Python constant |
| TDD step ordering variant | `map_orchestrator.py:125-136` | Python list |
| Test runner detection | `map_step_runner.py:820-842` | Python if/elif chain |
| Guard rework max | `map-efficient.md:571` | Prose |
| Confidence threshold | `map-efficient.md:676` | Prose |

**What should remain as code:** state machine transitions (wave computation, subtask rotation), DAG algorithms (wave splitting by file conflicts), resume detection (regex parsing of task_plan), constraint enforcement (scope_glob fnmatch), circuit breaker formula.

**What should remain as prompts:** interview dimensions in `map-plan.md`, agent reasoning instructions, UX formatting, context distillation rules, troubleshooting guidance.

**Recommendation:** Start with `map-efficient` — it has the largest rule surface. Migrate `map-plan` second — it has less runtime orchestration, more reasoning guidance. The prompt files should reference parameters from the schema via injection (e.g., `{{max_retries}}`) rather than duplicating values.

## Phase 3. Project Config and Profiles

Add `mapify.yaml` or `.map/config.yaml` and built-in profiles.

Deliverables:

- config parser and validator
- default config generation
- profile selection
- runtime policy overrides

Acceptance criteria:

- users can change workflow/profile behavior without editing templates
- installer and runtime both read the same config source

### Codebase analysis

**Current state: 7 configuration sources, zero unification.** Configuration is scattered across `workflow-rules.json` (workflow selection triggers), `settings.json` (permissions + hooks), `ralph-loop-config.json` (circuit breaker thresholds), `skill-rules.json` (skill triggers), 3 Python hooks (~60 hardcoded constants), CLAUDE.md (behavioral rules in prose), and the `init()` CLI (4 flags, 0 profiles).

**Key gaps identified:**

| Gap | Impact |
|-----|--------|
| No `config.yaml` | Users must edit 5+ files to customize MAP |
| No language/framework detection | init installs identical config for Python/Go/TS — yet `settings.json` contains `go vet`, `gofmt`, `kubectl` in allow rules |
| Hook constants are fully hardcoded | `EDITING_PHASES`, `DANGEROUS_FILE_PATTERNS`, `SAFE_PATH_PREFIXES`, `READONLY_COMMANDS` — all Python constants, user must edit source |
| No per-workflow overrides | `ralph-loop-config.json` is global; `map-fast` cannot have `max_total_iterations: 10` while `map-efficient` has 50 |
| No profiles | init installs ALL: 11 agents, 13 commands, 8 hooks, 3 skills — no `core`/`full`/`custom` |
| No CLAUDE.md for user projects | Template CLAUDE.md is MAP's own dev instructions, not a user-project skeleton |

**Existing infrastructure that helps:** `repo_insight.py` already detects project language and can generate suggested verification commands. This can feed auto-detected defaults into `config.yaml`.

**Migration path for hooks:** Hooks should read overridable constants from `config.yaml` via a shared `load_map_config()` utility, with fallback to current hardcoded defaults. This preserves behavior for users who don't create a config file.

## Phase 4. Managed Generation Metadata

Add metadata to generated files and upgrade detection.

Deliverables:

- metadata contract
- drift detection
- selective upgrade behavior
- clearer reporting in `mapify doctor`

Acceptance criteria:

- generated files show origin/version
- `mapify upgrade` can distinguish stale files from customized files

### Codebase analysis

**Current state: almost no metadata, upgrade is blind overwrite.** All four generation functions (`create_agent_files`, `create_command_files`, `create_hook_files`, `create_config_files`) use `shutil.copy2()` — pure file copy with zero metadata injection. No `generated_by` marker, no content hash, no `mapify_version` stamp exists in any generated file. The `upgrade()` command (line 2519) calls the same `create_*_files()` functions and blindly overwrites everything. Only two exceptions have merge logic: `.mcp.json` (preserved) and `settings.local.json` (merged with `create_or_merge_project_settings_local()`).

**What exists today:**

| Category | Has frontmatter | Has version | Has `generated_by` | Upgrade behavior |
|----------|:-:|:-:|:-:|---|
| Agents (11 .md) | YAML: name, description, model | Manual (e.g., `2.4.0`) | No | Blind overwrite |
| Commands (13 .md) | YAML: description only | No | No | Blind overwrite |
| Hooks (7 .py) | No (docstring only) | No | No | Blind overwrite |
| Config (3 .json) | N/A | No (schema version only) | No | Blind overwrite |

**Implementation approach:** Replace `shutil.copy2()` with a `copy_managed_file()` function that injects metadata. For .md files: YAML frontmatter fields. For .py files: header comment block. For .json files: `_mapify_metadata` key or sidecar `.map/manifest.json`. The `upgrade()` function should compare `template_hash` values: overwrite only when the source template changed AND the user did not modify the file.

**Drift detection logic:**

```
current_hash = sha256(file_content_without_metadata)
if current_hash != metadata.template_hash:
    → "user_modified" (warn, don't overwrite)
if metadata.mapify_version < current_mapify_version:
    → "stale" (safe to overwrite)
else:
    → "up_to_date" (skip)
```

## Phase 5. Formal `.map` Artifact Schemas

Extend schema coverage to all critical branch artifacts.

Deliverables:

- explicit schema/version for each artifact
- validators for write/read paths
- migration helpers for old artifacts

Acceptance criteria:

- resume/check/doctor rely on validated artifacts
- artifact consumers fail with actionable errors, not silent drift

### Codebase analysis

**Current state: 25 artifacts discovered, only 2 have JSON Schema validation.** The full artifact inventory:

| Scope | Machine-readable (JSON) | Human-readable (MD) | With schema | Without schema |
|-------|:-:|:-:|:-:|:-:|
| `.map/<branch>/` | 10 | 8 | 0 | 18 |
| `.map/` root | 2 | 1 | 2 | 1 |
| `.map/logs/`, `.map/scripts/` | — | — | — | — |

**Critical gaps:**

1. **`step_state.json` — central artifact, no runtime validation.** Read by orchestrator + 4 hooks + step_runner. `STATE_ARTIFACT_SCHEMA` exists in `schemas.py` but is never imported or used — it is an orphaned schema definition.
2. **`blueprint.json` — no schema at all.** Created by `/map-plan`, consumed by orchestrator for DAG computation. Expected keys (`subtasks[].id, .dependencies, .affected_files`) are described only in prompt text.
3. **Two state systems coexist.** `progress.md` (root-level, `workflow_state.py`) is legacy; `step_state.json` (branch-scoped, `map_orchestrator.py`) is current. Both remain in active code.
4. **Location inconsistency.** `verification_results_<branch>.json` and `repo_insight_<branch>.json` live at `.map/` root (branch in filename), while all other branch-scoped artifacts use `.map/<branch>/` directories.
5. **No lifecycle cleanup.** No artifact has a deletion mechanism. `.map/<branch>/` accumulates files indefinitely.

**Priority for schema formalization:**

| Priority | Artifact | Reason |
|----------|---------|--------|
| P0 | `step_state.json` | Central, 6+ consumers, schema already written but orphaned |
| P0 | `blueprint.json` | DAG computation input, no schema at all |
| P1 | `final_verification.json` | Gate decision artifact |
| P1 | `task_plan_<branch>.md` | Custom XML-like format with regex parsing |
| P2 | `active-issues.json`, `known-issues.json` | Simple, but no schema |

**Quick win:** Activate the orphaned `STATE_ARTIFACT_SCHEMA` — connect it to `map_orchestrator.py` with `jsonschema.validate()` calls on read/write paths.

## Phase 6. Verification Contract and Doctor Improvements

Formalize the verification model.

Deliverables:

- structured verification result schema
- per-dimension reporting (completeness, correctness, coherence)
- improved `mapify doctor` output with config validation

Acceptance criteria:

- `/map-check` reports structured results per verification dimension
- `mapify doctor` validates project config and reports issues with line numbers
- verification results are machine-readable JSON

### Codebase analysis

**Current state: three-tier verification model already exists, but is not formalized into unified dimensions.** The three tiers:

1. **Monitor agent** (per-subtask, during execution) — 10-dimension quality model with structured JSON verdict (`valid`, `issues[]`, `passed_checks`, `failed_checks`). Decision rules: CRITICAL → always `valid=false`; ≥2 HIGH → `valid=false`. Hard stop.
2. **final-verifier agent** (whole-task, after all subtasks) — adversarial verification with confidence scoring (threshold 0.7). Outputs JSON with `passed`, `confidence`, `evidence`, `root_cause`. Verdicts: COMPLETE / RE_DECOMPOSE / ESCALATE.
3. **`/map-check` command** (orchestration) — runs final-verifier + tests + linter + git status. Produces `verification-summary.md`, `<stage>-gate.json`, `active-issues.json`, `pr-draft.md`, `runs/<timestamp>/RESULTS.md`.

**Mapping to Completeness/Correctness/Coherence:**

| Tier | Completeness | Correctness | Coherence |
|------|:-:|:-:|:-:|
| Monitor | dims 5,8,10 (testability, deps, research) | dims 1,2,4,6 (correctness, security, perf, CLI) | dims 3,7,9 (quality, maintainability, docs) |
| final-verifier | subtasks done, criteria met | tests pass, edge cases, ground truth | integration between subtasks |
| `/map-check` | step_state all COMPLETE | tests+lint pass, verifier APPROVED | acceptance criteria from plan |

**Four incompatible result formats currently coexist:** `verification_results_<branch>.json` (recipe-based), `final_verification.json` (confidence-based), `verification-summary.md` (human-readable verdict), `<stage>-gate.json` (gate verdict). A unified umbrella schema with per-dimension reporting would consolidate these.

**Hardcoded policy values to extract to config:** confidence threshold (0.7) in `final-verifier.md`, Monitor decision rules ("CRITICAL → always valid=false", "≥2 HIGH → valid=false") in `monitor.md`, test timeout (300s) in `map_step_runner.py:858`, output truncation (5000 chars) in `map_step_runner.py:863`.

## Phase 7. Additional Delivery Adapters

Only after the platform boundary is complete.

Deliverables:

- second adapter if desired
- adapter capability metadata model
- adapter test harness
- generated-file snapshots per adapter

Acceptance criteria:

- adding a new delivery target does not require changing workflow semantics
- adapter declares capabilities via metadata, not implicit code paths

### Codebase analysis

**Current state: monolithic coupling to Claude Code, zero abstraction layer.** 73 references to "claude" in `__init__.py`, 12+ functions with `.claude/` hardcoded paths, 8 hook scripts fully dependent on Claude Code protocol (`PreToolUse`/`PostToolUse` events, `CLAUDE_PROJECT_DIR` env var, JSON stdout response format). `selected_ai = "claude"` is hardcoded (line 2167) with comment "the only supported AI assistant". No adapter/factory/provider pattern exists.

**Natural separation boundary already present:**

| Layer | Content | Portability |
|-------|---------|:-:|
| `.map/` scripts (orchestrator, step runner, diagnostics) | Workflow engine | 100% portable |
| Agent/command body text (prompt content) | Reasoning instructions | ~90% portable |
| Delivery envelope (frontmatter, paths, hooks, config) | Claude Code integration | 0% portable |

**What would need per-adapter reimplementation:**

| Component | Files affected | Effort |
|-----------|---------------|--------|
| Directory layout (`.claude/` paths) | `__init__.py` (12+ functions) | High |
| `settings.json` generation | 3 functions (settings, permissions, settings.local) | High — entirely different format per platform |
| Hook scripts | 8 files, ~700 LOC total | High — protocol completely different per platform |
| Agent file format (frontmatter) | `create_agent_files()` | Medium — body reusable, envelope differs |
| Command/slash format | `create_command_files()` | Medium |
| MCP config | 2 functions | Medium |

**What is reusable as-is across adapters:** `.map/` scripts, `ralph-loop-config.json`, `workflow-rules.json` body content, all state management modules, `schemas.py`, static analysis handlers, planning skill templates.

**Minimum viable adapter interface:**

```python
class DeliveryAdapter(Protocol):
    tool_id: str
    def create_agents(self, path: Path, agents: list[AgentSpec]) -> int: ...
    def create_commands(self, path: Path, commands: list[CommandSpec]) -> int: ...
    def create_hooks(self, path: Path, hooks: list[HookSpec]) -> int: ...
    def create_config(self, path: Path, config: ProjectConfig) -> int: ...
    def detect_installed(self, path: Path) -> bool: ...
```

Each adapter maps tool-agnostic content (`AgentSpec.prompt_body`) into platform-specific envelopes (`ClaudeAgentEnvelope.model_frontmatter`).

## Implementation Priority and Dependencies

Based on codebase analysis, the phases have the following dependency structure and priority assessment:

```
Phase 1 (Extract Boundaries) ─────────────────────────────────┐
  │                                                             │
  ├──> Phase 4 (Managed Metadata)         [parallel, low dep]  │
  │                                                             │
  ├──> Phase 3 (Config + Profiles)        [parallel, low dep]  │
  │                                                             │
  └──> Phase 2 (Workflow Schema)          [highest value]  ────┤
                                                                │
       Phase 5 (Artifact Schemas)         [incremental]   ─────┤
                                                                │
       Phase 6 (Verification Contract)    [incremental]   ─────┤
                                                                │
       Phase 7 (Delivery Adapters)        [only if needed] ────┘
```

| Phase | Complexity | Value | Risk | LOC affected | Recommendation |
|-------|-----------|-------|------|-------------|----------------|
| 1. Boundaries | Medium | High (prerequisite) | Low | ~2700 refactor | First, incremental moves with re-exports |
| 2. Schema | High | Highest (core problem) | Medium | ~2500 across 5 files | Start with map-efficient, then map-plan |
| 3. Config | Medium | High (UX) | Low | ~500 new + hooks migration | Parallel with Phase 2, after Phase 1 |
| 4. Metadata | Low-medium | Medium (upgrade safety) | Low | ~200 new + 4 functions | Parallel with Phase 3, after Phase 1 |
| 5. Artifacts | Low-medium | Medium (reliability) | Low | ~300 (activate + add schemas) | Incremental, P0 = step_state + blueprint |
| 6. Verification | Low | Medium (formalization) | Low | ~200 (unified schema) | After Phases 2-5 |
| 7. Adapters | High | Low (one platform now) | Medium | ~1500+ (hooks reimpl) | Only if multi-platform demand exists |

**Quick wins available today (before full refactor):**
- Activate orphaned `STATE_ARTIFACT_SCHEMA` in `schemas.py` → connect to `map_orchestrator.py`
- Add `BLUEPRINT_SCHEMA` to `schemas.py`
- Add `generated_by` + `mapify_version` to agent frontmatter (agents already have YAML frontmatter)
- Move 60 hardcoded hook constants to a `hook_defaults.json` that hooks read at startup

## Acceptance Criteria

This refactor is successful when all of the following are true.

### Platform

- workflow sequencing is defined in workflow schemas, not only in markdown command prompts
- runtime policies are loaded from code/config instead of duplicated across prompts
- `.map/<branch>/` artifacts have documented producers, consumers, and schemas

### Product

- a new project can still run `mapify init` and get a working Claude Code setup
- advanced users can tune behavior through config
- `mapify doctor` can explain state, drift, and missing artifacts clearly
- `mapify upgrade` can refresh managed files without acting as blind overwrite

### Engineering

- `src/mapify_cli/__init__.py` is reduced to CLI wiring and installer composition
- orchestrator logic is testable without parsing prompt files
- core workflow state transitions have unit tests
- generated templates have snapshot or fixture-based regression tests

## Risks

### R1. Over-engineering the schema layer

If the workflow schema becomes too abstract, it will be hard to use and hard to debug.

Mitigation:

- start with `map-plan` and `map-efficient`
- keep the schema minimal
- move only stable orchestration rules into the schema

### R2. Breaking the current Claude experience

MAP already works today. The refactor must not damage the default experience.

Mitigation:

- keep Claude adapter as the reference implementation
- ship migration incrementally
- preserve existing generated file locations in the first major rollout

### R3. Two systems temporarily coexisting

During migration there may be prompt-defined and schema-defined workflow logic in parallel.

Mitigation:

- make one workflow at a time authoritative
- document migration status clearly
- add tests that fail if both sources diverge

### R4. Config injection bloating prompts

If project config `context` and `rules` are too large, they consume token budget and degrade agent reasoning quality.

Mitigation:

- enforce a size limit on `context` (e.g., 50KB, following OpenSpec's precedent)
- warn in `mapify doctor` when context exceeds recommended size
- inject `rules` only into matching phases, not globally

### R5. Schema complexity creep

If workflow schemas support too many conditional features (run_if, retry policies, gate types), they become hard to debug.

Mitigation:

- start with a minimal schema format covering only `map-plan` and `map-efficient`
- add features incrementally based on real usage patterns
- provide `mapify workflow show <id>` for visual inspection of phase graphs

## Open Questions

1. Should project config live at `mapify.yaml` or `.map/config.yaml`?
   - *OpenSpec uses `openspec/config.yaml` inside its own directory. Codebase analysis supports `.map/config.yaml` — all branch-scoped artifacts already live under `.map/`, and hooks already read from `.map/<branch>/`. Co-locating config with artifacts reduces path management complexity.*
2. Should workflow schemas be user-overridable, or only built-in in the first iteration?
   - *OpenSpec allows custom schemas from day one via `schema fork`. Given that MAP has 10 hardcoded phases with complex interactions, start built-in only but design the YAML format to be extensible.*
3. Should managed metadata be embedded directly in generated markdown files, or tracked in a sidecar manifest?
   - *Codebase analysis shows agents already have YAML frontmatter (adding fields is trivial), but commands have minimal frontmatter and hooks have none. A hybrid approach is recommended: embed in .md frontmatter, use a sidecar `.map/manifest.json` for .py/.json files.*
4. Should human-readable `.map` artifacts remain markdown-first, or should some become JSON-first with generated markdown views?
   - *Codebase analysis shows `task_plan_<branch>.md` is parsed via regex to extract `ST-XXX` IDs and status. Converting it to JSON-first with a markdown view would eliminate fragile regex parsing.*
5. Should `/map-review` remain mostly prompt-driven longer than `/map-plan` and `/map-efficient`, or migrate with them?
6. Should MAP adopt a skills-based delivery model alongside commands/agents for forward compatibility with emerging AI tool standards?
   - *OpenSpec has moved to skills as the primary delivery surface. MAP already ships skills in `templates/skills/`. Consider expanding skills coverage during Phase 7.*
7. Should `context` and `rules` injection be validated against token budgets to prevent prompt bloat?
   - *OpenSpec limits context to 50KB. MAP should define a similar limit and warn when approaching it.*
8. Should `mapify doctor` validate delivery adapter state against capability metadata (similar to OpenSpec's `schema validate`)?
9. Should the legacy `progress.md` / `WorkflowState` system be removed or migrated as part of Phase 5?
   - *Codebase analysis confirmed two state systems coexist (`progress.md` + `step_state.json`). Removing the legacy system would simplify the artifact contract but requires verifying no consumers depend on it.*
10. Should `verification_results_<branch>.json` and `repo_insight_<branch>.json` move from `.map/` root into `.map/<branch>/` for location consistency?
    - *All other branch-scoped artifacts use `.map/<branch>/` directories. The current location-in-filename pattern is an inconsistency that complicates cleanup and discovery.*

## Recommended First Slice

The first implementation slice should be:

1. **Extract boundaries** — decompose `__init__.py` (2692 LOC) into `delivery/`, `config/`, `cli_ui.py` with backward-compatible re-exports
2. **Quick wins** — activate orphaned `STATE_ARTIFACT_SCHEMA`, add `BLUEPRINT_SCHEMA`, add `generated_by` to agent frontmatter
3. **Workflow schemas** for `map-efficient` first (largest rule surface, triple redundancy), then `map-plan`
4. **Project config** — `.map/config.yaml` with context injection, per-phase rules, profile selection; hooks read from config via `load_map_config()` with fallback to current defaults
5. **Managed file metadata** — replace `shutil.copy2()` with `copy_managed_file()` that injects `mapify_version` + `template_hash`; rewrite `upgrade()` with drift detection
6. **Schema introspection CLI** — `mapify workflow list` / `mapify workflow show`

This sequence provides the highest leverage while keeping the current product usable throughout the migration. Phases 3-4 can proceed in parallel after Phase 1.

## Appendix A: `.map/` Artifact Inventory (as of codebase analysis)

Full inventory of artifacts discovered in the current codebase. This serves as the baseline for Phase 5 schema formalization.

### Branch-scoped artifacts (`.map/<branch>/`)

| Artifact | Format | Producer | Key consumers | Schema exists | Semantics |
|----------|--------|----------|--------------|:-:|---|
| `step_state.json` | JSON | `map_orchestrator.py` | orchestrator, 4 hooks, step_runner | Doc only (orphaned schema in `schemas.py`) | Overwrite (atomic) |
| `blueprint.json` | JSON | `/map-plan` (Write tool) | orchestrator `set_waves()` | No | Overwrite (once) |
| `task_plan_<branch>.md` | MD + XML tags | `/map-plan` (Write tool) | orchestrator, step_runner (regex parse) | No | In-place status updates |
| `spec_<branch>.md` | MD | `/map-plan` (Write tool) | task-decomposer, `/map-tdd` | No | Overwrite + append |
| `findings_<branch>.md` | MD + XML tags | research-agent, `/map-plan` | `/map-efficient` | No | Append |
| `ralph_state.json` | JSON | `ralph_state.py` | Ralph loop orchestrator | No (dataclass only) | Overwrite (atomic) |
| `final_verification.json` | JSON | final-verifier agent | `ralph_state.py`, orchestrator | No | Overwrite |
| `verification-summary.md` | MD | `map_step_runner.py` | orchestrator (resume), `/map-check` | No | Overwrite |
| `code-review-NNN.md` | MD (numbered) | `/map-efficient` (Write tool) | orchestrator (resume briefing) | No | Create new |
| `plan-review-NNN.md` | MD (numbered) | `map_step_runner.py` | review handoff | No | Create new |
| `pr-draft.md` | MD | `map_step_runner.py` | handoff bundle | No | Overwrite |
| `qa-001.md` | MD | `ensure_human_artifacts()` / agent | handoff bundle | No | Overwrite |
| `known-issues.json` | JSON | `map_step_runner.py` | `/map-check`, diagnostics | No | Append |
| `active-issues.json` | JSON | `map_step_runner.py` | handoff bundle, `/map-review` | No | Overwrite (replace) |
| `<stage>-gate.json` | JSON | `map_step_runner.py` | handoff bundle | No | Overwrite |
| `diagnostics.json` | JSON | `diagnostics.py` | `workflow-context-injector.py` | No | Overwrite |
| `run-summary.json` | JSON | `diagnostics.py` | `/map-check` | No | Overwrite |
| `runs/<ts>/RESULTS.md` | MD | `/map-check` (Write tool) | Audit | No | Create new |
| `transcript-*.md` | MD | `pre-compact-save-transcript.py` | Manual review | No | Create new |

### Root-level artifacts (`.map/`)

| Artifact | Format | Producer | Schema exists | Notes |
|----------|--------|----------|:-:|---|
| `verification_results_<branch>.json` | JSON | `verification_recorder.py` | Yes (validated on write) | Location inconsistency: branch in filename, not path |
| `repo_insight_<branch>.json` | JSON | `repo_insight.py` | Yes (validated on write) | Same location inconsistency |
| `progress.md` | MD + YAML frontmatter | `workflow_state.py` | No | Legacy — coexists with `step_state.json` |

## Appendix B: Claude Code Coupling Map (as of codebase analysis)

Coupling assessment for Phase 7 planning. Shows what is Claude-specific vs tool-agnostic.

### Claude-specific (0% portable)

| Component | Files | Coupling points |
|-----------|-------|-----------------|
| `__init__.py` delivery functions | 12+ functions | `.claude/` paths hardcoded, `selected_ai = "claude"` |
| `settings.json` | Template | Claude Code proprietary schema, `$schema` URL, `permissions.deny/allow` format, hook event names |
| Hook scripts (8 files) | `templates/hooks/` | `CLAUDE_PROJECT_DIR` env var, `PreToolUse`/`PostToolUse` event model, JSON stdout protocol |
| Agent frontmatter | 11 `.md` files | `model: sonnet/opus/haiku` (Claude-specific tier names) |
| Skill format | `SKILL.md` files | `allowed-tools`, `${CLAUDE_PLUGIN_ROOT}`, Claude hook sections |
| `is_map_initialized()` | `__init__.py:549` | Checks for `.claude/agents`, `.claude/commands`, `.claude/settings.json` |

### Tool-agnostic (100% portable)

| Component | Files | Notes |
|-----------|-------|-------|
| `.map/` scripts | `map_orchestrator.py`, `map_step_runner.py`, `diagnostics.py`, `map_utils.py` | Only 1 comment mentions Claude |
| State management | `workflow_state.py`, `ralph_state.py`, `dependency_graph.py`, `schemas.py` | Pure logic |
| `ralph-loop-config.json` | Template | Circuit breaker thresholds |
| Static analysis | `analyze.sh` + language handlers | Language-specific, not platform-specific |
| Agent/command body text | Prompt content (sans frontmatter) | ~90% portable (`AskUserQuestion()` is Claude-specific) |
| `verification_recorder.py` | State module | Pure logic |
| `repo_insight.py` | State module | 1 line excludes `.claude` from scan |

## Appendix C: OpenSpec Reference

This spec was informed by analysis of [OpenSpec](https://github.com/Fission-AI/OpenSpec) (v2025+, OPSX workflow). Key documents referenced:

- `docs/concepts.md` — artifact model, delta specs, schemas
- `docs/workflows.md` — fluid actions, dependency graph, verification dimensions
- `docs/customization.md` — project config, custom schemas, context injection
- `docs/opsx.md` — OPSX architecture, component model, iteration model
- `docs/cli.md` — CLI surface, schema management commands
- `docs/migration-guide.md` — legacy detection, cleanup, config migration
- `docs/supported-tools.md` — multi-tool delivery, capability metadata
- `openspec/changes/add-global-install-scope/` — install scope design (global vs project)
