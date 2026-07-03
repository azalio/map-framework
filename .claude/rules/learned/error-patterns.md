# Error Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Idempotent File Backups Need Timestamps** (2026-03-26): When creating backup files during upgrade operations, always use a timestamp suffix (not fixed .bak), because repeated upgrades silently overwrite previous backups, destroying the user's customizations permanently. [workflow: map-learn-improvement]
  ```python
  # WRONG: backup = dest.with_suffix(".bak")  # overwritten next run
  # CORRECT:
  ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
  backup = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
  ```

- **Sanitize Control Characters Before External Tools** (2026-03-26, hardened 2026-05-04): When building JSON that will be consumed by `jq`, log aggregators, or APIs via a bash pipeline (``$(...)`` substitution), strip the ENTIRE C0 control range U+0000-U+001F plus U+007F from string values before serialization — including `\t`, `\n`, `\r`. Python `json.dumps` escapes them correctly for strict JSON, but bash command substitution does not preserve byte-perfect roundtrip in all locales: jq then receives raw control bytes and aborts with `Invalid string: control characters from U+0000 through U+001F must be escaped`. Initial 2026-03-26 fix excepted `\n \r \t` and the bug recurred on multi-line artifact bodies. [workflow: behavior-fix]
  ```python
  # WRONG — keeps \n \r \t, jq still breaks via bash pipeline
  return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

  # CORRECT — flatten newlines first, then strip every control char
  text = text.replace("\r\n", "\n").replace("\r", "\n")
  text = text.replace("\n", " ").replace("\t", " ")
  return re.sub(r"[\x00-\x1f\x7f]", "", text)
  ```

- **Pre-existing Surfaced Failures Are Not Out-of-Scope** (2026-05-04): When a quality gate (`make lint`, `make check`, `pytest`, type-check) emits errors during a workflow, Actor must fix EVERY error the gate reports — including ones on pre-existing code outside the current subtask's diff. The gate is failing in the current run; the failure is not historical. Writing "pre-existing failure unrelated to ST-XXX" as a one-line dismissal silently disables the gate and accumulates broken-windows debt. Distinguish from pre-existing DORMANT tech debt (code smell that does not surface in current gate runs), which legitimately stays out of scope. Genuinely-deferrable surfaced failures require explicit user approval, not in-output justification. [workflow: behavior-fix]
  ```
  WRONG (Actor output):
    "Pre-existing lint failure unrelated to ST-001. Skipping."
    → gate still red; Monitor should reject this run.

  CORRECT (Actor output):
    Either: fix the failure as part of the subtask, OR
    Stop and emit CLARIFICATION_NEEDED:
      "make lint reports <error> on <file:line>, predates ST-001.
       Fix here, defer with user approval, or treat as new subtask?"
  ```

- **Static-Analysis Tool Output Is a Workflow Gate Regardless of CI Scope** (2026-05-12): When an Actor or Monitor runs a static-analysis tool (Pyright/Pylance/mypy/ruff) during a workflow — even if that tool is absent from the formal CI gate — its output is a mandatory workflow gate and `0 errors / 0 warnings / 0 informations` is the required bar. Classifying the output as "pre-existing static-analysis noise outside CI" is dismissal that bypasses the gate. The previous rule covers pytest/lint gates already in CI; this extends to dev-time tools that surface diagnostics in the conversation (IDE language servers, `<new-diagnostics>` blocks). Enforcing 0/0/0 in this workflow revealed a REAL bug: variable `entry` simultaneously typed as `Path` and `dict[str, object]` in the same scope — a logic error the "noise" verdict would have hidden indefinitely. [workflow: map-efficient]
  ```
  WRONG (Monitor verdict):
    "Pyright diagnostics are pre-existing and outside the CI gate; proceeding."
    → real type-safety bugs accumulate; loop variable reuse hides under the noise label.

  CORRECT (Monitor verdict):
    python -m pyright src/ tests/
    Expected: 0 errors, 0 warnings, 0 informations
    If non-zero → valid=false, list every line, route back to Actor.
    Bug caught this way: `entry: Path | dict[str, object]` — split into two named variables
    via cast() at the narrowing boundary.
  ```

- **Truncated Agent Recovery: Inspect Git State, Then Continue — Do Not Restart** (2026-05-27): When an Actor agent truncates mid-response (stops with prose like "Now insert the marker in predictor.md:" without completing the edit), the correct recovery is: (1) inspect actual git state (`git diff`, `git status`) to determine which edits were applied vs pending, (2) continue in the SAME agent thread via SendMessage for the pending pieces only. Do NOT restart the agent or re-issue the full subtask prompt — restart causes the agent to re-execute already-completed edits, either double-applying changes (e.g., inserting a marker twice) or producing conflicts. The git state is ground truth for what was actually done; the agent's last prose line is not. [workflow: map-efficient]
  ```bash
  # After Actor truncates mid-response:

  # Step 1: Determine actual state from git — do NOT trust the last prose line
  git diff --stat      # which files were modified?
  git diff HEAD        # what exactly changed?

  # Step 2: Identify pending work by comparing git state to the subtask plan.
  # Example: plan required marker in monitor.md + predictor.md + evaluator.md
  # git diff shows monitor.md done, predictor.md done, evaluator.md NOT in diff
  # → pending: evaluator.md only

  # Step 3: Continue in SAME agent thread (SendMessage), NOT a new subtask:
  # "Continue from where you stopped.
  #  Already done (confirmed via git diff): monitor.md, predictor.md.
  #  Remaining: insert marker in evaluator.md at the appendix boundary."

  # WRONG — restart with full prompt:
  # Actor re-inserts marker in monitor.md and predictor.md → duplicate markers
  # or conflicts requiring manual untangling.
  ```

- **Broad Revert Commands Destroy Uncommitted Work** (2026-05-12): Before running any broad automated batch-fix (regex replacement, `sed -i`, automated import insertion) on a file that holds in-progress work from earlier subtasks, COMMIT or STASH first — `git checkout -- <file>` or `git restore <file>` used to undo a bad batch-fix will also erase every uncommitted line on that file. In this workflow a Python regex script inserted `del branch_workspace` indiscriminately, breaking tests that DO use the fixture; the rescue `git checkout -- tests/test_map_step_runner.py` destroyed 451 lines of test work written across three previous subtasks that had never been committed. Recovery required a full Actor pass re-deriving assertions from source. [workflow: map-efficient]
  ```bash
  # WRONG — batch-fix on uncommitted multi-subtask work, then revert on failure:
  python3 batch_fix.py tests/test_map_step_runner.py   # breaks tests
  git checkout -- tests/test_map_step_runner.py        # destroys ALL uncommitted work

  # CORRECT — commit (or stash) first; revert then only undoes the batch-fix:
  git add tests/test_map_step_runner.py
  git commit -m "wip: ST-001/ST-002 test work — save before batch fix"
  python3 batch_fix.py tests/test_map_step_runner.py
  git checkout -- tests/test_map_step_runner.py        # safe: only undoes the batch
  ```

- **Verify File State via Git After Every Edit — Tool Return Is Not Ground Truth** (2026-05-30): After any Edit tool call, verify the change actually landed via `git diff` before proceeding — do NOT assume a non-error return means the content changed. When an Edit is issued with a stale or guessed `old_string`, the tool returns an error that is easy to miss in a batch of tool calls; the agent may believe the edit landed when nothing was written. Correct sequence: (1) Read the exact anchor lines verbatim from the file — never guess surrounding text from memory or context; (2) issue the Edit; (3) run `git diff -- <file>` and confirm the expected delta. An empty diff after an Edit is a red flag requiring investigation before any dependent action. Distinct from "Truncated Agent Recovery" (prose truncation): this is the silent stale-`old_string` no-op swallowed in a batch. [workflow: map-efficient]
  ```bash
  # Step 1: Read exact anchor BEFORE editing — never guess the surrounding text.
  # Step 2: Issue Edit.
  # Step 3: Verify ground truth — tool return is NOT sufficient:
  git diff -- path/to/file        # must show the intended delta
  # empty diff => edit did NOT land; find the mismatch and retry
  ```

- **Write Is a Destructive Overwrite — Check Existence Before Writing to Unowned Paths** (2026-05-30): Before calling Write on any path you did not create in the current session, check whether it already exists in git — Write silently overwrites pre-existing content with no warning or diff. In this workflow Write clobbered a `docs/improvement-plan.md` that already held a substantial REGISTRY/FOCUS backlog; it was caught only because `git status` showed the file Modified (not Added). Recovery required `git restore` then appending the new section. Correct protocol: run `git ls-files --error-unmatch <path>` (or check `git status`) before Write; if the file exists, APPEND (`cat >>`, or Read+Edit at a known anchor) rather than overwrite. Treat "my Write produced Modified, not Added" as a clobber red flag. Distinct from "Broad Revert Commands Destroy Uncommitted Work" (git restore after batch fixes). [workflow: map-efficient]
  ```bash
  git ls-files --error-unmatch docs/improvement-plan.md 2>/dev/null \
    && echo 'EXISTS — append, do not Write' || echo 'new file — Write is safe'
  # WRONG: Write('docs/improvement-plan.md', new_section)  # clobbers backlog
  # CORRECT: cat >> docs/improvement-plan.md << 'EOF' ... EOF   # append
  ```

- **In an Agentic Harness, Git State Is Ground Truth — Tool Returns Are Not** (2026-05-30, key insight): When operating through an agentic harness, treat every external dispatch and file mutation as inherently uncertain — Agent calls may QUEUE rather than fail (never retry blindly: see [[never-retry-a-queued-agent-dispatch]]), Edit calls may NOT land (always verify via `git diff`), and Write calls ALWAYS overwrite (check existence first). The harness layer between intent and execution introduces silent queuing, silent no-ops, and silent overwrites that make a tool's return value an unreliable proxy for filesystem state. Before every commit, verify with independent `git`/`grep`/`pytest` rather than trusting an agent's self-report (which can also be replayed/garbled by context compaction). [workflow: map-efficient]

- **Cross-Clone Editable-Install Contamination: Verify Package Source Before Trusting Subprocess Results** (2026-05-31): When a Python project is installed editable (`pip install -e` / `uv sync`) and more than one clone of the repo exists, `uv run <console-script>` (or any subprocess invoking the installed entry point) resolves the package through the editable `.pth` in the active `.venv` — which may point to a DIFFERENT clone than the worktree under edit. The subprocess exits 0 with no import error, but exercises the WRONG code, producing phantom failures (wrong file counts, missing markers, behavior that contradicts your edits). To verify the worktree under edit, import in-process (`sys.path.insert(0,"src")` + call functions directly) or run `python -m pytest` (honours the worktree). Never trust a `uv run <console-script>` subprocess as evidence about local changes. [workflow: map-efficient]
  ```python
  import mapify_cli, os
  assert os.getcwd() in mapify_cli.__file__, (
      f"Package resolves to {mapify_cli.__file__!r}, not this worktree — "
      "check editable .pth in .venv/lib/*/site-packages/")
  # Prefer in-process over subprocess for the code you're editing:
  #   sys.path.insert(0,'src'); from mapify_cli.delivery... import fn; fn(tmp)
  # NOT: subprocess.run(['uv','run','mapify','init', str(tmp)])  # may hit wrong clone
  ```

- **Tangled Multi-Edit Recovery: `git checkout HEAD -- <file>` Then One Complete Write** (2026-05-31): When several sequential Edit calls have left a file internally inconsistent — partial anchors matched the wrong location, edits applied against a stale mental model of the real HEAD shape, or context compaction shifted the agent's understanding — STOP issuing incremental Edits. Each further Edit narrows the search but adds another chance to mis-anchor against the now-diverged content. Recover by: (1) `git checkout HEAD -- <file>` to restore the known-good committed state; (2) Read the file for an accurate model; (3) one full-content Write incorporating all intended changes. Trigger: `git diff` shows structural artifacts (duplicate blocks, orphaned `else`) that were never part of any explicit Edit intent. Distinct from "Truncated Agent Recovery" (prose truncation, git state correct) and "Verify File State via Git After Every Edit" (per-edit check) — this is specifically "file is internally inconsistent; reset to known-good and rewrite whole". [workflow: map-efficient]
  ```bash
  git checkout HEAD -- src/mapify_cli/delivery/managed_file_copier.py  # restore baseline
  # Read the file (ground truth, not memory), then Write full intended content once.
  # Safe because Write now produces exactly the intended delta vs the last commit.
  ```

- **Harness Flap Output Capture: Redirect to a File and Read It Back; Treat Cancelled Batches as Unknown** (2026-05-31): Under harness flapping, safety-classifier delays, or batched-tool cancellation, inline stdout can arrive garbled, out-of-order, or empty while the call still exits 0 — acting on it yields false verdicts ("no errors" when the tool never ran). Reliable pattern: redirect to a temp file (`cmd > /tmp/out.txt 2>&1`) then Read the file (file I/O bypasses the streaming pipeline). If a batch is cancelled or unreadable, classify as "unknown" and re-derive ground truth from `git diff`/`git status`/`pytest` before any dependent action. Separately: ad-hoc `python3 /tmp/foo.py` can break with stdlib shadowing (e.g. `module 'inspect' has no attribute 'Parameter'`) if `/tmp` holds a same-named module — prefer `python3 - <<'PY' … PY` heredocs run from the repo root with `sys.path.insert(0,"src")`. [workflow: map-efficient]
  ```bash
  python -m mypy src/ > /tmp/mypy.txt 2>&1; echo "EXIT:$?" >> /tmp/mypy.txt
  # then Read /tmp/mypy.txt; if empty or no EXIT: marker -> harness flap, re-derive from git
  ```

- **`uv sync` Without Groups Omits Dev/Test Extras: Always Use --all-extras --all-groups in Dev** (2026-06-12): A plain `uv sync` (or `uv sync` after activating a fresh or different venv) omits `--all-extras` and `--all-groups`, leaving pytest, hypothesis, truststore, and ssl extras uninstalled. Tests that depend on these packages appear to fail for completely unrelated reasons: SSL trust-store mocks resolve to None, hypothesis-based tests are silently skipped, and Pyright reports 'pytest' as unresolved. These phantom failures consume debugging time chasing non-existent bugs in the code under test. The invariant for any development or CI shell: always run `uv sync --all-extras --all-groups` after creating, activating, or switching a venv. Treat `ImportError: No module named pytest` or `ssl module not available` as a venv-setup signal, not a code defect. [workflow: map-efficient]
  ```bash
  # WRONG — omits dev/test groups and extras; pytest/hypothesis/truststore not installed
  uv sync
  pytest tests/  # fails: 'No module named pytest', ssl mock -> None, hypothesis skipped

  # ALSO WRONG — activating a different venv without re-syncing
  source .venv/bin/activate  # switched venv
  pytest tests/              # same missing-extras failures

  # CORRECT — always sync with all extras and groups in a dev shell
  uv sync --all-extras --all-groups
  pytest tests/

  # Diagnose a phantom failure first:
  python -c "import pytest; import truststore; import hypothesis"
  # ImportError here means venv-setup issue, not a code bug -> uv sync --all-extras --all-groups
  ```

- **Decomposer Existence Claims Are Assumptions — Grep Before Dispatching Any 'Create New X' Subtask** (2026-06-29): A task-decomposer or plan that asserts "X does not exist yet" or scopes a subtask to "add X" is making an assumption about the live codebase, not a verified fact. Decomposers work from context summaries and miss existing implementations — especially in mature multi-module codebases. Acting on a false existence claim makes the actor implement a DUPLICATE of an existing component (e.g. duplicating a state machine from the orchestrator into the runner). Protocol: before dispatching any actor on a "create new function/class/module" subtask, grep the relevant source trees for the symbol; if it exists, fix the subtask scope before dispatch. A wrong existence claim that goes unverified propagates into duplicated machinery across all dependent subtasks. [workflow: map-efficient]
  ```bash
  # Plan: 'ST-010: add get_wave_step/validate_wave_step/advance_wave to runner — do not exist yet.'
  # WRONG: trust the claim -> actor creates a duplicate state machine
  # CORRECT: grep before dispatch
  grep -r 'get_wave_step\|validate_wave_step\|advance_wave' src/mapify_cli/templates_src/
  # -> map_orchestrator.py.jinja already defines them: claim is FALSE.
  # Re-scope ST-010 to GATE the existing orchestrator functions, not recreate them.
  # Any subtask verb 'add'/'create'/'implement new' requires a pre-dispatch grep.
  ```

- **Targeted Per-File Checks During a Subtask Are Not a Substitute for the Full Aggregate Lint Gate** (2026-06-29): Running `pyright <single-file>` / `mypy <single-file>` during a subtask is faster but has two systematic blind spots vs the project's aggregate gate (`make check` / `ruff check src tests`): (1) SCOPE — targeted checks run on one file; ruff F401/F811/E501 run across all of `src/` and `tests/`, surfacing unused imports introduced in any file touched this subtask; (2) RULE SET — pyright enforces type correctness; ruff enforces lint rules pyright ignores (unused imports, line length). A file that passes targeted pyright can still fail ruff at the aggregate level (it did: `sys`/`Any` F401 surfaced only at the final `make check`). Run the project's aggregate gate as part of each code subtask's verification step, not only at the final gate; per-file targeted checks are for fast iteration, not the commit-before-monitor gate. [workflow: map-efficient]
  ```bash
  # WRONG: per-subtask verification uses only a targeted single-file type-check
  pyright src/mapify_cli/parallelism_observability.py   # passes; ruff F401 not checked
  # CORRECT: run the aggregate gate the CI runs, at each code subtask:
  ruff check src/ tests/        # ALL files, ALL rules incl. F401
  python -m pyright src/         # ALL source files
  pytest tests/ -x -q
  # If make check fails on F401 after per-file pyright passed -> scope mismatch.
  ```

- **Awk Two-Address Range Silently Collapses When Start and End Patterns Co-Match the Same Line** (2026-07-03): An awk range `/start/,/end/` is NOT guaranteed to span multiple lines — if the start and end regexes are not mutually exclusive and can both match the SAME line (e.g. end is an unanchored prefix-superset of start, like `/## \[/` matching `## [Unreleased]`), awk closes the range immediately after that one line and the extraction silently degenerates to a single line instead of erroring. This is dangerous specifically because it fails SILENTLY: downstream consumers (a bullet-point counter via `grep -c`, a content-display step) receive a plausible-but-wrong single-line result and report a confidently-wrong number (here: a CHANGELOG-completeness gate always reported 0 entries) rather than crashing, so the defect can survive undetected across many runs/releases until someone manually cross-checks the output against ground truth. Fix by replacing the range with an explicit flag state machine, using `next` to exclude the start line from also being tested against the end pattern. [workflow: map-release]
  ```bash
  # WRONG: range collapses to exactly 1 line whenever start and end co-match
  awk '/## \[Unreleased\]/,/## \[/' CHANGELOG.md
  # CHANGELOG.md's actual heading '## [Unreleased]' matches BOTH regexes on the
  # same line -> awk opens AND closes the range there -> output is just that heading
  # -> grep -cE '^- ' on this output is always 0, even with 9 real entries below it.

  # CORRECT: explicit flag; 'next' skips the start line so it can't also end the range
  awk '/^## \[Unreleased\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md
  # f=1 set on start line, but 'next' means this line is never tested against
  # the end pattern or printed; f=0 clears on the FIRST subsequent '## [' heading,
  # also excluded from output ('f' block only prints when flag is already 1).
  ```
