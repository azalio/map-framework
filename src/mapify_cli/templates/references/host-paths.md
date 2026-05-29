# MAP Host-Path and Environment-Variable Contract

**Purpose:** Canonical reference for MAP_* env vars, ~/.map/ host-path layout, and state-marker enum. Read this before adding, renaming, or consuming any MAP_* variable.

---

## (a) MAP_* Namespace — Canonical

`MAP_*` is the canonical prefix for all MAP Framework runtime variables. New variables MUST use this prefix. The `MAPIFY_*` prefix is frozen (legacy only — see §Legacy below).

## (b) Reserved Variables

These three variables are reserved by the MAP orchestration layer. Do not repurpose or shadow them.

| Variable | Semantics |
|---|---|
| `MAP_INVOKED_BY` | Identity of the invoking agent or surface (e.g., `map-efficient`, `map-task`). |
| `MAP_BRANCH` | Git branch name of the active MAP session; used to scope `.map/<branch>/` state. |
| `MAP_SUBTASK_ID` | ID of the currently executing subtask (e.g., `ST-002`); set by the orchestrator. |

## (c) Registry of Existing MAP_* Variables

| Variable | Status | Location | Semantics |
|---|---|---|---|
| `MAP_DEBUG` | live | `src/mapify_cli/__init__.py:207` | Enables verbose debug logging across MAP CLI internals when set to a truthy value. |
| `MAP_MONITOR_HOTFIX` | live | `src/mapify_cli/templates/codex/hooks/workflow-gate.py:68` | Bypasses the monitor gate for emergency hotfix flows; must not be set in normal workflows. |
| `MAP_STRICT_SCOPE` | live | `src/mapify_cli/templates/map/scripts/map_step_runner.py:7137` | Enforces strict mutation-boundary validation; rejects Actor edits outside `affected_files`. |
| `MAP_REVIEW_PROMPT_BUDGET_TOKENS` | live | `src/mapify_cli/templates/map/scripts/map_step_runner.py:147,4577` | Token budget for review prompts; consumed via `REVIEW_PROMPT_BUDGET_ENV`. |
| `MAP_CONTEXT_BLOCK_BUDGET_TOKENS` | provisional | `docs/USAGE.md:54,64` | provisional — documented in docs/USAGE.md but no runtime consumer found as of this PR; do not rely on it without re-verifying |

## (d) Legacy / Frozen Variables

- **`MAPIFY_TRANSCRIPT_PATH`** — legacy. Defined in `.map/scripts/map_orchestrator.py`. The `MAPIFY_*` prefix is frozen; this variable will not be renamed or promoted. Do not introduce new `MAPIFY_*` variables.

## (e) Host-Path Layout

MAP uses two root directories:

- **`.map/<branch>/`** — per-branch workflow state (subtask plans, step state, findings). Lives inside the project repo, committed or gitignored per project convention.
- **`~/.map/`** — host-scoped shared state. Two subdirectories matter:
  - `~/.map/locks/` — advisory lock files acquired by the orchestrator to prevent concurrent MAP sessions on the same branch.
  - `~/.map/hooks/` — host-level hook scripts invoked by the MAP hook harness before/after workflow phases.

These are the only two MAP roots. No other directories are created by the MAP runtime.

## (f) State Markers (Closed Enum)

`src/mapify_cli/_locking.py` defines the `LockState` enum and writes one of these six values to the sidecar at `~/.map/locks/<name>.state.json` whenever a caller holds a `flock_with_state` lock:

```
in_progress  created  updated  skipped  timeout  error
```

This PR ships the enum and the sidecar writer; no MAP workflow surface is wired to call `flock_with_state` yet (Phase A consumes it for hook serialization, Phase E for memory-flush). The pre-existing `step_state.json` subtask statuses (`pending|in_progress|complete|blocked`) are a separate, unrelated enum owned by the orchestrator.

**INV-5 invariant:** This is a closed enum. Adding a new state requires editing BOTH `src/mapify_cli/_locking.py:LockState` AND this document in the same PR. A PR that adds a state to one without the other must be rejected.

## (g) Implementation — `src/mapify_cli/_locking.py`

`src/mapify_cli/_locking.py` is the authoritative implementation of the state-marker contract and the `~/.map/locks/` protocol. It defines the `LockState` enum (the closed set from §f above) and the lock-acquire/release logic for `~/.map/locks/`. Full docstring discipline for this module is specified in ST-003, which lands in this same PR.

Forward-reference: any question about lock semantics, timeout behaviour, or state-transition rules should be answered from `_locking.py`, not from this doc.

## (h) Related (Platform Integration)

- **`CLAUDE_PROJECT_DIR`** — owned by Claude Code, not MAP. MAP must not set, override, or depend on this variable; treat it as read-only ambient context if needed.
