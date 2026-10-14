# #502 lossless blocker repair: real-Git spike

Status: **PASS for serial, quiescent, disjoint-path repair**. This is a docs-only binding spike, not a production implementation. Delivery remains PR + CI; no merge or release is authorized.

## Binding strategy

Use a **private standalone repository**, not a linked worktree, stash, reset, or synthetic commit on the paused branch.

1. `begin_repair` pins the original commit H, attached full ref, repository/Git-directory identity, and the exact paused orchestration frame. Preserve the parent frame in place with an active-repair marker; keep normal repair workflow state in the private checkout. Reject concurrent waves, nested repair, unmerged index entries, unsupported index/path types, and overlapping paths.
2. Capture the combined working snapshot: actual working bytes and modes, including tracked deletions, staged-plus-unstaged files, staged additions/renames, symlinks, and ordinary nonignored untracked files. Separately capture paused per-path index entries and working preimages; the combined snapshot is not a substitute for the original index.
3. Initialize a private `.git` directory, fetch H into its independent object store, copy the working snapshot, and create private synthetic snapshot S. There are no remotes, alternates, or shared Git directory. Synthetic S and repair-on-S candidate C remain private.
4. `verify_repair` runs independent repair gates against the **combined snapshot plus repair**. Freeze/certify the exact candidate that was checked; reject out-of-bound writes or candidate drift. The spike ran an executable assertion gate on private working files before committing those exact bytes; production must bind its actual gate receipts to the frozen candidate, not merely remember an earlier successful command.
5. Compute repair path set P from S→C with rename detection disabled, so both rename endpoints and deleted paths are included. Check component-prefix intersections in both directions, conservatively case-folded, against paused paths. A deletion or staged rename source remains protected even if absent from working files.
6. Build R in the private repository: `git read-tree H`, apply only P's candidate index entries/deletions using NUL-delimited `git update-index --index-info`, then `git write-tree` and `git commit-tree <tree> -p H`. **R has parent H, not S or C; its only H→R changes are P.** Fetch only R into the main object store. The spike verified S is not even present there.
7. `finish_repair` validates pinned identity/ref, paused preimages, repair preimages and expected HEAD. Persist finish intent, CAS the pinned ref using `git update-ref <ref> R H`, update only P in the **current** main index through Git's index lock, and replace/delete only P's working files. Never restore a saved whole index. Validate exact paused per-path index OIDs/modes and working types/modes/bytes afterward, then restore the paused phase/frame without advancing it or forging gate success.

The Git mechanism and finish-recovery cuts below were executed. Orchestration API/state integration, actual project quality gates, and their receipts were not implemented by this spike.

## Empirical setup and output

Executed on 2026-10-12, Darwin, `git version 2.47.1`, using `python3 -I` and real subprocess Git commands. All repositories/scripts are disposable and outside the production tree:

- Script: `/tmp/blocker-repair-spike.8X346c/spike.py`
- Raw output: `/tmp/blocker-repair-spike.8X346c/output.txt`
- Machine results: `/tmp/blocker-repair-spike.8X346c/results.json`
- Workspace resolves to `/private/tmp/blocker-repair-spike.8X346c` on this host.

Each of 25 cases started with a fresh attached feature branch and original H. Paused feature work included staged+unstaged content on one path, staged deletion, unstaged deletion, staged rename plus unstaged destination content, staged executable mode/content plus unstaged bytes, binary bytes, changed symlink target, and an ordinary untracked file with mode `0600`. Repair changed a disjoint lint file, deleted a file, renamed a file, and added an executable file.

Selected actual output, final run:

```text
EXIT:0
PASS 340 25
```

```json
{
  "assertions": 340,
  "status": "PASS",
  "git_version": "git version 2.47.1",
  "checks": {
    "combined snapshot exact working bytes and modes": 25,
    "gate executed combined snapshot": 25,
    "independent object store no alternates": 25,
    "private no remotes": 25,
    "private separate git directory": 25,
    "repair parent original HEAD not synthetic": 25,
    "repair commit excludes paused changes": 25,
    "repair tree preserves base feature tree": 25,
    "synthetic snapshot never imported into main": 25,
    "real expected-head CAS rejects stale HEAD": 1
  }
}
```

The gate required both paused working content/untracked/deletion/rename and the repair's fixed content/deletion/rename/executable addition, and emitted `COMBINED_GATE_OK`. Successful finish and replay compared every paused per-path stage-0 index entry `(mode, object ID)` and working entry `(type, permission bits, exact bytes or symlink target)`; all were identical. Fresh-process recovery executions performed the same postconditions, not only return-code checks.

Negative checks passed:

- Exact deletion overlap; addition below a paused file; addition replacing a paused directory prefix; deletion of a parent prefix; rename source overlap; rename destination prefix overlap; case-folded prefix overlap. `feature/a` versus `feature/ab` correctly does not conflict. These conflict checks exercised the path-set predicate; conflicting filesystem transitions were deliberately not applied.
- External HEAD, attached-ref, repository-identity, paused bytes/index/mode, and repair bytes/index drift. Also repair-file drift after CAS and paused-file drift after index update. Each rejection left the observed files/index/HEAD unchanged from its drifted pre-call state: recovery does not undo the user's drift or silently roll back an already-applied CAS.
- A real `git update-ref` with stale expected H failed and retained the external commit, independently of Python preflight validation.

## Crash recovery stages

The journal lives under private Git metadata, outside the tracked snapshot, and records H/R, pinned ref/identity, exact paused preimages, P, repair pre/post index entries and working images, and stage. It is written through a temporary file + replacement. Recovery starts in a **new Python process**, reloads the journal, examines actual Git/filesystem state, and completes only recognized transitions.

| Stage / interrupted cut | Recovery rule | Empirical result |
| --- | --- | --- |
| `prepared` / `before_cas` | Persist HEAD intent; only pinned H is expected before applying CAS. | PASS |
| `head_intent` / `after_cas_before_journal` | Recognize pinned ref already at R; do not repeat H→R blindly. | PASS |
| `head_done` | Require R; repair files/index still preimage. | PASS |
| `index_intent` / `before_index` | Apply targeted P update to current index. | PASS |
| `index_intent` / `after_index_before_journal` | Accept whole P index at OLD or whole P index at NEW, not arbitrary mixture. | PASS |
| `index_done` | Require P index NEW and working preimages. | PASS |
| `files_intent` / `before_files` | Allow each P working entry at exact OLD or NEW; write missing NEW entries only. | PASS |
| `files_intent` / after each of five repair paths | Reconcile mixed OLD/NEW working files; require NEW index and unchanged paused entries. | PASS, five cuts |
| `done` | Recheck postconditions and replay idempotently. | PASS |

Thirteen named finish cuts passed. The spike injected interruptions **between operations**, including immediately after successful CAS/index syscalls before stage persistence. It does not claim power-loss atomicity or recovery from every instruction inside a file write. A production writer needs explicit ownership/reconciliation of temporary files, stale lock handling, and an intent before each destructive operation; never remove an unfamiliar lock or temporary file blindly.

## Limitations and fail-closed boundaries

- Serial execution and a quiescent checkout are required. Git ref CAS and the index lock do not create an atomic transaction across HEAD, index, filesystem and workflow state. The spike rejects observed drift; it does not solve a concurrent external writer racing between validation and file replacement. Require exclusive runner ownership and stop/ask if that cannot be established.
- Durable promise demonstrated: ordinary process restart at the named checkpoints. No sudden power-loss/storage-failure guarantee, no general rollback after partial application. A recognized partial finish resumes forward; unfamiliar state stops with evidence.
- Demonstrated stage-0 ordinary index entries, regular files, symlinks, executable bits and working permission bits. Index extension/flag preservation beyond per-path mode/OID was not measured. Reject or separately prove intent-to-add, unmerged entries, sparse/split index, skip-worktree/assume-unchanged, submodules, special files, hardlink/xattr/ACL requirements, filters/LFS and unusual repository layouts before supporting them.
- All spike inputs were generated harmless fixtures; no secrets or environment configuration were read. The fixture copier is not a production secret classifier: ordinary nonignored files can contain secrets. Production must reject sensitive `.env*`, credential/key paths and unsafe snapshot candidates rather than auto-copy them; ignored inputs are excluded. Private storage must be mode `0700` (the spike workspace is), with no payload bytes in logs. The private repository owns its own refs; no shared refs/remotes/alternates are configured. If a gate requires ignored files or external state, declare a separate safe gate-input contract; do not sweep them into the snapshot.
- Prefix/case-folding is conservative, not a complete proof for every filesystem alias/Unicode normalization rule. Symlinked ancestor paths, ambiguous case aliases, unsupported paths and structurally colliding additions/deletions must fail closed unless separately proven.
- Creation-time snapshot races, arbitrary repairs of paused paths, concurrent waves, nested repair, production workflow suspension/restoration, real lint/test hooks, PR/CI automation, and cleanup/pruning policy remain outside this Git experiment. No production/test files were edited by the spike; the only repository artifact it created is this document.
