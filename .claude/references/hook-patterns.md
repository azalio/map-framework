# Hook Patterns — The `MAP_INVOKED_BY` Recursion Guard

This document is the authoritative contract for the recursion guard that every
MAP hook is classified against. It is enforced mechanically by
`scripts/lint-hooks.py` (wired into `make lint` / `make check`) and proven by
`tests/test_hook_patterns.py`. The classification list here and in
`lint-hooks.py` must agree; a hook that is unclassified fails the linter.

## Why a recursion guard exists

A MAP workflow routinely spawns a nested Claude/Codex subprocess (a nested
Actor, Monitor, or — in Phase E — a memory-flush `claude -p` launched from a
hook). When it does, it sets the reserved environment variable
`MAP_INVOKED_BY` (see `.claude/references/host-paths.md` for the reserved
`MAP_*` namespace).

The nested subprocess re-fires the **entire hook chain**. Hooks that do
orchestration-, session-, or telemetry-level work belong to the *top-level*
session; re-running them inside a nested Actor is at best noise (duplicate
context injection, double-counted tokens) and at worst recursive (a hook that
spawns child tooling which itself re-enters the hook chain). The guard makes
those hooks no-op when `MAP_INVOKED_BY` is set.

The guard is **not** a blanket "exit everywhere" switch. A subset of hooks —
the deny gates and the post-compaction re-prime — MUST always fire, even
inside a nested invocation. Applying the guard to them would be a security
regression (a nested Actor doing real edits would no longer be gated) or a
correctness regression (a nested Actor whose context was just compacted would
lose its workflow re-prime). Those hooks are therefore guard-**forbidden**.

## The two classes

Every hook is in exactly one class.

### REQUIRE_GUARD — recursion-suppressed (early-exit on `MAP_INVOKED_BY`)

These only emit context / nudges / telemetry / transcript saves that belong to
the top-level session. They early-exit when the flag is set.

| Hook | Event | Blocking? | Rationale for suppression |
|------|-------|-----------|---------------------------|
| `context-meter.py` | `UserPromptSubmit` | No | `/compact` nudge is a top-level session concern; meaningless inside a nested turn |
| `map-token-meter.py` | `SubagentStop` + `Stop` | No | Token attribution is owned by the parent run; nested re-entry double-counts and can spawn child tooling |
| `workflow-context-injector.py` | `PreToolUse` (Edit/Write/Bash) | No | The MAP reminder targets the top-level operator, not a nested Actor that already has its subtask context |
| `detect-clarification-triggers.py` | `UserPromptSubmit` | No | Clarification nudges apply to the human-facing prompt, not nested machine turns |
| `ralph-iteration-logger.py` | `PostToolUse` | No | Iteration/thrashing logging is a parent-run concern; the orchestrator runs its own Monitor on the subtask diff |
| `ralph-context-pruner.py` | `PreCompact` | No | Restore-point/pruning belongs to the top-level transcript |
| `pre-compact-save-transcript.py` | `PreCompact` | No | Saving the parent transcript; a nested run has its own short-lived transcript |
| `end-of-turn.sh` | `Stop` | No | Auto-format could edit files outside a nested Actor's `affected_files`; lint surfacing is the orchestrator's job |
| `scrub-internal-ids.py` | `Stop` | No | Scrub + cleanup-commit is a top-level run-completion concern; a nested Actor (`MAP_INVOKED_BY` set) must not rewrite or commit the parent run's tree |
| `map-memory-capture.py` | `Stop` | No | Memory capture is a top-level-session concern; a nested run (MAP_INVOKED_BY set) must not write to the parent's session WAL |
| `map-memory-endmark.py` | `SessionEnd` | No | End-marker belongs to the top-level session WAL; a nested run must not write an ended marker into the parent's scratch |
| `map-memory-finalize.py` | `SessionStart` | No | Digest finalization is a top-level-session concern; a nested run must not finalize the parent's session scratch |
| `map-memory-recall.py` | `SessionStart` + `UserPromptSubmit` | No | Recall injection targets the top-level session; a nested run must not recall from or inject into the parent's context |

> **Intentional consequence:** suppressing `end-of-turn.sh` and
> `ralph-iteration-logger.py` in nested runs means a nested Actor's lint
> errors / tool calls are not surfaced or logged at the *parent* level. This
> is by design — the orchestrator runs its own Monitor and `make check` on the
> subtask diff. It is documented here, not a defect.

### FORBID_GUARD — must always fire (guard is forbidden)

These either enforce a safety/workflow boundary or recover context. The linter
forbids a `MAP_INVOKED_BY`-conditioned early-exit in them, in both directions,
so a future contributor cannot "helpfully" disable the gate for every
MAP-spawned subagent.

| Hook | Event | Blocking? | Rationale for always-fire |
|------|-------|-----------|---------------------------|
| `safety-guardrails.py` | `PreToolUse` (Edit/Write/Read/MultiEdit/Bash) | Yes (JSON deny) | A nested Actor doing real edits MUST still be blocked from sensitive files / dangerous commands |
| `workflow-gate.py` | `PreToolUse` (Edit/Write/MultiEdit) | Yes (JSON deny) | The Actor+Monitor phase gate must enforce on nested edits exactly as on top-level edits |
| `workflow-gate.py` (Codex) | `PreToolUse` | Yes (JSON deny) | Codex twin of the above (`.codex/hooks/` + `src/mapify_cli/templates/codex/hooks/`); same rule |
| `post-compact-context.py` | `SessionStart` (compact) | No | A nested Actor whose context was just compacted needs the MAP re-prime *more*, not less; SessionStart cannot be self-triggered by a hook, so it is not a recursion source |

> **Load-bearing security property (INV-A1):** A FORBID_GUARD hook's
> decision/recovery path is byte-identical whether or not `MAP_INVOKED_BY` is
> set. This mirrors the learned rule *"never structurally bypass the
> blocklist."* The deny gates read no env flag at all.

## The guard idiom and its position

### Position rule (INV-A2)

Presence is not enough — **position** is enforced.

- **Python REQUIRE_GUARD hooks:** the guard MUST be the **first statement of
  the entry function** (`main()` or equivalent), after the function docstring
  (if any) but before any `stdin` read or other I/O. If a hook has no `main()`
  and executes at module scope, the guard MUST be the first statement at module
  scope after the import block and constant definitions.
- **Shell REQUIRE_GUARD hooks (`end-of-turn.sh`):** the guard MUST appear
  before the first command that reads input or runs tooling.

`scripts/lint-hooks.py` AST-walks each `.py` hook and regex-checks each `.sh`
hook to verify the class-appropriate guard *and* its position; a guard placed
after a side-effecting statement fails the linter, not just an absent one.

### Canonical idiom (SC-1 — byte-identical across all REQUIRE_GUARD hooks)

Python:

```python
def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    ...
```

Shell (`set -euo pipefail` safe — the `:-` default avoids tripping `nounset`):

```bash
set -euo pipefail

# Recursion guard: no-op when MAP spawned this subprocess (MAP_INVOKED_BY set)
[ -n "${MAP_INVOKED_BY:-}" ] && exit 0
```

`MAP_INVOKED_BY` set to the empty string counts as "not invoked": both
`os.environ.get(...)` (falsy on `""`) and the shell `-n "${MAP_INVOKED_BY:-}"`
test treat empty as unset.

## Pointer: the `LockState` marker enum

Hook serialization across processes is governed by the lock-state marker
contract, **not** by this env-flag guard. The authoritative marker enum is
`LockState` in `src/mapify_cli/_locking.py` (a closed `StrEnum`:
`in_progress`, `created`, `updated`, `skipped`, `timeout`, `error`), written to
the sidecar at `~/.map/locks/<name>.state.json` by `flock_with_state`. See
`.claude/references/host-paths.md` §(f)/(g) for the marker contract and the
`~/.map/locks/` protocol.

Phase A deliberately does **not** call `flock_with_state` for hook
serialization — there is no current recursion-by-concurrency case, so the
env-flag guard above is sufficient. The lock-state contract is referenced here
only so the two mechanisms are not confused.

## Phase E forward reference — not used by any current hook

> **The pattern below is documented for forward compatibility only. No current
> hook implements it.** It is recorded here so it is not mistaken for an
> active convention.

Phase E will let a hook spawn a fully detached background process (e.g. a
memory-flush `claude -p`) that outlives the hook without re-entering the hook
chain on the parent's stdin. The contract for that detached spawn is:

```python
import subprocess

subprocess.Popen(
    [...],
    start_new_session=True,   # detach from the parent process group
    stdin=subprocess.DEVNULL, # never inherit / block on the parent's stdin
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
```

The detached child sets `MAP_INVOKED_BY` in its own environment so that any
hooks it triggers honor the REQUIRE_GUARD early-exit above. Until Phase E
lands, treat this section as design intent, not implemented behavior.
