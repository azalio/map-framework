---
name: map-memory-now
description: >-
  Finalize cross-session memory on demand; --finalize-all sweeps every dirty
  scratch. Use when ending a long session or before switching branches. Do NOT
  use for routine edits — finalize auto-runs at next SessionStart. Requires
  claude + git.
effort: low
disable-model-invocation: false
argument-hint: "[--finalize-all]"
---

# MAP Memory Now — On-Demand Session Memory Finalization

**Purpose:** Immediately finalize cross-session memory without waiting for the
next `SessionStart`. Useful after a long session, before switching branches, or
as a maintenance sweep over multiple unfinalized scratches.

**When to use:**
- Before ending a long working session to ensure memory is committed
- After a session that ended abruptly (process kill, crash) without a clean `SessionEnd`
- Maintenance sweep: `--finalize-all` to finalize every dirty scratch across all branches
- Before running `/map-learn` to ensure the current session's context is available

**Requires:**
- `claude` CLI (finalization uses `claude -p` to generate the digest summary)
- `git` (branch name resolution and optional digest commit)

**Optional env var:**
- `MAP_MEMORY_COMMIT_DIGESTS=0` — keep digests local (do not `git add`/commit them).
  To make this permanent, add `.map/*/sessions/` to your project `.gitignore`.

---

## Constraints (NEVER)

- **NEVER** edit code, run a workflow, or make commits beyond the digest from this skill — it only finalizes memory.
- **NEVER** hand-write or edit a digest `.md` or scratch `.jsonl` directly; only `finalize_dirty` writes them (it is atomic — a failed digest is left unfinalized for retry, never half-written).
- **NEVER** modify the user's `.gitignore` or flip `MAP_MEMORY_COMMIT_DIGESTS` for them — if the user wants digests kept local, instruct them; do not change it automatically.
- **NEVER** let a digest carry secrets or credentials.

---

## Arguments

- `$ARGUMENTS` empty or `--finalize-all` — both run the full sweep (finalize ALL dirty
  scratches). `finalize_dirty(None, project_dir)` treats `incoming_sid=None` as "all
  scratches are candidates", so a single call covers both the current session and any
  older unfinalized ones.

---

## Step 1: Run finalize sweep

From the **repo root**, run the finalize sweep in-process (avoids cross-clone
editable-install contamination):

```bash
python3 - <<'PY'
import sys, os
# Prefer in-process import from src/ when running in the development worktree;
# fall back to the installed package when running in a user project.
_src = os.path.join(os.getcwd(), "src")
if os.path.isdir(_src):
    sys.path.insert(0, _src)
from mapify_cli.memory.finalize import finalize_dirty
n = finalize_dirty(None, ".")
print(f"map-memory-now: finalized {n} digest(s)")
PY
```

`finalize_dirty(None, ".")` is the `--finalize-all` sweep: it finalizes every
dirty scratch WAL found under `.map/*/sessions/scratch/` in the current project,
regardless of which session or branch wrote it.

---

## Step 2: Report result

After the script completes, report to the user:

```
## /map-memory-now Result

Finalized N digest(s).

- Digests written to: .map/<branch>/sessions/<session-id>.md
- Scratches cleaned:  .map/<branch>/sessions/scratch/<session-id>.jsonl (removed after finalize)

To keep digests local (not committed), set MAP_MEMORY_COMMIT_DIGESTS=0 or add
`.map/*/sessions/` to .gitignore.
```

If `N = 0`, report:

```
## /map-memory-now Result

No dirty scratches found — nothing to finalize.
(All sessions are either already finalized or have no recorded turns.)
```

---

## Examples

- **End-of-session finalize (default):**
  `/map-memory-now` — finalizes every dirty scratch in the project so the next
  session can recall this one's decisions.
- **Maintenance sweep after several abrupt exits:**
  `/map-memory-now --finalize-all` — same behavior; explicitly sweeps all
  outstanding dirty scratches across branches.
- **Keep digests local:** set `MAP_MEMORY_COMMIT_DIGESTS=0` before running, then
  uncomment `.map/*/sessions/` in `.gitignore` so finalized digests stay private.

## Troubleshooting

- **"finalized 0 digest(s)":** no dirty scratches exist — every session is already
  finalized or recorded no turns. This is the normal no-op result, not an error.
- **`claude: command not found`:** the finalizer shells out to `claude -p`. Install
  the `claude` CLI / put it on PATH. On hosts without `claude`, `mapify init` prunes
  this skill entirely (host gate, EC-4).
- **Digest not written / scratch still present:** finalize is best-effort and atomic —
  on a `claude -p` timeout or error the scratch is left unfinalized (no partial digest)
  and retried on the next `SessionStart`. Re-run `/map-memory-now` to retry immediately.
- **Wrong package exercised:** when developing in a clone, run from the repo root so the
  in-process `src/` import resolves the worktree (not a stale editable install).

## Notes

- **Idempotent:** running `/map-memory-now` multiple times is safe — already-finalized
  sessions are skipped automatically.
- **No new CLI subcommand needed:** `finalize_dirty(None, project_dir)` IS the
  `--finalize-all` sweep. The skill invokes it directly.
- **Keep digests local (MAP_MEMORY_COMMIT_DIGESTS=0 opt-out):** finalize never stages or
  commits anything itself — it only writes the digest file to disk. Digests under
  `.map/*/sessions/*.md` are committed by default simply because they are not git-ignored.
  To keep them local, uncomment the `.map/*/sessions/` line in your `.gitignore` (see the
  commented block shipped by `mapify init`).
