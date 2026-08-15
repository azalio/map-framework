# MAP Host-Path and Environment-Variable Contract

**Purpose:** Canonical reference for MAP_* env vars, ~/.map/ host-path layout, and state-marker enum. Read this before adding, renaming, or consuming any MAP_* variable.

---

## (a) MAP_* Namespace — Canonical

`MAP_*` is the canonical prefix for all MAP Framework runtime variables. New variables MUST use this prefix. The `MAPIFY_*` prefix is frozen (legacy only — see §Legacy below).

## (b) Reserved Variables

These four variables are reserved by MAP runtime layers. Do not repurpose or shadow them.

| Variable | Semantics |
|---|---|
| `MAP_INVOKED_BY` | Identity of the invoking agent or surface (e.g., `map-efficient`, `map-task`). |
| `MAP_BRANCH` | Git branch name of the active MAP session; used to scope `.map/<branch>/` state. |
| `MAP_SUBTASK_ID` | ID of the currently executing subtask (e.g., `ST-002`); set by the orchestrator. |
| `MAP_UPDATE_PARENT_LEASE` | Ephemeral updater-to-provider-child credential. It is not user configuration; see §Update Refresh Lease below. |

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

MAP uses the following host and project paths:

- **`.map/`** — project-local MAP state. `.map/<branch>/` holds per-branch workflow artifacts. The automatic updater owns the gitignored `.map/update-state.json`, `.map/update.lock`, `.map/installer.lock`, and `.map/provider-refresh.lock` files.
- **`.sofa/`** — opt-in SOFA credentials. `.sofa/credentials.lock` serializes private credential-file reads and writes and is ignored with the rest of `.sofa/`.
- **`~/.map/`** — host-scoped shared state. Two subdirectories matter:
  - `~/.map/locks/` — advisory lock files acquired by the orchestrator to prevent concurrent MAP sessions on the same branch.
  - `~/.map/hooks/` — host-level hook scripts invoked by the MAP hook harness before/after workflow phases.

Root `.gitignore` mutation uses one persistent cross-process lock keyed by the
SHA-256 of the resolved project root. POSIX hosts place it at the fixed path
`/tmp/mapify-gitignore-<digest>.lock`, independently of `TMPDIR`; Windows uses the
centrally ignored project-root fallback `.map-gitignore.lock`. These lock files do
not introduce another MAP state directory.

### Update Refresh Lease

`MAP_UPDATE_PARENT_LEASE` is a cryptorandom, single-process handoff from an updater
that holds `.map/update.lock` to its direct `mapify init --refresh-existing` child.
It is an ephemeral credential, not a configurable runtime option:

- the updater passes it only in that provider child's environment;
- the child removes it before init executes any command or extension;
- it is never placed in command arguments or inherited by a package manager;
- the raw value is never persisted—the lock record stores only its SHA-256 digest,
  the parent PID, and resolved project identity; and
- it cannot be reused without active update-lock contention plus matching direct
  parent PID, project, provider, running version, and pending update phase.

Package mutation is serialized by `.map/installer.lock`, which is acquired by an
isolated installer controller before it signals `READY`. The updater writes durable
install intent only after `READY`, then sends `GO`. Parent death before `GO` closes
the control pipe without starting pip/uv; parent death after `GO` leaves the child
holding the installer barrier until pip/uv exits. The controller uses the current
interpreter's isolated mode plus the resolved trusted MAP package root, so project
files and `PYTHONPATH` cannot shadow its `mapify_cli` import. No lease or handshake
secret is placed in argv. Pip also runs in interpreter isolated mode while keeping
the project as its working directory, so neither the project nor `PYTHONPATH` can
shadow pip's module entry point.

Provider mutation is separately serialized by `.map/provider-refresh.lock` so a
child that outlives its updater parent cannot race a replacement update. The
enforced global order is `.map/update.lock`, then `.map/installer.lock`, then
`.map/provider-refresh.lock`. The updater's installer child owns only the installer
barrier; a validated provider child already covered by its parent's update lock
acquires only the provider barrier after installation completes.

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
