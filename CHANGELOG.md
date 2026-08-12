# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.25.0] - 2026-08-12

### Added
- **`/map-review` computes its verdict instead of choosing one (closes #406).** `write_review_verdict_ledger` normalizes Monitor/Predictor/Evaluator envelopes into a finding registry and applies a closed decision table (`review_verdict_table.v1`), writing `.map/<branch>/review-verdict-ledger.json` and a human-readable `.md`. Reviewer envelopes are captured to `.map/<branch>/review-agent-<role>.json` and read via `--monitor-file`/`--predictor-file`/`--evaluator-file`/`--adversarial-file`. The table counts every finding whose status is `active` or `downgraded`. Only a finding proven `minor` may be tombstoned — by any route — so neither a missing `reach_evidence` field, nor a reviewer's own `was_present_before_pr=true`, nor an operator objection can erase a blocking finding from the gate; each downgrades severity to `needs_investigation` instead, and doing so to a CRITICAL sets `escalation_required`. `needs_investigation` sits inside that floor because it means "severity not established", not "low severity". Missing, unreadable or malformed reviewer output is itself an active finding: an empty registry reads as "the review was not observed", never as a clean pass. `journal.previous_verdict` is recovered from the ledger on disk, so the journal spans runs.
- **Objection channels for contesting a review finding (#406).** `record_review_objection --finding-id RVF-001 --channel <channel> [--evidence …]` is the only supported way to remove a finding. `quote_absent`, `wrong_category` and `different_version` are checkable against the change and REQUIRE evidence; they remove a `minor` finding outright and downgrade anything above it with `escalation_required` set, because the objection's evidence is free text that nothing verifies. `unverifiable_context` keeps the finding and escalates to a human, so PROCEED becomes unavailable; `no_new_fact` keeps the finding and repeats the previous verdict. Objections are stored in `.map/<branch>/review-objections.json`, bound to the claim they were raised against so a stale objection cannot drift onto another finding, and limited to one per finding so a registry cannot be worn down by repetition.

- **Wayfind amend commands for post-resolution wording fixes (#396).** `amend_resolution`
  updates a resolved ticket's gist and/or resolution path in place; `amend_out_of_scope`
  does the same for an out-of-scope entry's reason/gist. Both touch no structural
  invariant, are allowed on a handed-off map, and flag `handoff_refresh_needed`.
- **Wayfind one-non-research-resolve-per-session cap is now opt-in (#395).**
- **Role-local persistent memory for learning agents (#379).**

### Fixed
- **PyPI publish action bumped to v1.14.2 so uploads accept Metadata-Version 2.5.**
  `pypa/gh-action-pypi-publish@v1.13.0` bundles an older twine that rejected the
  3.25.0 wheel with `InvalidDistribution: '2.5' is not a valid metadata version`
  even after the repo's own `twine check` step was fixed; v1.14.2 ships twine v7
  with core-metadata 2.5 support. Applied in `release.yml` and `test-pypi.yml`.
- **GitHub Release notes are no longer an empty stub.** The changelog-excerpt
  extraction used a two-address awk range whose start and end patterns both match
  the `## [X.Y.Z]` heading line, collapsing the range to that single line and
  yielding an empty excerpt — every past GitHub Release body fell back to
  "See CHANGELOG.md for details.". Replaced with an explicit flag state machine
  in `release.yml`, the release-checklist issue template, and the map-release
  skill.
- **Atomic writes for `review-verdict-ledger.json` and `review-objections.json` (#409).**
  Both files were written with non-atomic `write_text()` and could be corrupted by a
  mid-write kill; they now go through `_write_json_file()` (temp file + `os.replace`).
- **Non-English Monitor feedback is no longer dropped from retry artifacts (#404).**
  The keyword filter is a ranking hint only; the full original text is always forwarded.
- **Six proactive bugs in `wayfind_runner`, `map_step_runner`, and settings deny globs.**
  `_resolve_evidence_path` rejects absolute paths before path-joining (POSIX join
  discarded the base and bypassed containment); `add_ticket` accepts only open fog
  entries as `from_fog`; `validate_mutation_boundary` catches subprocess `OSError`
  in `_resolve_subtask_diff_base`; `record_scope_baseline` writes atomically; git
  porcelain quoted filenames (spaces) are un-quoted; `Write`/`MultiEdit` deny
  patterns now mirror `Edit` for `.env*`/credentials/secret globs.
- **`wayfind_runner` evidence reads catch `OSError`; `.env` deny glob covers
  subdirectories (#401, closes #400).**
- **Five bugs: scope-classifier crash on non-integer config, snake_case config
  dead-toggle, zero scale-threshold reset, `needs_clarification` verdict without
  blocking questions rejected, governance category drift for `map-wayfind`/`map-architecture` (#399).**
- **Secret/credentials deny globs scoped by extension (#397).** Broad
  `Edit(**/*secret*)`-style globs blocked normal source files like
  `secret_service.go`; deny patterns now target only secret-material formats
  (`.yaml`, `.yml`, `.json`, `.toml`, `.env`).
- **Class-scoped instance-method fixture promoted to module scope (#393).**
- **`.claude/settings.json` parity is gated via `make check-render` (#390).**
- **CI/release `twine check` no longer rejects Metadata-Version 2.5 wheels.** The
  `packaging>=24.2,<26` cap from #195 forced a downgrade to `packaging` 25.0, which
  does not recognize the Metadata-Version 2.5 that current setuptools emits —
  the `build` job failed with `InvalidDistribution: '2.5' is not a valid metadata
  version`. CI, TestPyPI, and PyPI release jobs now install `packaging>=26`.

### Documentation
- **`wayfind_status` is documented with `--slug`, not a positional argument (#408).**
  The map-wayfind SKILL.md told the operator to run `wayfind_status <slug>`, which the
  CLI rejects; all other documented wayfind commands were audited against their argparse
  definitions and match.
- **ARCHITECTURE.md refreshed to record the #404 feedback-preservation fix.**

### Changed
- **The review stage gate is bound to the computed verdict (#406).** `write_stage_gate review <verdict>` is refused, and no gate file written, when `<verdict>` contradicts `computed_verdict` or when no ledger exists for the branch. Enforcement is on by default with no calibration period; `MAP_REVIEW_LEDGER_ENFORCE=0` is the explicit opt-out. Other stages are unaffected. `/map-review`'s closeout now takes `FINAL_VERDICT` from the ledger output rather than asking the model to pick one of `PROCEED|REVISE|BLOCK`.

## [3.24.1] - 2026-07-25

### Fixed
- **`map-review` closeout no longer errors on its own documented verdicts (closes #388).** `map-review`'s SKILL.md documents `PROCEED | REVISE | BLOCK`, but `write_stage_gate` only accepted `{ready, needs-revision, blocked}`, so following the skill verbatim always failed with `Invalid verdict: revise`. `write_stage_gate` and `write_plan_review` now normalize `PROCEED -> ready`, `REVISE -> needs-revision`, `BLOCK -> blocked` (via a shared `normalize_gate_verdict` helper); unknown verdicts still error. Also fixed the secondary arity mismatch: the Gate Unlock call site passed the review summary as the THIRD positional arg, silently landing it in `source_artifact` instead of `notes` — both call sites in `SKILL.md` and the Codex `review-reference.md` port now pass `<stage> <verdict> <source_artifact> <notes>`.

## [3.24.0] - 2026-07-25

### Added
- **`disallowedTools` frontmatter on non-writer agents (closes #378).** `monitor`, `research-agent`, `predictor`, and `evaluator` now have their capability boundaries enforced at the harness level instead of relying on prompt text alone: `monitor`/`research-agent` disallow `Edit`/`Agent`; `predictor`/`evaluator` disallow `Edit`/`Write`/`Agent`.

### Fixed
- **Stale `Write(...)`/`Glob(**)` permission rules no longer emit startup warnings.** Claude Code now matches all file-editing tools (Edit/Write/NotebookEdit) against `Edit(path)` rules only, and all file-reading tools against `Read(path)` rules only. Two shipped surfaces predated that consolidation: `settings.json.jinja`'s 6 redundant `Write(...)` deny/allow entries (already covered by existing `Edit(...)` rules) were removed, and `configure_global_permissions()`'s `Glob(**)` entry (written into the user's global `~/.claude/settings.json` on every `mapify init`) was changed to `Read(**)`, with a one-time migration that also heals any already-installed stale `Glob(**)` rule.
- **Claude Code harness output-scan markers no longer trip strict JSON gates (closes #380).** Claude Code v2.1.210+ may prepend a `[harness: subagent output matched instruction-shaped pattern(s):` marker line to a subagent report; `detect_truncated_agent_output` now strips known marker lines before JSON parsing instead of treating them as a truncation signal, so valid Monitor/Predictor/Evaluator/Actor payloads are no longer rejected.
- **`git status` scope checks now detect files inside pre-existing untracked directories (closes #376).** `validate_mutation_boundary`, `record_subtask_baseline`, `record_scope_baseline`, `refresh_blueprint_affected_files`, and `_current_subtask_changed_files` now use `git status --porcelain -uall` instead of the default, which previously collapsed an untracked directory to a single `?? dir/` entry — making new files added inside a pre-existing untracked directory invisible to the mutation-boundary check.
- **CI's lint step could never fail (`ruff`/`mypy`/`pyright` were unenforced on every PR).** `.github/workflows/ci.yml` used `which ruff && ruff check ... || echo skip`, which falls through to the no-op branch whenever the lint command itself fails, so a red ruff/mypy/pyright run always reported green. Rewritten to run the three checks directly so a real failure now fails the job.
- **1537 pre-existing ruff violations resolved (`make lint` was red on `main`, invisible to the broken CI gate above).** Fixed across `src/`, `tests/`, and the shipped hook/script templates: explicit `subprocess.run(..., check=False)` (311 sites, behavior-preserving — `False` is the existing default), UTC-aware `datetime.now()` in state/log/backup timestamps (36 sites, matching the project's existing UTC convention), collapsed redundant nested `if`/`with` blocks, restored 6 `# pyright: ignore[reportMissingImports]` suppressions that an earlier automated pass had collaterally stripped alongside an unrelated unused-`noqa` cleanup, and misc modernization (`Optional[X]` → `X | None`, `Dict`/`List` → `dict`/`list`, f-strings, import sorting). Two rule categories were disabled via `pyproject.toml` config instead of restructuring code: `B008` (typer's `Option(...)`/`Argument(...)` argument-default idiom) and `TRY004` (this codebase deliberately raises `ValueError`, not `TypeError`, from isinstance-based input validators — a tested, documented contract).

### Documentation
- Redesigned README with a native SVG visual system (hero, loop diagram, section headers) and restructured content — proof before claims, case study promoted, implementation details collapsed into `<details>`.

## [3.23.0] - 2026-07-18

### Added
- **`/map-wayfind` — decision-frontier wayfinding before planning (closes #362).** A new opt-in skill for large or foggy efforts where `/map-plan` would force premature decomposition. It builds a durable, repo-level decision map under `.map/wayfind/<slug>/` and resolves open decisions one at a time behind a claim-before-work frontier, with a "fog of war" for questions that cannot yet be stated sharply. Three explicit modes: `chart` (start a map), `work` (resolve one ticket), `handoff` (finish). Tickets are typed `research | prototype | grilling | task`; `prototype`/`grilling` are human-in-the-loop and cannot be resolved until a verbatim human answer is recorded via `record_human_input`. All state mutations go through the new stdlib-only `wayfind_runner.py` (canonical `state.json` + regenerated `map.md`/`tickets/*.md` views); invariants — DFS cycle-freedom, one-non-research-resolve-per-session, the human-in-the-loop gate, and the terminal handoff condition (fog empty AND no active claims AND every ticket resolved/out-of-scope) — are enforced in the runner. `emit_wayfind_handoff` writes a `handoff.md`/`handoff.json` pair and registers a new `wayfind_handoff` artifact-manifest stage; `/map-plan --wayfind <slug>` (or a single-candidate offer via `list_handoffs`) pre-seeds the spec's Decisions Made / Out of Scope / Open Questions. Maps are committed by default so decisions are durable; `chart` warns about the commit-by-default privacy note and the per-slug opt-out. (Also syncs the artifact-manifest JSON schema to the stage-name authority, adding the previously-missing `approval_hold`/`worktree`/`context_usefulness` stages.)
- **Scale-adaptive intelligence — automatic scope→workflow-depth mapping (closes #287).** A scale-adaptive config plus a scope classifier (Python layer) with a `classify_scope.py` entry-point script route a task to the right planning depth; `/map-plan`'s Codex variant gains explicit `--light`/`--deep` modes, and the Scale Advisory output was corrected. Documented in `docs/ARCHITECTURE.md`.
- **SpecKit-style preset composition engine (#291).** Layered template resolution via a new `mapify preset` command family: `list` + `add` (Slice 1); `remove` / `enable` / `disable` / `resolve` (Slice 2); and a composition engine with `render` + `set-priority` supporting prepend/append/wrap strategies (Slice 3).
- **`/map-architecture` skill — architecture-deepening reports for hotspot modules (closes #363).** A new skill (inspired by mattpocock/skills) that produces an architecture-deepening report for hotspot modules.
- **`mapify prompt-profile list` command (#353, slice 1).** First slice of eval-gated prompt-profile canary/rollback controls: lists the available prompt profiles.
- **GRACE semantic code-contract anchor eval (#339, slice 1).** First slice of a semantic code-contract anchor eval for bug-fix workflows.
- **Implementer-readiness review artifact before decomposition (closes #348).** A new implementer-readiness review artifact runs before task decomposition; `docs/ARCHITECTURE.md` refreshed to document the gate.
- **Context-usefulness feedback loop for recall ranking (closes #343).** Feeds observed context usefulness back into MAP recall ranking.
- **Trajectory-level outcome eval with side-by-side regression reports (#351).** Adds a trajectory-level outcome eval (from arXiv:2607.06624) producing side-by-side regression reports.
- **`/map-plan` → `/map-wayfind` off-ramp for too-foggy tasks (#365).** When a task is too foggy to decompose, `/map-plan` now offers a Workflow-Fit off-ramp that routes to `/map-wayfind`.

### Fixed
- **`abandon_workflow` escape hatch for stuck workflows (closes #360).** `workflow-gate` previously blocked all repo edits on a stuck `INITIALIZED` workflow that had no plan and no resolvable path to archive; a new `abandon_workflow` escape hatch lets the operator cleanly exit the stuck state.

## [3.22.0] - 2026-07-13

### Fixed
- **`workflow-gate.py` orthogonal-file relief now applies to every blocking phase, and out-of-repo paths are always allowed (closes #164).** A prior fix (#174) scoped the RESEARCH-phase block to the current subtask's `affected_files`, allowing Edit/Write to files outside that surface — but only during RESEARCH, and it deliberately kept blocking paths that resolve entirely outside the repository. Both choices reproduced the original friction: a report against `neuro-vlad` hit the identical block during INIT_STATE while editing `~/.claude/CLAUDE.md`, a path outside that repo's tree entirely. `is_orthogonal_to_current_subtask()` now treats out-of-repo paths as unconditionally orthogonal (no subtask's `affected_files` can ever legitimately name a path outside the repo it was declared in), and the orthogonal-relief exception in `main()` fires for any blocking phase, not just RESEARCH. The Bash-write bypass (`cat >`, `tee`, `sed -i`) remains a documented, deliberately deferred limitation.
- **End-of-MAP-flow: sequential completion left `workflow_status` stuck at `IN_PROGRESS`, silently disabling every completion-gated hook, and the post-completion edit gate misled the agent into thrash.** `validate_step`'s sequential terminal transition set `current_step_phase=COMPLETE` but never `workflow_status=WORKFLOW_COMPLETE`/`completed_at`, so the most common completion path (a sequential `/map-efficient` or `/map-task` run) finished half-marked and every `WORKFLOW_COMPLETE`-gated hook (`scrub-internal-ids`, and any future teardown) silently no-op'd on it. Completion is now atomic at that site (all three fields + `completed_at`), matching `mark_workflow_complete`/`mark_subtask_complete`. On a finished branch the `workflow-gate.py` block message no longer says "Call the Actor agent first" — it names the clean exits (`python3 .map/scripts/map_orchestrator.py archive` / `/map-review`) and instructs the agent to STOP and report rather than edit `.map/` state or the runner; the gate also treats `workflow_status=WORKFLOW_COMPLETE` as permissive regardless of the phase label, so a finished branch never hard-blocks a follow-up edit. `workflow-context-injector.py` replaces silent suppression on a terminal state with a one-shot, low-pressure completion notice (archive/review guidance) for editing tools — refining #317's no-misleading-banner invariant (Bash stays silent). Design was llm-council-reviewed (conv `0cd9bcc7`).
- **`validate_step` false-progress and scope-warning double-call eliminated on committed subtasks (closes #162).** The false-progress check re-read `step_state.json` from disk via `_resolve_subtask_diff_base`, a secondary read that could return stale data in container environments where `save()` lacks `fsync()`; it now checks the already-loaded in-memory `state.subtask_results` for a recorded `commit_sha` (a present SHA proves the subtask was committed) and skips the check, so no second call is ever needed. Separately, the scope-warning guard used to return `valid=false` on first occurrence and demand an identical second call to advance — pure ceremony in operator-driven flows with no Actor to intervene; it is now advisory-only (records into `scope_feedback_subtasks`, advances normally, surfaces out-of-scope files as `scope_warning` metadata on the success response).
- **`tdd.enforce` now documented in `generate_default_config()` (closes #340).** The `tdd.enforce` option shipped in #285 with a `MapConfig` field and YAML alias but was absent from the generated default config, so `mapify init` users had no way to discover it. A commented example block now documents its behavior and default, and new `TestVc9DefaultConfigCompleteness` regression tests prevent future config options from being silently omitted from the generated default.
- **`map_orchestrator.py` resolves the project root from the caller's git toplevel, not the script anchor (closes #328).** `main()` anchored cwd exclusively to `Path(__file__).resolve().parents[2]`, silently operating on the main clone when invoked by absolute path from a git worktree lacking its own `.map/scripts/` copy. Resolution priority is now: `CLAUDE_PROJECT_DIR` env var → `git rev-parse --show-toplevel` from the caller's cwd (correct for worktrees) → the script-anchored fallback (legacy behavior for non-git callers). An INFO line to stderr flags when the resolved root differs from the anchor so cross-checkout usage is auditable.
- **Safety-guardrails false positives, PyYAML error status, and `set_waves` install-path fallback (closes #319, closes #320, closes #321).** `safety-guardrails.py` matched dangerous patterns against the full path, blocking benign files under directories whose names contained security words (e.g. `secrets-injector/values.yaml`); it now matches only `os.path.basename(path)`. `parse_requirements_index` collapsed missing-PyYAML and malformed-YAML into one `malformed` status, misleading users whose spec was fine but PyYAML absent; `ImportError` now returns a distinct `pyyaml_missing` status with an actionable install message. `set_waves`' `ImportError` fallback only searched source-checkout layouts, missing `uv tool install` / `pipx` locations; the candidate list now covers common installed-package paths.

### Added
- **Mandatory TDD enforcement for `/map-tdd` (`tdd.enforce`, closes #285).** When `tdd.enforce: true` in `.map/config.yaml`, `/map-tdd` enforces the Iron Law ("NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST") instead of only preaching it: a mandatory RED-GREEN-REFACTOR cycle, a 14-item Red Flags list, an 11-item Rationalization Table with counters, a Spec Compliance Reviewer (adversarial, `SPEC-COMPLIANT` verdict) and a Code Quality Reviewer gated behind it, plus a Monitor `tdd_violation` verdict that detects code-before-test and rationalization patterns. Backed by a `MapConfig.tdd_enforce` field with a `tdd.enforce` YAML alias (dead-toggle guarded).
- **Durable approval-hold artifacts in the step runner (closes #344).** New `create_approval_hold` / `decide_approval_hold` / `list_approval_holds` / `get_pending_holds` commands provide a human-gate mechanism for risky workflow actions. Branch-scoped JSON store (`approval_holds.json`) plus a per-hold Markdown report; sequential IDs, idempotent on same kind+summary; a `pending → approved | denied | expired | cancelled` state machine over five hold kinds (`safety_guardrail`, `autonomy_posture`, `template_overwrite`, `plan_approval`, `dangerous_action`); a new `approval_hold` manifest stage; and a `resume_blocked` flag for orchestrator polling. Summaries are redacted — no raw secrets or credential values.
- **`mapify governance report` — MAP behavior-shaping asset inventory (closes #342).** `mapify governance report [PATH] [--json] [--out FILE]` inventories installed skills, hooks, references, and learned rules from `.claude/` and classifies each asset under six governance categories (Charter, Policy, Context, Harness, Oversight, Learning). Hooks are classified as **enforced** (runtime controls); skills/references/rules as **prompt-only**. A Gaps section flags missing key hooks (`workflow-gate`, `safety-guardrails`) and prompt-only policy claims lacking a backing harness control.
- **`mapify domain-skill init` — project-local reference-skill bootstrap (closes #338).** Scaffolds a project-local `.claude/skills/<name>/SKILL.md` without fabricating content: discovered facts (project name, README summary, key dirs, safe commands) come from local config files, and missing data becomes explicit TODO placeholders. Secret filenames are never read; the generated skill and CLI output both warn against committing secrets, and the skill is excluded from `skill-rules.json` so it never conflicts with MAP's shipped global catalog.
- **Reversible config-entry ownership and `mapify uninstall` (closes #314).** MAP-owned provider config merges (MCP servers, statusline) are now tracked in `.map/mapify.lock.json` under a `config_entries` list, enabling safe removal via `mapify uninstall`. A new `ConfigEntry` records the file, dot-notation key path, install time, and version; `reconcile_config` removes only MAP-owned entries whose current value still matches the canonical MAP config (user-modified entries are skipped, absent ones marked missing). Manifests without the field default to `[]` for backward compatibility.
- **Install manifest/lock for MAP-managed provider surfaces (closes #313).** `mapify init` (Claude and Codex) writes a scan-based install manifest to `.map/mapify.lock.json` recording every MAP-managed file with its `template_hash`, `content_hash`, `management_mode` (fenced/full/hooks-merge), and committed flag. The new `mapify check-installed` command compares the current tree against the manifest and reports missing, drifted, and orphaned managed files (exit codes 0/1/2). Local-only files (`settings.local.json`, symlinks) are excluded from the committed manifest; no absolute paths or secrets are stored.
- **Optional local structural code-map provider for MAP research (closes #310).** An opt-in, no-network structural code-map provider surfaces symbol/structure context for the research phase, letting Actor localization work from a real structural map rather than blind reads.
- **Structural-discovery ROI comparison for research-eval (closes #311).** New `research_eval_compare` module runs a side-by-side A/B comparison of two `ResearchEvidence` runs (baseline vs treatment), scoring quality metrics (precision/recall/F1) and exploration-cost metrics (location count, stale count, over-broad count, avg span) **independently**, so token/LOC reductions cannot mask lower localization quality.
- **Minimality A/B benchmark harness (closes #312).** A deterministic, no-network eval harness that proves MAP minimality is active and isolated without live model calls. `build_doctrine_block()` mirrors the runner's `_minimality_doctrine_block()` so each arm's context is independently verifiable; three fixture tasks (over-build trap, safety-guard invariant survival, irreducible convergence); a contamination check (off arm must lack `<MAP_Minimality_Doctrine>`, treatment arms must carry it — hard FAIL on mismatch); a safety check (required patterns must appear in both arms); and a warn-only LOC-delta check. Report persisted to `.map/eval-runs/minimality/<timestamp>.json`.
- **Deterministic boundary-quality eval for architecture plans (closes #316).** `boundary_quality_report.py` — a pure-Python advisory evaluator working from `blueprint.json` alone (no network/model/structural-map) — flags `FILE_SHARED_ACROSS_BOUNDARIES` and `CROSS_BOUNDARY_DEP_PRESSURE` (warn), plus `REFACTOR_WITHOUT_TEST_PAIR` and `LOW_COHESION_SUBTASK` (info). Findings are advisory only; hard errors remain in `validate_blueprint_contract`. Subtasks related by a dependency edge suppress file-sharing and pressure warnings.
- **MAP Prompt Library catalog (`docs/PROMPT_LIBRARY.md`, closes #326).** 14 copyable prompt recipes grouped by SDLC phase (Understand, Plan, Build, Review, Learn) and role (Engineer, Tech Lead, Operator/Maintainer), each with prompt text, fillable slots, MAP surface, prerequisites, why-it-works, and completion signal; plus a prompt-pattern audit table classifying 9 Claude Code Prompt Library patterns against MAP's implementation. Docs-only — no agent/skill prompt bodies or template sources changed.
- **Adversarial governance violation fixtures (#350).** `tests/test_governance_attack_fixtures.py` adds 16 tests spanning seven enforcement surfaces (orchestrator state machine, strict mutation-boundary gate, false-progress gate, wave lifecycle, safety-guardrails hook, workflow-gate hook, run-health schema), each with a violation fixture (must reject) and a positive-control fixture (must allow) to exercise deny/allow symmetry.
- **`map_orchestrator.py archive` command + auto-archive on branch reuse (end-of-MAP-flow teardown).** A finished branch's `.map/<branch>/step_state.json` used to linger indefinitely; the gate fail-opens on absent state, but a stale terminal file kept the branch looking "in work" and left the agent to infer completion (and thrash). The new idempotent `archive` command retires a COMPLETED run by renaming `step_state.json` → `step_state.completed-<utc-ts>.json` (the gate then fail-opens and the injector goes quiet); it is a no-op when there is no active state and refuses to touch an in-flight run. Archival is **deferred by design** — it never fires the instant a run reaches COMPLETE — so `/map-review` → `reopen_for_fixes` keeps its review window; instead `initialize_workflow` auto-archives a prior COMPLETED run when a new `/map-*` workflow starts on the branch, so branch reuse always starts clean (the return payload carries `archived_prior`). Design was llm-council-reviewed (conv `0cd9bcc7`).

## [3.21.0] - 2026-07-02

### Changed
- **Parallel execution defaults flipped ON (`worktree.isolation` off→auto, `execution.concurrent_dispatch` false→true, Slice 6 of #303).** Concurrent wave execution is now **ON by default** for repositories that are git repos with a parallel-ready plan (>=2 independent subtasks in a wave). Off-ramps (either is sufficient): (1) **global kill-switch** — set `MAP_EFFICIENT_SEQUENTIAL_ONLY=1` in your environment; forces the full legacy sequential path, byte-identical to pre-5a behavior, regardless of config; (2) **per-repo opt-out** — set `worktree.isolation: off` and/or `execution.concurrent_dispatch: false` in `.map/config.yaml`. The `auto` isolation mode degrades gracefully to sequential with a warning when git worktrees are unavailable (non-git repo, shallow clone, detached HEAD). Default `worktree.isolation` `MapConfig` value: `"off"` → `"auto"`; `concurrent_dispatch` `MapConfig` value: `False` → `True`; matching defaults in the step-runner config readers (`_worktree_isolation_mode`, `_concurrent_dispatch_enabled`). The `select_execution_strategy` and `compute_dispatch_gate` functions now check the kill-switch as their **first** gate (before any config read or concurrency probe), backed by a new shared `_sequential_only_env()` helper and a stable `WAVE_REASON_SEQUENTIAL_ONLY_ENV` reason code.

### Added
- **`/map-review` ported to the Codex provider.** `mapify init --provider codex` now ships a `map-review` skill (`$map-review`) alongside `map-plan`/`map-efficient`, feature-parity with the Claude skill: normal mode dispatches `monitor`/`predictor`/`evaluator` via `spawn_agent(agent_type=...)` through two new Codex agent configs (`predictor.toml`, `evaluator.toml`, condensed from the canonical Claude prompts, registered in `config.toml`); adversarial mode runs the same three-pass in-session review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) without a new agent-dispatch primitive; `--cross-ai <runtime>` reuses `run_cross_ai_review` verbatim, preserving the secret-scan/injection-detection/`EXTERNAL UNTRUSTED REFERENCE` trust boundary and its fall-through-never-hard-stop behavior. The skill ships as a `SKILL.md` + `review-reference.md` + `adversarial-reference.md` split (mirroring `map-efficient`'s reference-file pattern), reuses every provider-neutral CLI verb (`create_review_bundle`, `build_review_prompts`, `shuffle-sections`, etc.) unmodified, and contains zero Claude-only API tokens (verified by `test_ac10_no_claude_refs_anywhere`).
- **Concurrent Actor dispatch for parallel waves (`execution.concurrent_dispatch`, part of #303 Slice 5b).** Activates same-turn concurrent dispatch of Actor subagents within a parallel wave, previously scheduled but always run sequentially. Flag-gated (`execution.concurrent_dispatch: false` by default) so the default code-path is byte-identical to Slice 5a; defaults flip only in Slice 6. Key components: `compute_dispatch_gate` (strict conjunction — `concurrent_dispatch` AND `concurrency_allowed` AND `concurrency_ready` AND `isolation != off`; hard-aborts with a `ConfigError`-equivalent on any config contradiction, fail-closed rather than degrading silently), `run_concurrent_wave` (splits the wave into sub-batches of `execution.max_actors` and dispatches each sub-batch; atomic per-sub-batch merge via `merge_wave_worktrees`), `abort_wave_group` (whole-group rollback — reverts every worktree in the group back to wave base, bounded by `execution.max_wave_retries`), `record_dispatch_actual` (clock-free phantom-parallelism classifier using `max_in_flight` replay — worktree SHA proves isolation but NOT concurrency; emits `phantom_parallel` evidence when actors ran but no concurrent overlap is detectable). Test harness uses barrier-based determinism (no wall-clock sleeps); HC-1 leak-guard suite validates no cross-subtask state leaks under concurrent dispatch. Council review split this into 5a (infrastructure) and 5b (activation); this entry covers 5b.
- **`deferred_nondeterministic` wired into the core Monitor verdict path (completes #252).** The flaky-triage primitives (`run_/record_/validate_flaky_test_triage`) and the `defer_flaky_subtask` close+advance command already existed, but were **disjoint** from the Monitor verdict path: Monitor could only emit `valid:true`/`valid:false`, had no field to signal a flaky defer, and `validate_step 2.4` could only pass or hard-stop — so a confirmed flake forced an out-of-band manual `defer_flaky_subtask`. The third Monitor outcome is now part of the structured verdict. (1) The Monitor schema gains an OPTIONAL structured `disposition: {kind, check_id}` field (`kind` enum currently `{deferred_nondeterministic}`), absent for normal verdicts, with guidance to emit it on confirmed mixed pass/fail evidence instead of demanding a fake Actor fix. (2) `validate_step 2.4 --disposition deferred_nondeterministic --check-id <id> --monitor-envelope -` routes to the existing `defer_flaky_subtask` **in-process** (the single owner of the close+advance transaction), placed BEFORE the recommendation gates so a defer carrying `recommendation=needs_investigation` is not hard-stopped. (3) **Anti-gaming** (llm-council-reviewed, conv `d3ddca63`): the deferral is honored ONLY when the Monitor envelope structurally backs it — `valid:false`, non-empty `failed_checks`, and a structured `disposition` whose kind + `check_id` match the flags — AND the sidecar holds mixed pass/fail evidence for that `check_id` (re-validated from disk by `defer_flaky_subtask`). A Monitor cannot dodge a real deterministic failure or a green check by merely claiming "flaky"; `recommendation in {revise, block}` together with a disposition is rejected as a contradiction. (Note: the Monitor schema's `failed_checks` lists failed quality *dimensions*, a different namespace from a flaky check id, so the binding is "Monitor admits a dimension failure + dispositions match" rather than "check_id ∈ failed_checks".) (4) **Verdict vs routing:** a deferred run returns `valid:false` + `deferred:true` + `non_green_outcome:true` (a deferral is NOT green — it is a routing decision, not a clean pass); the CLI exits `0` on a deferral (not a hard-stop) and `1` only on a true invalid verdict. A single source-of-truth `MONITOR_DISPOSITIONS` policy dict drives the routing, the CLI `--disposition` surface, and a drift-guard test (the Monitor prompt must name every supported disposition). Closes the last core slice of #252.
- **Context-budget statusline for all MAP sessions (`map-statusline.py`, completes #284 Phase 3).** A Claude Code `statusLine` render command that shows live context-window usage at a glance: `[Opus] MAP ctx 47% (94k/200k) · feature-x · ST-003 ACTOR`. It reads the usage Claude Code **pre-computes** on stdin (`context_window.used_percentage` / `context_window_size` / `total_input_tokens`), so it does NO transcript parsing, no token counting, and no network — it formats already-available numbers plus the git branch (read directly from `.git/HEAD`, no `git` subprocess; handles the linked-worktree `.git`-as-file case) and the active MAP subtask (best-effort `.map/<branch>/step_state.json`). Output is **never blank and never crashes** — any error degrades to a minimal safe line; it shows `--%` before the first API response (instead of a misleading `0%`) and a `200k?` uncertainty marker when the harness omits the window size. It is wired **non-destructively** at install time by `ensure_map_statusline`: the `statusLine` entry is merged into the user-owned `.claude/settings.local.json` ONLY when no status line already exists in the local/project/user scope — so MAP never overrides a status line the user configured. Writing to `settings.local.json` (not the MAP-managed `settings.json`) avoids all managed-file drift/`.bak` churn and stays idempotent across upgrades; remove the `statusLine` key there to disable. Claude provider only (`statusLine` is a Claude Code concept; the Codex install path never wires it). The other Phase 3 item — threshold warnings — already shipped via the `context-meter.py` `/compact` nudge; the heartbeat/SSE-keepalive item is closed as **harness-owned** (MAP's orchestrator is prompt-driven and dispatches subagents through Claude Code's Task tool, which the harness keeps alive — MAP ships no bespoke keepalive). Design was llm-council-reviewed (conv `585f773b`). Completes #284 Phase 3.
- **Parallel-wave merge coordinator for worktree isolation (`merge_wave_worktrees`, part of #284 Phase 2).** Wires the existing wave/DAG scheduler to per-subtask worktree isolation so a parallel wave's independent subtasks each run in their own worktree and are accepted **atomically**. Every worktree of a wave is cut off the same base (HEAD at wave start), so they cannot be merged one at a time — the first `merge_subtask_worktree` advances HEAD and the next trips `BASE_DIVERGED`. The new coordinator relaxes *only* that guard to a wave-scoped form: it refuses **external** HEAD movement (`EXTERNAL_HEAD_MOVED`) but allows the sibling divergence each in-wave squash-merge creates. It derives `wave_base_sha` from the sidecar (never a caller parameter), preflights every worktree (commit + per-worktree guards + pre-merge verify) BEFORE touching the working branch, then squash-merges each accepted worktree **by frozen SHA in sorted id order** (one runner commit per subtask — the one-commit-per-subtask contract holds), then runs **one post-wave full gate on the merged tree inside the same transaction**. It is **all-or-nothing** (council-reviewed, conv `c29d6fa9`): any textual conflict, commit failure, or post-wave-gate failure rolls the whole working branch back to the wave base via `git reset --hard` + `git clean -fd` (squash leaves no `MERGE_HEAD`, so `git merge --abort` is never used; MAP runtime state is excluded from the clean) and leaves **every** worktree intact for retry — no partial-wave state ever survives. Safety extras: an advisory `flock` serializes coordinators (`MERGE_IN_PROGRESS`); attached-/clean-target preconditions; conflicted paths are attributed back to the subtasks that touched them (declared-disjoint `affected_files` is only a scheduler hint, so actual changed-file overlap is reported as advisory telemetry while git's textual conflict stays the hard guard). The shared `_wt_freeze_and_verify` primitive (commit + guards + pre-merge verify) is extracted once and reused by both the single-subtask and wave merge paths. CLI: `merge_wave_worktrees <ST…> [--branch B] [--verify-cmd CMD…] [--skip-verify] [--post-wave-cmd CMD…] [--skip-post-wave]`. Phase 3 (context-budget hooks) remains open on #284.
- **Per-subtask git worktree isolation for `/map-efficient` (`worktree.isolation`, part of #284).** Opt-in, OFF by default. When enabled, each subtask's Actor runs in a dedicated, throwaway git worktree and its result is squash-merged back into the working branch ONLY after the configured `verification_checks` pass IN the worktree (a **pre-merge** gate, strictly stronger than today's post-commit check) — a rejected attempt (Monitor `valid=false` / Evaluator fail) is discarded so the working branch is never touched by a bad attempt. The Python step runner owns the whole lifecycle and every safety guard (producer-owns-parse): `create_subtask_worktree` (crash-safe remove-and-recreate; guards: not-a-repo, protected-ref, nested-worktree refusal, active-git-op, `subtask_id` ref/path sanitization, dirty-main refusal, submodule init), `merge_subtask_worktree` (guards run BEFORE the working branch is touched: base-divergence `git merge-base` check, runtime-state-in-diff, configurable bulk-deletion threshold `worktree.max_deletions`, submodule-pointer change, detached-HEAD, then the pre-merge verify gate; accept = `git merge --squash` + one runner-authored commit, never `--no-ff`, preserving one-commit-per-subtask), `discard_subtask_worktree` (atomic reject, idempotent, optional `--save-patch` forensics), and `worktree_isolation_status` (reconciles recorded vs live worktrees). Worktrees are stored OUT of the working tree under the repo's git common dir (`<git-common-dir>/map-framework/worktrees/`), so `git clean -fdx`, recursive scanners, and accidental commits can never touch them; MAP runtime state (`.map/<branch>/...`) always resolves against the main checkout — state-mutating commands refuse if invoked from inside a managed worktree (the silent state-desync footgun). Every guard returns a structured `{kind, message}` the skill branches on. Config keys `worktree.{isolation,max_deletions}`; new `worktree` manifest stage; `.map/<branch>/worktrees.json` sidecar. Design was llm-council-reviewed (runner-owned worktrees over harness-native `isolation="worktree"`; squash-merge over `--no-ff`; always-discard on reject; pre-merge verification + crash-safe retry + atomic reject folded in so the slice is not a no-op; explicit state-root separation). Phase 2 (wave/DAG parallelism) and Phase 3 (context-budget hooks) remain open on #284.
- **Cross-AI peer review for `/map-review` (`--cross-ai <runtime>`, part of #288).** `/map-review --cross-ai codex|gemini|claude|opencode` dispatches the review to an INDEPENDENT external AI CLI for a true second opinion (different model/vendor, fresh context with no shared session). The dispatch, parsing, normalization, and untrusted-wrapping all live in the Python step runner (`run_cross_ai_review` / `dispatch_cross_ai_review`, producer-owns-parse) — the skill only handles consent and presentation. Egress is **double-consent**: the per-run `--cross-ai` flag AND `review.cross_ai.enabled: true` in `.map/config.yaml` (off by default) are both required, because the diff/code leaves the machine. Mandatory guardrails: a **high-confidence outbound secret scan** (private keys, AWS/GitHub/Google/Slack credentials) BLOCKS dispatch before the subprocess and surfaces only the pattern name, never the value; the external CLI is invoked `shell=False` with a literal-argv adapter and a configurable timeout; the returned findings ALWAYS enter context behind an `EXTERNAL UNTRUSTED REFERENCE` fence (link/injection scan, applied deterministically in Python so the model cannot skip it) and are advisory-only (`source: cross_ai`, never auto-applied); same-vendor runtimes (`claude`) are honestly labeled `independent_vendor: false`. Any dispatch failure (disabled, CLI missing, not authenticated, timeout, non-JSON output, secret-blocked) degrades non-blockingly and falls back to the in-session review. Config keys `review.cross_ai.{enabled,runtime,timeout_seconds}`. Design was llm-council-reviewed (Python-owned dispatch; single-runtime slice with `--cross-ai all` consensus deferred to a follow-up slice).
- **Adversarial multi-perspective code review (`/map-review --adversarial`).** Runs three parallel independent reviewers with isolated contexts instead of a single monitor pass: Blind Hunter (diff-only, unbiased by stated intent), Edge Case Hunter (diff + repo read; null handling, boundaries, error paths), and Acceptance Auditor (diff + spec + artifacts; missed requirements, AC gaps). Adds a `--quick` flag (Blind + Acceptance, skips Edge Case) and a `--show-raw-findings` debug flag. Findings use a structured severity/category/evidence/failure_mode schema, deduplicated via deterministic clustering with corroboration signals, and rolled up into a unified report with a convergence section and all-clear statements. New `build_adversarial_review_prompts()` / `aggregate_adversarial_findings()` in the step runner, plus an `adversarial-reference.md` workflow doc. This is the Claude-side feature the Codex port (above) mirrors.
- **`mapify tokenreport` dashboard, history, estimate, and export modes (closes #289).** `token_report_dashboard()` adds a box-drawing visual layout (session summary, per-subtask bar chart, per-agent/model breakdowns, vs-previous-session comparison); `record_session_snapshot()` persists `token_history.jsonl` for `token_report_history()` trend analysis; `token_report_estimate()` gives a weighted cost projection; `token_report_json()` / `token_report_csv()` support CI/export. New CLI flags: `--dashboard`, `--history`, `--json`, `--csv`, `--estimate`, `--finalize`.
- **Learned rules scoped by `path_glob` (closes #280).** Rules with a `paths:` frontmatter key are now filtered before Actor context and personal-rules injection, and only load when the agent is working on matching files — aligning with Claude Code's hierarchical rule-loading pattern instead of injecting every learned rule into every subtask regardless of relevance.
- **Auto-created GitHub Release in the release CI workflow (closes #279).** `release.yml` now uses `softprops/action-gh-release@v2` to auto-create the GitHub Release (with a changelog excerpt) on tag publish, with the required `contents: write` / `id-token: write` permissions. The manual Phase 5.4 (`gh release create`) step is dropped from the `/map-release` skill; the summary/checklist now reference the auto-created release URL instead.

### Fixed
- **`detect_actor_files_changed_mismatch` no longer false-positives on MAP-only subtask artifacts (closes #277).** The actor files-changed gate validated every declared file against `_current_subtask_changed_files`, which derives from `git diff`/`git status` and strips the gitignored framework trees (`.map/`, `.codex/`, `.agents/`). A subtask whose only declared `affected_files` entry was a MAP artifact (e.g. `.map/<branch>/verification-summary.md`) therefore always reported `status_mismatch=true` with a false "Actor declared files it did not write" recovery instruction, making MAP-only documentation/verification subtasks look like truncated actor edits. The detector now partitions declared files: git-tracked files keep the diff check, while MAP-internal artifacts are validated by filesystem existence + non-empty content (a missing or empty artifact is still a real mismatch). MAP-artifact validation is independent of git availability, so a MAP-only subtask is never forced into a false mismatch by a git error. A new shared `_is_map_internal_artifact` helper de-duplicates the framework-tree prefix list used by both the strip filter and the new validation path.
- **Workflow-context injection no longer fires on a terminal `COMPLETE` state (closes #317).** When `step_state.json` has `current_step_id` or `current_step_phase` equal to `"COMPLETE"`, `format_reminder()` now returns `None` immediately via a terminal-state guard, so the hook emits `{}` instead of a misleading "REQUIRED: Complete phase COMPLETE" banner after a workflow has already finished. Added a `_TERMINAL_STEP_IDS` frozenset constant and regression tests covering both the subprocess-integration and unit (`format_reminder`) paths.
- **`record_test_baseline` timeout is now fail-safe, not fail-open (closes #307).** When the baseline subprocess timed out it never finished, so `baseline_failures` was always `[]` — indistinguishable from a genuinely clean suite, silently treating any pre-existing failure as "not pre-existing" and defeating the regression-vs-pre-existing distinction. Status is now `"timed_out"` (distinct from `"baseline_failures"`); a new `baseline_complete: bool` field is `false` on timeout so downstream code can check it before trusting an empty baseline; `list_baseline_failures` propagates `baseline_complete`/`timed_out` and emits a `warning` key when the stored baseline is incomplete. Default `timeout_seconds` raised from 120 to 600 to give most suites room to finish; `--timeout` still accepts an explicit value.
- **Bare-basename spec citations now auto-resolve instead of hard-failing (closes #301, closes #300).** `validate_spec_citations.py` resolves a bare filename citation (e.g. `api.ts:80`) automatically when it is unique in the repo; an ambiguous bare basename now produces a non-blocking warning instead of a hard error, and a genuinely missing file gets a clearer error message. Separately, `/map-plan` Step 0's research-agent now writes its full report directly to disk (with the pipe-based fallback kept), documenting the `SendMessage` vs. new-`Agent()` footgun for future skill authors.

## [3.20.0] - 2026-06-26

### Added
- **Automatic cleanup of MAP-internal workflow IDs from shipped code.** At workflow completion (`WORKFLOW_COMPLETE`), the new `scrub-internal-ids.py` Stop hook strips leaked internal identifiers — subtask `ST-001`, acceptance criteria `AC-3`, verification criteria `VC1`, invariants `INV-7`, hard constraints `HC-1` — that an Actor wrote into the code a run changed — as comments (`// The rule (INV-7) is:`) or test names (`test_vc1_*` → `test_*`). The deterministic engine (`.map/scripts/scrub_internal_ids.py`) is hard-scoped to the run's git diff (only files the run changed, only the lines it added; pre-existing IDs on untouched lines are never modified) and to recognized source files using each language's comment syntax (`#`, `//` + `/* */`, `<!-- -->`, …). It strips ID tokens **inside comments** (deleting pure-marker comment lines) and renames `vc<n>` test identifiers with a collision guard. IDs in code, string literals, docstrings, and data files (`.json`, …) are deliberately left intact and only *reported* — stripping a string substring would corrupt legitimate values (e.g. `"INV-7-special-sku"`) and `#` is a heading, not a comment, in markdown. It re-scans for residual. It then commits the cleanup as a dedicated `chore(map): strip internal workflow IDs` commit, runs exactly once per completed run, no-ops outside a completed run, honors `MAP_INVOKED_BY`, and can be disabled with `scrub_internal_ids: false` in `.map/config.yaml`. The Actor prompt now also forbids writing these IDs into comments/strings (the transient `test_vc<n>` grep aid stays during the run and is renamed at close). Claude provider only — the Codex hook model has no `Stop` event; the shared engine ships to `.map/scripts/` regardless.

## [3.19.0] - 2026-06-24

### Fixed
- **Blueprint affected-files refresh no longer shrinks approved subtask scope after resume (closes #273).** `refresh_blueprint_affected_files` now merges the computed actual delta into existing `affected_files` by default, preserving files that were already approved but excluded from the per-subtask baseline. The old destructive rewrite behavior remains available only via explicit `--replace`, and reports now expose both `actual` and `mode`.
- **Plan resume requires an overlap floor, not containment alone (closes #274).** `check_plan_resume()` no longer returns a false `resume` verdict (with the dangerous "existing step_state ⇒ plan complete, print checkpoint and STOP" recommendation) when the new goal merely overlaps a contained-but-near-zero existing plan. The verdict now requires a minimum goal overlap in addition to containment, so a genuinely different goal starts fresh instead of silently resuming a stale plan.
- **Codex `hooks.json` no longer carries an unsupported `_map_managed` top-level key (closes #270).** The codex hooks-JSON generator merged MAP metadata as a top-level `_map_managed` object, which the Codex runtime rejects. The generator now writes only the supported `hooks` structure and keeps MAP's managed-merge bookkeeping out of the emitted file.
- **`/map-efficient` resume prefers `blueprint.json` for ordered subtask IDs (closes #264).** `resume_from_plan`, `resume_single_subtask`, `resume_from_test_contract`, and `get_plan_progress` now read ordered `ST-XXX` IDs from `blueprint.json` first, falling back to markdown `task_plan` parsing (including the `/map-plan` table layout with IDs in the first column). `set_subtasks` normalizes whitespace-joined arguments and rejects malformed subtask IDs, so resume no longer fails to parse a well-formed plan and force a manual `set_subtasks`.

### Added
- **Opt-in `--autonomy` posture for `mapify init` (claude provider).** `mapify init --autonomy` writes a "YOLO-minus-git" permission set — broad auto-approve (`Bash(*)`, `Read/Edit/Write/MultiEdit/Glob/Grep/LS(*)`) plus a `Bash(git commit:*)` / `Bash(git push:*)` deny — into the **per-user, gitignored** `.claude/settings.local.json`, leaving the committed team `.claude/settings.json` as the secure curated baseline. Because the permission-level git deny is bypassable under a broad `Bash(*)` allow (`bash -c 'git commit'` matches as `bash`, not `git commit`), enforcement is the `safety-guardrails.py` PreToolUse hook: it now hard-blocks `git commit`/`git push` (including shell-wrapped and chained forms) **gated on a `mapify.autonomy` sentinel** the installer writes beside the permissions, so posture and permissions can't drift apart and the standard commit workflow is never broken for non-autonomy users. `--no-autonomy` cleanly removes the block; omitting the flag leaves any existing local posture untouched on re-init. `mapify init --autonomy` also gitignores `.claude/settings.local.json` so the personal posture can't leak to the team. The codex provider ignores the flag (it installs neither file). Design was llm-council-reviewed (per-user opt-in over team/global default; hook enforcement over permission-deny-alone; sentinel embedded in `settings.local.json`).
- **Merge-conflict resolution guardrail (closes #256).** The workflow-context injector now surfaces MAP conflict-resolution guidance during a git merge/rebase preflight and whenever the index holds active unmerged paths. It detects conflicted paths read-only via `git diff --name-only --diff-filter=U -z --` (the existing `step_state.json` gate is preserved) and documents the per-file, intent-preserving, test-after-each-batch protocol so conflicts are resolved one file at a time rather than with bulk overwrites.
- **`defer_flaky_subtask` orchestrator command for validated flaky Monitor outcomes (closes #252).** When a Monitor verdict is an explicit `deferred_nondeterministic` outcome, the orchestrator can now persist the non-green flaky evidence metadata in `step_state.json` and advance without requeueing Actor, preserving run-health completion parity instead of grinding the retry loop on a known-flaky check.
- **`run_flaky_test_triage` repeat runner for `/map-efficient` (part of #252).** New step-runner subcommand repeats an exact `argv` command with `shell=False` and records flaky-test evidence automatically into `flaky_test_triage.json`, preserving bounded stdout/stderr tails, timeout, and duration evidence. No shell interpretation by default (shell behavior requires explicit argv such as `bash -lc`); output tails are tempfile-backed to avoid unbounded in-memory capture. Design was llm-council-reviewed (argv-based runner; core Monitor/orchestrator state-machine integration deferred).
- **Qualitative convergence sidecar for high-risk Monitor/self-review gates (issue #257).** New step-runner subcommands `record_qualitative_convergence <gate-id> <pass-json> [--scope monitor|self_review] [--required-clean-passes N] [--max-passes N]` and `validate_qualitative_convergence [path]` persist append-only qualitative review passes in `.map/<branch>/qualitative_convergence.json` and register the `qualitative_convergence` manifest stage. Validation re-derives the tail clean streak from the pass log (`clean, dirty, clean` with K=2 is not converged), rejects `clean=true` with critical findings, requires evidence even for clean passes, and treats `max_passes_exceeded` as a hard stop/escalation rather than a pass. Scope is deliberately limited to qualitative `monitor` / `self_review`; deterministic build/test/lint gates remain single-pass. Part of #251.
- **Flaky-test triage artifact for `/map-efficient` (issue #252).** New step-runner subcommands `record_flaky_test_triage <check-id> <outcomes-json> [--command ...] [--reason ...] [--branch ...]` and `validate_flaky_test_triage [path]` persist repeated check outcomes in `.map/<branch>/flaky_test_triage.json` and register the `flaky_test_triage` manifest stage. Mixed pass/fail repetitions classify as `disposition:"deferred_nondeterministic"` with `monitor_verdict_policy:"not_valid_without_explicit_triage"` and operator requirements that forbid weakening, skipping, deleting, or treating the artifact as a passing gate. All-failing repetitions classify as `deterministic_failure`; all-passing repetitions classify as `not_reproduced`. Package schemas and run-health artifact inventory now understand the new artifact, while keeping the core Monitor/orchestrator binary verdict path unchanged. Part of #251.
- **Intra-run failure memory for the Actor→Monitor retry loop (issue #253).** When Monitor rejects the *same* subtask the *same way* twice, `/map-efficient` now injects a binding anti-stagnation constraint into the next Actor attempt so the loop stops re-walking a dead end (token burn / identical rejected diffs). Four deterministic step-runner subcommands implement it: `record_failure_signature "<feedback>" <subtask_id> [--source monitor_rejection|test_failure|gate_failure]` conservatively normalizes the failure (strips line numbers, absolute-path prefixes, hex/uuid/addresses, timestamps, ANSI; preserves exception types, file basenames, symbol/test names, assertion text), hashes it, and arms on the 2nd identical signature; `build_anti_repeat_constraint <subtask_id> [--quarantine-active]` renders the `<intra_run_failure_memory>`-delimited block (shows the human-readable sample, never the hash) and returns empty when nothing is armed or a CLEAN_RETRY quarantine is active that iteration; `set_anti_repeat_subtask_status <subtask_id> succeeded|failed|escalated` records the terminal disposition; `collect_anti_repeat_learn_candidates` feeds `write_learning_handoff` so armed signs from **non-succeeded** subtasks become `/map-learn` candidates (a subtask that eventually passed is excluded — it found a way through). The constraint is *anti-stagnation*, not *anti-approach*: it binds the next delta to resolve the repeated failure, never bans a whole approach. Generic rejections with no concrete anchor ("tests still fail") are recorded `low_specificity` and **never arm**. At the 3rd identical failure the record sets `escalation_recommended=true` as a SIGNAL only — bounded-effort escalation (#255) owns the stop decision; this slice never skips the Actor call. Durable store: `.map/<branch>/anti_repeat.json` + `anti_repeat` manifest stage; thresholds are env-tunable (`MAP_ANTI_REPEAT_ARM_THRESHOLD`, `MAP_ANTI_REPEAT_ESCALATE_THRESHOLD`). Complements — never duplicates — `log_agent_failure` (FORMAT failures only) and `retry_quarantine` (one-shot CLEAN_RETRY). Design was llm-council-reviewed (hard anti-stagnation + generic-failure guard + per-subtask scoping + CLEAN_RETRY suppression). Part of #251.
- **Bounded-effort escalation: "act once, then escalate" (issue #255).** Turns the #253 `escalation_recommended` SIGNAL (previously written but never consumed) and the orchestrator's `max_retries` hard cap into ONE deterministic terminal outcome instead of grinding the Actor→Monitor loop to the ceiling on a dead end. New step-runner subcommand `build_escalation_outcome <subtask_id> <reason> [--retry-count N --max-retries M] [--quarantine-active]` (reason ∈ `repeated_failure | max_retries`) emits a structured `{status:"escalated", outcome, reason_code, attempts, blocker_summary, repeated_failures, recommended_action}`, sets the subtask's anti-repeat status to `escalated`, writes a durable human-readable `.map/<branch>/escalation_<subtask>.md` blocker report, and registers a new `escalation` manifest stage. The outcome splits on cause: a **3rd identical** failure short-circuits to `outcome:"BLOCKED"` (the constraint armed at the 2nd identical failure was the single bounded recovery act, so the legacy retry-3 Stuck-Recovery is bypassed for identical-failure loops, kept for non-identical stuckness), while budget exhaustion across **differing** failures is `outcome:"CLARIFICATION_NEEDED"`. The stop is re-derived from the anti_repeat store INSIDE the subcommand — a spurious/hallucinated call returns `status:"not_escalated"` (the loop resumes), never a fabricated stop; it binds to the *latest* signature (a fresh failure on the last attempt → resume), a CLEAN_RETRY iteration (`--quarantine-active`) defers the stop so the one-shot reset runs first, and the call is idempotent. The orchestrator's tested retry math is untouched; the runner owns the store (producer-owns-parse). Directly serves "surface blockers, don't fake progress". Design was llm-council-reviewed (hard short-circuit at the 3rd identical signature; BLOCKED vs CLARIFICATION_NEEDED split; deterministic runner-side guard over SKILL prose). Part of #251.
- **Repro-probe root-cause gate for `/map-debug` (issue #254).** `/map-debug` now *enforces* the "no fix without root cause" Iron Law instead of only preaching it. Before any fix, the agent writes a small self-contained executable probe under the gitignored `.map/<branch>/repro/` that exits `42` while the bug reproduces and `0` once it is gone. Two new deterministic step-runner subcommands gate the fix: `record_repro_probe <probe> [--root-cause … --timeout N --runs N]` copies the probe into an immutable runner-owned locked snapshot, executes it (`shell=False`, hard timeout + process-group kill, `stdin=/dev/null`, bounded output capture, path-containment) and arms the gate only when the runner *witnesses* exit 42 — a self-reported claim never satisfies it; `verify_repro_resolved` re-runs the **same frozen snapshot** (re-checking its sha256) after the fix and passes only on the 42→0 flip. A missing reproduced probe, a still-reproducing probe, an inconclusive run, or a tampered snapshot is a hard stop (CLI exits non-zero). The durable verdict lives in `.map/<branch>/repro_probe.json` and a new `repro_probe` manifest stage; throwaway probes are kept out of VCS via a self-contained `.map/<branch>/repro/.gitignore` (the user's own `.gitignore` is never touched). The runner proves a *witnessed behavioral flip*, not that the probe captures the real root cause — Monitor still owns that semantic judgment. Design was llm-council-reviewed (Option A: sentinel exit contract + frozen snapshot). Part of #251.
- **Deterministic decomposition-completeness gate (issue #249).** `validate_blueprint_contract` now runs a forward-coverage set-diff between the spec's **Requirements Index** (`mapify:requirements-index:v1` fenced YAML, one `{id, kind}` entry per acceptance criterion / invariant / hard constraint / cross-cutting concern) and `coverage_map` keys. The index is the authoritative requirement list and lives in the spec, not the blueprint, so the decomposer cannot self-certify the set it is measured against. Uncovered requirements produce a **warning** by default; set `MAP_STRICT_COVERAGE=1` for a hard error (off by default — staged migration). An absent index (e.g. the `/map-efficient` no-spec path) emits a loud warning and skips the check — never a silent pass. A malformed index is always a hard error. Confidence is qualitative (`high | medium | low`) with a one-line basis; no numeric scores. Non-blocking guardrails: prose-orphan detection (canonical IDs in spec prose outside the index), reverse-phantom detection (`coverage_map` keys absent from the index), and an ownership-distribution report with a configurable fan-in warning (`_COVERAGE_FANIN_WARN`, default 3). Structural checks: entry-point existence (non-empty plan must have at least one zero-dependency subtask) and warn-first max dependency depth (`MAX_DEPENDENCY_DEPTH` default 5, env override `MAP_MAX_DEPENDENCY_DEPTH`). Spike finding (ST-007): multi-node cycle DFS was evaluated and deliberately omitted — forward-dependency-ordering and `_topo_sort_subtasks` already reject all cycles; a regression test (`test_multinode_cycle_already_rejected`) guards both mechanisms.

## [3.18.0] - 2026-06-21

### Fixed
- **PyYAML promoted to a hard runtime dependency (closes #245).** `pyyaml` was
  declared only in the `test`/`dev` optional groups, so a normal install
  (`uv tool install` / `pipx` / `pip install mapify-cli` without extras) shipped
  without PyYAML. `project_config.load_map_config` then hit `ImportError`, warned
  once, and **silently fell back to default config** — the user's entire
  `.map/config.yaml` (`minimality`, `profile`, `compression_policy`, thresholds,
  `language`, `prompt_layering`, …) was ignored by every config-dependent CLI path
  (`minimality-report`, `mapify init` compression/sofa overrides). CI never caught
  it because the dev/test groups *do* include `pyyaml`. Fix adds `pyyaml>=6.0.0` to
  `[project].dependencies` in `pyproject.toml`. (The `.map/scripts/map_step_runner.py`
  runner was unaffected — it reads config via a stdlib-only scalar parser — which is
  why the defect hid.) Regression tests assert `pyyaml` is in the runtime dependency
  table and that a non-default `.map/config.yaml` value actually loads.

### Changed
- **Prompt layering resolved as cache-neutral; `docs_first` stays the default (closes #231).**
  The remaining field-gated step of #231 — measure `docs_first` vs `stable_first`
  on a real multi-subtask run, then maybe flip the global default — is resolved
  **on mechanism, not a fabricated measurement.** Anthropic prompt caching writes
  a cache entry only at an explicit `cache_control` breakpoint on a content-block
  boundary and hits require a byte-identical prefix up to that block; Claude Code's
  Task tool owns the API call and **all** breakpoint placement, and MAP joins its
  sections into one user-message string so the stable/variable seam lives *mid-block*
  and can never become a cache boundary. The only byte-identical cross-dispatch
  prefix (`tools` + role system prompt) is independent of `prompt_layering`, so both
  modes benefit equally. Therefore `stable_first` yields **no incremental prefix-cache
  hit** under the current Claude Code Task architecture. **No behavior change:** the
  global default stays `docs_first`; `stable_first` remains opt-in and is **not** a
  behavior no-op (it still changes token order/attention) and is never silently
  remapped. `docs/ARCHITECTURE.md`, `docs/USAGE.md`, the `MapConfig.prompt_layering`
  comment, the generated `.map/config.yaml` comment, the `map_step_runner.py` layering
  comments, and `tests/test_prompt_layering.py` were de-overclaimed accordingly, and
  re-open triggers were recorded. No `token_accounting.json` figures were fabricated —
  per-subagent cache `usage` is harness-owned and not observable to MAP for Task
  dispatches, which is exactly why an end-to-end run is a poor test of this hypothesis.
- **Global `minimality` default flipped `off` → `lite` (Phase 3, closes #183).**
  The promotion gate (`mapify minimality-report`) reached `candidate` and the
  manual review gate passed against field telemetry, so the keyless default now
  resolves to `lite` instead of `off` at BOTH layers: `MapConfig.minimality`
  (`src/mapify_cli/config/project_config.py`) and the runner's
  `_load_minimality_level` (`map_step_runner.py`). Projects that omit the key now
  get the advisory complexity-lens / minimality doctrine (advisory-only — never a
  verdict gate). Opt out with `minimality: off`. **Opt-out hardening:** YAML 1.1
  parses bare `off` as boolean `False`, which the str field previously rejected and
  silently dropped to the default — now the loader coerces a boolean `minimality`
  back to the `off` level before type-checking, so `minimality: off` (quoted or
  bare) reliably opts out. `generate_default_config` already wrote `minimality:
  lite` for new projects, so generated configs are unchanged; only keyless/invalid
  fallbacks move from `off` to `lite`. Regression tests pin the new default, the
  bare-`off` opt-out, the invalid→`lite` fallback, run-health stamping, and the
  doctrine/lens activation at the lite default.

### Added
- **`/map-plan` Step 0.6: Verify Live/Runtime State gate (#243).** A new
  `depends_on_runtime_state` workflow-fit signal (6th signal on
  `record_workflow_fit`, default `false`; CLI flag `--depends-on-runtime-state`,
  legacy positional path unchanged) arms a gated **Step 0.6** between the
  Already-Implemented gate (Step 0.5) and decomposition. It is the runtime
  analogue of Step 0.5: where 0.5 stops you re-planning code that already
  exists, 0.6 stops you planning against runtime facts that have drifted
  (prod row counts, enum labels actually present in a live DB, a column that
  already exists, the applied migration head, a live feature-flag value).
  Each assumption is either verified read-only through an approved source
  (replica/dashboard/metadata query — cite the derived fact, never persist
  prod rows/PII/secrets into `.map/<branch>/` artifacts) or recorded as an
  `Unverified Runtime Assumption` in the spec's Open Questions / Risks with the
  exact check to run, with dependent subtasks marked `provisional`. The skill is
  a planning-time gate, not a runtime tool — it suggests the read-only checks and
  defers execution to the operator or an authorized sub-agent; it never
  hard-stops merely because prod is unreachable. Mirrored into the Codex
  `$map-plan` surface; detail + examples + safety guardrails live in the bundled
  `plan-reference.md` (the active SKILL body stays under its line budget).
  `WORKFLOW_FIT_DECISION_SCHEMA` gains the optional `depends_on_runtime_state`
  boolean (not `required`, so pre-existing `workflow-fit.json` files still
  validate). Design pressure-tested via llm-council (deep mode). New regression
  tests pin the signal round-trip, the keyword CLI flag, the legacy-positional
  default, schema backward-compat, and the gate prose across all rendered
  Claude + Codex trees.
- **Opt-in cache-friendly prompt layering for reviewer fan-out (Part of #231).**
  `.map/config.yaml` now accepts `prompt_layering: docs_first | stable_first`
  (default `docs_first`, behavior unchanged). `docs_first` keeps the historical
  attention-optimized envelope (variable `<documents>` first, stable contract
  last). `stable_first` reorders the stable `<task>`/`<workflow_policy>`/
  `<instructions>`/`<expected_output>` contract ahead of the variable documents
  so it forms a **byte-identical prefix** across repeated same-role Monitor/
  Predictor/Evaluator (and complexity-lens) dispatches — the precondition for an
  automatic prefix-cache hit. `_render_review_prompt` and
  `_render_complexity_lens_prompt` route through a shared `_layer_prompt_sections`
  helper; `build_review_prompts` reads `_load_prompt_layering()` and echoes the
  active mode as `prompt_layering` in its result. Registered + validated on
  `MapConfig` and documented (commented) in the generated config. The
  attention-vs-cache tradeoff is unproven, so the **default does not flip**: it
  is gated on a measured `docs_first` vs `stable_first` comparison (incremental
  `cache_read` + no quality regression) — the measurement recipe and the
  harness-owned-dispatch constraint are documented under "Prompt Layering &
  Prefix Caching" in `docs/ARCHITECTURE.md`. The token-accounting `cache_read`
  double-count the issue cited as a measurement caveat was already fixed and is
  regression-tested, so the comparison numbers are trustworthy. New
  `tests/test_prompt_layering.py` pins docs_first byte-identity and the
  stable_first prefix invariant.
- **Agent-Boundary Doctrine: written down + every live hand-off audited
  `independent | relay` (#230).** `docs/ARCHITECTURE.md` now carries the explicit
  criterion — keep a separate sub-agent **only** when it adds an independent /
  adversarial perspective; collapse any **pure-relay** hop (a context that only
  paraphrases a prior agent's output, emitting no new verdict) into its caller.
  It is a *substance* rule, not a *wiring* rule. The doctrine includes a ground-truth
  audit (classified from actual `subagent_type="…"` dispatch sites, not docs): all
  8 pipeline-dispatched agents emit independent verdicts and none is a relay; the
  only relay hops the doctrine condemns — the Self-MoA `synthesizer`/`debate-arbiter`
  — were already collapsed in #240. The audit also resolves the orphaned
  `documentation-reviewer` (zero skill dispatch sites) as a **deliberate keep**: it
  emits a unique, non-relay verdict, so it is retained as an **optional,
  user-dispatchable** agent (invoke via `Task(subagent_type="documentation-reviewer")`)
  and now self-declares a `Dispatch status:` annotation. A new
  `tests/test_agent_dispatch_audit.py` enforces the invariant going forward: any
  agent shipped with no dispatch site and not marked optional fails the gate,
  preventing a silent orphan from recurring.
- **Hand-authored RESEARCH artifacts now self-correct on the first reject, and
  the exact contract is documented (#228, follow-up to #197).** The documented
  `save_research` path ("save direct current-session findings") used to cost 2-3
  `validate_research` rejects because the strict schema enforced by the validator
  (status enum, `confidence` float, `search_stats` field names, `lines: [start,
  end]` with a ≤200-line span) lived only in code — the SKILL prose implied free
  text (`"complete"`, `"high"`, `files_examined`). Now: (1) `validate_research`
  echoes a copy-pasteable, structurally-valid artifact in a `skeleton` field on
  ANY failure (bad JSON, wrong types, or a missing artifact), so the first reject
  is self-correcting — copy it, swap your values, re-save; (2) the exact field
  table + the same skeleton are documented under "RESEARCH artifact schema" in
  the map-efficient `efficient-reference.md` (Claude and Codex), with the SKILL
  RESEARCH section naming the exact status enum and pointing at it. Validator
  behavior is unchanged for valid artifacts (no `skeleton` field is added).
- **Compaction now offloads large tool outputs for on-demand retrieval instead
  of dropping them (#232).** Before context compaction prunes old/large
  tool-result bodies (grep output, test logs, whole-file reads), MAP now saves
  each one at full resolution to a retrievable sidecar under
  `.map/<branch>/compacted/` (an append-only `index.ndjson`, an agent-readable
  `MANIFEST.md`, and per-output `*.txt` files with a self-describing header).
  After compaction the post-compact hook points the agent at the manifest so a
  dropped output is re-read from its sidecar **instead of re-running broad
  discovery** — the exact re-discovery cost #203 fights. Provider-agnostic: the
  Claude PreCompact hook and the Codex orchestrator budget warning both capture
  at the same pre-drop point, sharing one `mapify_cli.tool_output_offload`
  module. Gated by `compression_policy` — with the default `never` no offload
  happens and `.map/<branch>/compacted/` is never created. Selection is
  size-based (≥10K chars any tool, or ≥2K for `Bash`/`Read`/`Grep`/`Glob`;
  `TodoWrite`/`AskUserQuestion`/`ExitPlanMode` never offloaded); the directory
  is FIFO-capped (300 files / 100 MiB, evictions logged). **Security:** tool
  outputs may contain secrets, so every sidecar is written `0o600` and a
  self-contained `.gitignore` (`*`) is dropped into `compacted/` on creation so
  it is never committed regardless of the host repo's ignore rules; bodies are
  never redacted. Persistent Actor/Monitor prompt guidance landed as the
  eval-gated follow-up #236 (below); the ephemeral post-compact pointer still
  re-primes the next turn.
- **Actor and Monitor persistently recover offloaded tool outputs across turns
  (#236, follow-up to #232).** The #232 post-compact pointer only re-primed the
  next turn; the map-efficient Actor and Monitor dispatched `<task>` prompts now
  carry persistent guidance so recover-before-rediscover survives compaction
  across turns. **Actor:** before re-running broad discovery (re-grep, re-read a
  large file, re-run the full test suite), check
  `.map/<branch>/compacted/MANIFEST.md` and `Read` the cited sidecar to recover
  the earlier output, re-running the tool **only** on a concrete staleness
  signal (recent edits, a new test run, an updated schema, or the task asking
  for current state) — the default is sidecar reuse, not over-eager
  re-discovery. **Monitor:** a sidecar is evidence of *what was checked*, never
  sole proof of correctness — every verdict stays grounded in live source and a
  current test run. Wording was validated with llm-council against the
  documented eval risk (over-trust of stale snapshots vs. skipping needed fresh
  discovery); the map-efficient `SKILL.md` line budget was bumped 502 → 504 for
  the two prompt lines, which must live in the dispatched body.

### Removed
- **Self-MoA and Debate-Arbiter removed entirely from MAP (#230).** Both the
  Self-MoA multi-variant pattern (`3×Actor → 3×Monitor → Synthesizer → final
  Monitor`) and the Debate-Arbiter cross-evaluation pattern were documented
  across `ARCHITECTURE.md`, `USAGE.md`, `INSTALL.md` and the plugin manifests but
  **never wired into any skill** — no `/map-*` surface dispatched the
  `synthesizer` or `debate-arbiter` agents, no `--self-moa` flag was ever parsed,
  and there was no `/map-debate` skill. The orphaned `synthesizer.md` and
  `debate-arbiter.md` agent templates, the Actor "Self-MoA Support" and Monitor
  "Self-MoA Output Extension" prompt sections, the `agent_mcp_mappings` entries,
  and all Self-MoA/Debate documentation are deleted. The shipped agent roster is
  now **9** (was advertised as 11): TaskDecomposer, Actor, Monitor, Predictor,
  Evaluator, Reflector, DocumentationReviewer, Research-Agent, Final-Verifier.
  No runtime behavior changes — nothing dispatched these agents.

### Fixed
- **`record_test_baseline` silently skipped the MANDATORY pre-flight baseline in
  monorepos (#229).** Auto-detect probed only the repo root, so when the module
  lives in a subdir (e.g. `component-manager/go.mod` with no root harness) it
  returned `status="skipped"` and the whole run proceeded with an empty baseline
  — the cross-subtask regression gate could then no longer tell an introduced
  regression from a pre-existing failure. Detection now probes the repo root
  first, then shallow-scans the immediate subdirectories (one level) for a
  single module that has a harness and runs the command from that dir (recording
  `module_dir`/`run_dir`). When more than one subdir qualifies it refuses to
  guess and skips loudly with `candidate_module_dirs`; the no-harness skip now
  names the `--command`/`--module-dir` escape hatch. A new `--module-dir`/`--cwd`
  flag forces the module dir for ambiguous or deeply-nested layouts. Documented
  in `efficient-reference.md`.
- **`/map-efficient` Actor truncation gate false-positived on every clean run
  (#227).** The pre-Monitor `detect_truncated_agent_output --agent actor` gate
  requires the Actor response to parse as a JSON object
  (`files_changed`/`tests_run`/`validation_notes`/`blocker`), but the ACTOR
  `<expected_output>` prompted for free-form prose — so every complete, correct
  Actor response was flagged `truncated: true`, forcing a needless re-invoke
  (token waste) or a manual operator override on each subtask. The ACTOR prompt
  now instructs a strict JSON manifest mirroring the MONITOR contract: code is
  written via tools first, then summarized into the four-field envelope (no code
  or diffs inside the JSON). Detector and retry machinery are unchanged. The
  rationale is documented in `efficient-reference.md`.

## [3.17.1] - 2026-06-18

### Fixed
- **Broken and misleading prose in lower-tier MAP skill prompts (prompt-quality
  audit).** Repaired shipped `SKILL.md` defects surfaced by a PQS audit: the
  `/map-tdd` ACTOR example carried an unterminated `f"""` string (would break on
  copy-paste) plus a duplicated `<TDD_Tests>` placeholder; `/map-state` declared
  three conflicting versions (frontmatter `1.0.0`, `metadata` `3.1.0`, footer
  `1.0.0`) — now all `3.1.0`; the auto-generated Troubleshooting footer in
  `/map-fast`, `/map-debug`, `/map-tdd`, and `/map-release` referenced a
  non-existent "What this command CANNOT do" section and shipped a
  `<typical args>` placeholder Examples block; the `/map-release` validation-gate
  matrix listed a "Black format" gate that `make check` never runs (black is
  `make format` only); and `/map-skill-eval` Troubleshooting required a
  non-existent `id` field on eval-set entries (`cell_id`s are derived).

### Changed
- **Strengthened inhibition (NEVER rules) and output contracts in read/write MAP
  skills.** `/map-state`, `/map-tokenreport`, `/map-memory-now`, and
  `/map-skill-eval` gained explicit `Constraints (NEVER)` blocks (single-writer
  enforcement, no direct `step_state.json`/run-log edits, read-only guarantees,
  no auto-persisting secrets or flipping user config) plus fixed output-report
  templates and a skill-eval self-check — raising prompt quality without changing
  runtime behavior. The `/map-debug`, `/map-fast`, `/map-tdd`, and `/map-release`
  Examples/Troubleshooting sections now reference real sections and real example
  invocations.

## [3.17.0] - 2026-06-18

### Added
- **`/map-understand` interactive learning mode (#221).** MAP now ships an
  opt-in deep-understanding slash surface for Claude and Codex. It keeps a
  transient Markdown checklist in the conversation, teaches code/diffs/workflow
  artifacts incrementally, asks restatement or quiz checks without revealing
  multiple-choice answers early, and stays separate from normal workflow
  verbosity and `/map-learn` persistence.
- **Minimality rollout telemetry can now be inspected before the Phase 3 default
  flip (#180/#183).** `run_health_report.json` records the workflow's historical
  `minimality` level, and `mapify minimality-report` compares complete `off` and
  opt-in cohorts for retry pressure, guard rework, and deferred-YAGNI reversal
  rate before marking the local rollout as `candidate`, `hold`, or
  `insufficient_data`. The report summary now includes `sample_gaps`,
  `cohort_branches`, `next_actions`, and a candidate-only `manual_review_gate`
  with opt-in branches plus a clarity/underscope checklist, so maintainers can
  see the exact telemetry, stale historical-minimality branches, and human review
  still needed before promotion.
- **Decomposer pruning is now contract-gated and user-visible (#184).**
  Blueprints can carry `requiredness`/`pruneable` metadata per active subtask
  and a `deferred_yagni` parking lot for speculative omissions. The validator
  rejects non-empty `deferred_yagni` under `minimality: off`/`lite`, requires
  explicit REVIEW_PLAN approval warnings under `full`/`ultra`, and Actor context
  now preserves approved omissions so they are not silently implemented or lost.
- **Deferred YAGNI items can be restored before approval (#184).**
  `map_orchestrator.py restore_deferred_yagni YG-NNN` moves one parking-lot
  item into active subtasks, appends it to the task plan, and clears prior plan
  approval so REVIEW_PLAN cannot proceed on stale scope.
- **Research-agent localization quality can now be scored deterministically
  (#200).** Maintainers can parse ResearchEvidence JSON or `path:line[-end]`
  text citations, validate them against a fixture repo, and compute file-level
  plus line-overlap precision/recall/F1 without live provider credentials.
  The scorer is exposed as `mapify research-eval score` and covered by the
  no-provider E2E artifact-contract suite.

### Changed
- **`/map-explain` now respects the user's language and scales depth to target
  size (#224).** The skill writes prose in the user's established language
  (code, identifiers, commands, and `file:line` refs stay English) instead of
  always defaulting to English. The rigid always-emit-all-10-sections /
  explain-every-line structure is replaced by a signal-first output spec:
  size tiers with word-budget ceilings and load-bearing-line caps, a front-loaded
  "Mental model in 60 seconds" block, read-tier section tags
  (`[MUST READ]`/`[READ IF MODIFYING]`/`[SKIM]`), a single load-bearing-lines
  table (merging the old "what every line does" + "why each line" sections,
  repeated shapes explained once), before→after-first ordering for diffs,
  adaptive sections with an `Omitted:` footer, and natural-language follow-up
  offers. Applies to both the Claude and Codex surfaces.
- **Research artifacts are now unified and consumed before broad search
  (#209/#210).** Planning and per-subtask research now share a single artifact
  shape across `/map-plan`, `/map-efficient`, and the research-agent, and Actor
  is required to consume the persisted research artifact before launching its
  own broad codebase search — enforced by `map_step_runner.py` so research spend
  is not duplicated or ignored.

## [3.16.0] - 2026-06-15

### Added
- **Research ROI is now visible in token and run-health diagnostics (#202).**
  `token_accounting.json` records advisory `research_roi`, `/map-tokenreport`
  prints per-agent cost plus research-vs-Actor/Monitor token share, and
  `run_health_report.json` summarizes persisted research artifacts, parsed
  status/confidence/location counts, low-confidence warnings, and token share.

## [3.15.2] - 2026-06-15

### Changed
- **Codex `researcher` now shares the Claude `research-agent` ResearchEvidence
  contract (#198).** Codex may use provider-specific search commands internally,
  but `/map-efficient` research artifacts now explicitly preserve the same strict
  JSON fields, bounded file-line evidence, and downstream Actor/Monitor
  semantics across providers.

## [3.15.1] - 2026-06-15

### Fixed
- **`/map-efficient` now distinguishes mandatory RESEARCH artifacts from
  conditional research-agent delegation (#201).** Hook hints, Claude/Codex
  workflow skills, orchestrator validation errors, and docs now tell operators
  to persist a research artifact before Actor while using `research-agent` /
  `researcher` only for broad, high-risk, or unclear discovery.

## [3.15.0] - 2026-06-15

### Added
- **MAP RESEARCH artifacts are now validated before Actor work (#197).**
  `validate_research` checks strict JSON, confidence/status/search stats,
  bounded file-line evidence, safe relative paths, and over-broad location lists;
  `validate_step 2.2` now blocks malformed or missing research before Actor can
  consume it.

## [3.14.0] - 2026-06-15

### Added
- **`/map-review` now runs an advisory what-to-delete lens when minimality is
  enabled (#182).** Projects with `minimality: lite`, `full`, or `ultra` get an
  extra complexity-only pass that reports `delete:`, `stdlib:`, `native:`,
  `yagni:`, and `shrink:` opportunities plus a post-hoc `net: -N` estimate;
  the output is never used as a verdict gate or Actor retry input.

### Fixed
- **`safety-guardrails.py` avoids regex/pathlib import overhead on common safe
  file checks.** The hook now keeps `Read app.py`-style allow paths on a lighter
  path while preserving regex checks for suspicious paths and custom config,
  reducing macOS CI flake risk in the hook performance gate.

## [3.13.1] - 2026-06-14

### Fixed
- **Release workflows now run `twine check` with modern packaging metadata
  support.** CI, TestPyPI, and PyPI release jobs upgrade `packaging` alongside
  `twine` using a `<26` upper bound for compatibility with environments that
  still constrain `packaging`, avoiding `InvalidDistribution: ... license-file`
  failures before publication (#195).

## [3.13.0] - 2026-06-14

### Added
- **Minimality doctrine Phase 1 (#181)**: `.map/config.yaml` now supports a
  `minimality` setting (`off`, `lite`, `full`, `ultra`). Existing projects with
  no key preserve historical behavior (`off`), while freshly generated configs
  opt into conservative `lite`. In `lite`, Actor receives smallest-sufficient
  guidance, Monitor flags requirement-affecting over-engineering and risk drift,
  Evaluator scores `simplicity` while keeping `completeness` highest-weight, and
  Actor retries receive only BLOCKER-class Monitor feedback so non-blocking
  style/docs/volume comments do not re-bloat the implementation.
- **Repository licensing is explicit.** The source tree now includes the MIT
  `LICENSE` file referenced by package metadata and project documentation.

### Removed
- **`deepwiki` MCP server is no longer installed, and `deepwiki`/`context7`
  guidance is removed from all agent prompts.** `mapify init` no longer
  configures the `deepwiki` MCP server in the project `.mcp.json`, the internal
  `.claude/mcp_config.json`, the plugin manifests, or `.mcp.json.example`;
  `--mcp all` and `--mcp essential` now install only `sequential-thinking`, and
  `--mcp deepwiki` is treated as an unknown server. Every shipped agent prompt
  (actor, monitor, predictor, evaluator, reflector, task-decomposer,
  documentation-reviewer), the fallback agent generators, the MCP usage-examples
  reference, the `map-debug` skill, and the user docs (INSTALL, USAGE,
  ARCHITECTURE, CLI reference) had their `deepwiki` and `context7` references
  removed; `sequential-thinking` is retained as the only MCP integration.

### Changed
- **Onboarding leads with the golden-path flow.** The ASCII banner now carries a
  `/map-plan → /map-efficient → /map-check → /map-review → /map-learn` subtitle,
  and the post-`init` "Next Steps" panel presents that loop in order (leading
  with `/map-plan`) instead of leading with `/map-efficient`.
- **README quick-start docs now show the `/map-plan` → `/map-efficient` flow
  directly.** The README includes the terminal demo GIF and keeps the generated
  `review-bundle.json` explanation in sync with the review workflow.
- **Generated MAP scripts now read scalar `.map/config.yaml` settings without
  importing `mapify_cli`.** Actor minimality context and subtask-boundary
  compression advice now work in generated projects even when the `python3` used
  to run `.map/scripts/*` cannot import the globally installed `mapify_cli`
  package.

### Fixed
- **Release validation now uses the maintained project gate.** The shipped
  `map-release` skill, release guide, and release checklist use `make check`
  plus explicit `uv run --with build` / `uv run --with twine` package checks
  instead of the stale Black-specific gate that failed on generated files (#186).
- **Release changelog completeness checks ignore release-note maintenance commits.**
  The `map-release` heuristic no longer counts `docs(changelog)` or
  `chore(release)` commits as user-visible changes that need their own
  changelog bullet (#191).
- **Release tag annotations now include the versioned changelog excerpt.**
  `scripts/bump-version.sh` extracts notes from the just-created release section
  instead of the now-empty `[Unreleased]` section, avoiding fallback tag messages
  such as `Release version X.Y.Z` (#194).

## [3.12.1] - 2026-06-12

### Changed
- **Legacy unfenced managed files are now silently upgraded to the fenced
  layout, removing the alarming `MIGRATION:` stderr flood on every `mapify
  init`.** Previously a managed file that carried metadata but no `map:start` /
  `map:end` fence (a pre-fence "Phase B" install) printed a scary per-file
  `MIGRATION: … Re-install with mapify to add fence structure.` line to stderr —
  yet the re-install never actually added the fence, so the file stayed
  unfenced and the same lines re-appeared on **every** subsequent `mapify init`.
  The copier now completes the migration in place: it writes the proper fence
  markers around the managed region (exactly like a fresh install), so the
  upgrade is genuinely one-time and the notice no longer reprints. The upgrade
  is silent; drifted files are still backed up to `.bak.<ts>` before rewrite.

## [3.12.0] - 2026-06-12

### Changed
- **`mapify upgrade` now self-upgrades the CLI to the latest release.**
  Previously `mapify upgrade` refreshed the *current project's* shipped MAP
  files (and, on Codex projects, only printed a re-init hint). It now upgrades
  the installed `mapify-cli` package itself: it auto-detects the install method
  and runs `uv tool upgrade mapify-cli` (uv tool installs) or
  `python -m pip install --upgrade mapify-cli` (pip installs). The command is
  now provider-agnostic and writes no project files. When already on the latest
  release it does nothing; when run from a source checkout / editable install,
  self-upgrade is disabled. To refresh a project's shipped MAP files with the
  new templates after upgrading, run `mapify init . --force`.

## [3.11.0] - 2026-06-12

### Added
- **Opt-in Stack Overflow for Agents (SOFA) integration (#169, #176, #177)**:
  a new, **off-by-default, read-only** integration enabled with
  `mapify init --sofa` (persisted as `MapConfig.sofa_enabled` /
  `sofa.enabled` in `.map/config.yaml`). Ships a stdlib-only `sofa_client.py`
  (interactive 7-step onboarding, session handling, 401-retry, credential
  resolution) and a `/map-so-search` skill (`skillClass=hybrid`) that queries
  SOFA and renders results behind an UNTRUSTED-content boundary, degrading to
  a no-op when the feature is disabled or offline. Init idempotently merges
  `.sofa/` into `.gitignore` only under `--sofa`. Credentials are never
  auto-persisted — the user is instructed to export `SOFA_API_KEY` themselves.
  Cross-cutting zero-network proofs assert no network call happens unless the
  feature is explicitly enabled, and golden render-parity tests cover the new
  surfaces across both provider trees.
- **Cross-session memory + recall (#157)**: a write-ahead-log → lazy-digest →
  recall pipeline so the framework carries learned context across sessions
  instead of starting cold each run.
- **Skill-evaluation harness + description optimizer (#158, #159, #160, #161)**:
  a skill-eval engine (MVP) with outcome eval-sets, a skill-description
  optimizer, and an HTML results viewer, plus a whole-skill outcome-eval
  harness and `map-task` body hardening. The optimized `map-plan` description
  is applied, and skill-eval/A-B polish trims ~1,000 lines of example bloat
  from the MAP agent prompts.
- **Personal/repo-global learned-rules layer (#153)**: a layered learned-rules
  system under `.claude/rules/learned/*.md` (architecture/error/security
  patterns) with a MONITOR-gate fix so captured rules feed back into the
  workflow.
- **Skill manifest dependencies (#156)**: declarative skill manifest
  dependencies with a consistency test and a host-conditional install gate.
- **`MAP_INVOKED_BY` recursion-guard contract for MAP hooks (#152)**: a
  recursion guard wired into the shipped hooks to prevent self-triggering
  loops, backed by a `lint-hooks.py` linter (wired into `make lint` /
  `make check`) and a `hook-patterns.md` classification of all shipped hooks.
- **MAP cross-workflow safety guards (#147)**: blast-radius checks, a
  recommendation gate, and actor-mismatch detection so one workflow cannot
  silently corrupt another's state.
- **Single-source template render + fence-aware managed-file copier (#155)**:
  consolidates every generated tree behind one `templates_src/` source with a
  fence-aware copier; the render invariant is enforced by `make check-render`.
- **Agent-review harness hardening (#145)**: a single source-of-truth for
  agent output schemas, a retry-prompt builder derived from that schema, and
  failure telemetry.
- **`/map-efficient` learning-handoff (#154)**: emits a deferred `/map-learn`
  handoff that auto-loads on the next run, plus a cross-subtask regression
  gate (#143).
- **Already-implemented gate in `/map-plan` (#150)** and a spec `file:line`
  citation validator (#149).
- **Clean retry quarantine (#140)** and **mutation-boundary prompt
  guardrails (#139)**.
- **Token-budget decision artifact (#136)** and **context-first XML prompt
  envelopes (#131)** for MAP agent prompts.
- **Codex `map-efficient` skill (#151)** and a skill IR audit for provider
  templates (#132).
- **Cross-cutting prep plumbing (#148)**: a `jinja2` runtime dependency, a
  `host-paths.md` contract doc, and a `_locking.py` flock primitive.
- **`normalize_blueprint` deterministic repair pass (#168)**: a new runner
  function (and `/map-plan` Step 5.55) that fixes the two self-consistency
  drifts the `task-decomposer` routinely emits, so planning is self-serve
  (`decompose → normalize → validate → proceed`) instead of requiring manual
  JSON surgery between Step 5 and the Step 5.6 contract gate. It (1) stably
  topologically sorts `subtasks[]` so every dependency is declared before its
  dependents — satisfying `validate_blueprint_contract`'s forward-dependency
  invariant without reordering by hand (independent subtasks keep their order;
  a true cycle is left for the validator to reject), and (2) for every
  `coverage_map[req] = owner` whose owner's `validation_criteria` doesn't cite
  `[req]`, appends a `[req]`-tagged criterion. It never invents `coverage_map`
  ownership or rewrites dependency edges — genuine semantic gaps still fail
  Step 5.6. Idempotent. Run via
  `python3 .map/scripts/map_step_runner.py normalize_blueprint [<path>] [--check]`.
- **Per-subtask token accounting**: a new `map-token-meter` hook (wired on
  `SubagentStop` and `Stop`) reads each transcript's per-turn `usage` and
  attributes input/output/cache-creation/cache-read tokens to the active
  subtask, phase, and agent. Rows append to `.map/<branch>/token_log.jsonl`
  (deduplicated by message id) and roll up into `token_accounting.json` with
  `by_subtask`/`by_agent`/`by_phase` buckets, `est_cost_usd` (priced per model
  in `MODEL_TOKEN_PRICES`), and `cache_hit_ratio`. Inspect via
  `python3 .map/scripts/map_step_runner.py token_report <branch>`. The
  parsing/recording/rollup logic is self-contained in `map_step_runner.py`
  (stdlib only) so it works in generated projects without `mapify_cli`
  importable; the meter is advisory and never blocks a turn.

### Changed
- **Agent prompt budgets tightened**: Actor context budget is now enforced
  (#134), `/map-review` reviewer prompts are bounded (#135), and the MAP
  harness context gates are hardened (#141).
- **High-traffic skill bodies compacted**: the `map-resume` skill body (#137)
  and other high-traffic MAP skill playbooks (#138) were slimmed down.
- **Build/CI runs through `uv run`**: lint and tests invoke `uv run` and
  `pyright` is pinned to the project venv, so a global interpreter on `PATH`
  can no longer shadow the venv and produce phantom failures.
- **Closed the shipped TDD handoff plan item (#133)**.

### Fixed
- **Token accounting double-counted ~2× (#165)**: the token-meter re-logged
  repeated `msg_id` entries (one row per content block); rows are now
  deduplicated by message id so `est_cost_usd` is no longer inflated.
- **Co-authored test files no longer trip `validate_mutation_boundary`
  (#163)**: files carrying a co-author trailer are recognised as in-scope
  subtask work instead of being flagged as an out-of-boundary mutation.
- **Eight framework gaps surfaced in a downstream run (#142)** plus
  skill-routing, `conftest` PYTHONPATH, and pyright-gate fixes (#149).
- **`/map-plan` resume-detection compares plan goals instead of branch-keying
  alone (#166)**: a single git branch can host more than one sequential
  planning effort over its lifetime, but the Resume-Detection preflight keyed
  "plan complete" purely on `test -f .map/<branch>/step_state.json`. A
  brand-new, unrelated request on a branch that already held a *completed* plan
  was therefore falsely off-ramped as "plan complete" (no plan produced), and
  proceeding anyway silently clobbered the prior plan's `spec`/`blueprint`/
  `task_plan`. New `check_plan_resume "<request>" [--branch <b>]` runner
  function reports the existing artifacts AND a `verdict`
  (`no_plan`/`resume`/`goal_mismatch`) by comparing the prior plan's goal
  (from `task_plan`/`spec`) against the incoming request via a deterministic
  token-overlap (containment) heuristic. On `goal_mismatch` the skill no longer
  prints "plan complete" and does not overwrite the prior artifacts — it
  recommends archiving/renaming `.map/<branch>/` (or planning on a fresh
  branch) with operator confirmation, then planning the new goal. Comparison is
  intentionally conservative — both sides must carry ≥2 significant tokens and
  fall below the containment threshold, so a legitimate resume with a shorter
  paraphrase (or a bare `/map-plan` with no request text) is never falsely
  diverted. Both provider surfaces (Claude + Codex `map-plan` SKILL) and
  `plan-reference.md` document the single-plan-per-branch layout and the
  `goal_mismatch` off-ramp.
- **`workflow-gate` RESEARCH block scoped to the current subtask's
  `affected_files` (#164)**: during the RESEARCH phase the gate used to block
  *every* `Edit`/`Write`/`MultiEdit` (except docs-only surfaces), so orthogonal
  out-of-band fixes — a repo-root config, an unrelated failing test, a hotfix
  the operator explicitly asked for — had to be smuggled through `Bash`
  heredocs, losing read-before-write safety and minimal-diff review. The gate
  now lifts the RESEARCH block for any target that is *provably outside* the
  current subtask's declared `affected_files` (resolved from `blueprint.json`),
  while files inside that surface stay blocked so research-before-code is still
  enforced where it matters. The relief is conservative — it falls back to the
  strict block whenever the mutation surface can't be determined (no blueprint,
  unknown subtask, empty `affected_files`, or an out-of-repo target) — and it
  still honours `scope_glob`/constraints, so it can't silently widen scope. The
  `Bash` write bypass noted in the issue is documented as a known limitation
  and deferred (closing it needs shell write-target parsing that risks
  false-positives across host repos).
- **Structural create-vs-modify replaces magic-prose matching in
  `validate_blueprint_contract` (#167)**: the `affected_files`-drift check used
  to decide "this subtask creates a new file" by string-matching prose phrases
  (`creates new` / `new file` / `introduces` / `adds new`) in the free-text
  subtask `description` — brittle, and it forced authors to pollute descriptions
  with boilerplate written for the parser. Subtasks now carry an optional
  structural `creates_files: [...]` field (the subset of `affected_files` created
  from scratch). The validator marks those paths *expected-absent* and only
  warns drift for missing **modify-targets**; the deprecated prose heuristic
  survives solely as a fallback for blueprints that predate the field. A
  `creates_files` path not listed in `affected_files` is a hard error (a created
  file is part of the mutation surface the scoped gates allow), and
  `normalize_blueprint` self-heals it by unioning such paths into
  `affected_files` so the `decompose → normalize → validate` loop stays
  self-serve. The `task-decomposer` schema, field docs, and planning checklist
  now point to `creates_files` instead of description prose.
- **False-progress on every committed subtask (#162)**: `validate_step 2.4`
  (which auto-runs `validate_mutation_boundary`) compared the *working tree*
  against the contract's `affected_files`. In the documented per-subtask close
  order — commit → `record_subtask_result --commit-sha` → `validate_step 2.4` —
  the working tree is clean and `last_subtask_commit_sha` already points at the
  subtask's OWN commit, so the diff was empty and the gate wrongly rejected
  every committed subtask with *"MONITOR is closing ST-XXX but NO files
  changed"*, forcing a redundant second call. The base-ref resolution now
  re-bases onto the subtask commit's parent when the resolved base is the
  subtask's own recorded commit, so the committed work counts as the mutation
  surface. Resolution is shared by `validate_mutation_boundary` and
  `_current_subtask_changed_files` via a new `_resolve_subtask_diff_base`
  helper (root-commit safe).

## [3.10.0] - 2026-05-19

### Added
- **Persisted review bundle**: `create_review_bundle()` writes durable
  `review-bundle.json` and `review-bundle.md` under `.map/<branch>/` so
  `/map-review` runs from a fresh chat context without relying on implementer
  session memory. Bundle JSON contract is captured in `REVIEW_BUNDLE_SCHEMA`
  (`src/mapify_cli/schemas.py`).
- **`/map-review --detached` flag**: `prepare_detached_review()` opens an
  isolated `git worktree add --detach` worktree at
  `.map/<branch>/detached-review/` so reviewer agents read source from a clean
  copy. The source branch is never mutated; graceful degradation to in-place
  bundle on `unavailable`/`error`.
- **Soft schema validation in `create_review_bundle()`**: bundle JSON is
  validated against `REVIEW_BUNDLE_SCHEMA` after assembly. On failure the file
  is still written, gains a `schema_validation_error` array, and the manifest
  review stage is downgraded from `ready` to `warn`.
- **Path-traversal guard on `prepare_detached_review`**: explicit `target_dir`
  values that resolve outside `.map/<branch>/` (or the `.map/` root) are
  rejected with `status="error"` before any git mutation.
- **`code_state.diff_truncated` flag**: `snapshot_code_state` caps `diff_stat`
  at 64 KiB and `files_changed` at 500 entries, surfacing a `diff_truncated`
  marker so reviewers can see the snapshot was clipped on very large repos.
- **`hypothesis` test dependency**: added to `[project.optional-dependencies]`
  `test` / `dev` extras for property-based coverage of `_sanitize_for_json`.
- **Context compression policy**: New `compression_policy` setting in `.map/config.yaml`
  with three modes — `never` (quality-leaning), `auto` (default, nudges at 120k tokens),
  and `aggressive` (nudges at 0.4 × threshold = 48k by default).
- **`mapify init --compression {never,auto,aggressive} --compression-threshold N`**:
  set the policy and absolute threshold at project init time. Persisted into
  `.map/config.yaml`.
- **`context-meter.py` hook (UserPromptSubmit)**: counts tokens from the last
  assistant turn in `transcript_path` and injects a `/compact <focus>`
  recommendation into the assistant's context when the threshold is crossed.
  Honours a 5-minute cooldown via `.map/<branch>/last-compact.marker` so it
  does not double-fire after Claude Code's built-in 83.5% auto-compact.
- **`mapify_cli.token_budget`**: pure module exposing
  `count_last_turn_tokens`, `effective_threshold`, `should_nudge`,
  `format_compact_instruction`. 25 unit tests in `tests/test_token_budget.py`.
- **Orchestrator `--transcript-path` flag**: `map_orchestrator.py` accepts
  `--transcript-path` (or env `MAPIFY_TRANSCRIPT_PATH`) and emits the same
  `/compact` recommendation to stderr at every command. Provider-agnostic —
  works for both Claude Code and Codex sessions.
- **Design doc**: `docs/context-compression-plan.md`.
- **`/map-explain` skill**: new manual slash surface for deep code, PR, and
  project walkthroughs. Synced into shipped templates so generated projects
  get the same explainer workflow.
- **`/map-review` order-bias hardening (Phase 1)**: review prompts now use
  randomized agent order, evidence-tagged findings, and explicit anti-bias
  checks so reviewer agents are less susceptible to ordering effects in
  multi-agent fan-out.
- **Skill `skillClass` runtime taxonomy**: `.claude/skills/skill-rules.json`
  and the shipped template copy declare `task`, `reference`, or `hybrid` for
  every shipped skill. Hybrid skills must enumerate `runtimeEffects`. The
  skills README and user docs distinguish runtime boundaries instead of
  treating every skill as passive documentation.
- **Run health report artifact**: `write_run_health_report` in
  `.map/scripts/map_step_runner.py` (and shipped template copy) emits
  `.map/<branch>/run_health_report.json` with terminal status, step
  progress, artifact presence, retry counters, Predictor/final-verifier
  signals, and hook-injection state. Backed by `RUN_HEALTH_REPORT_SCHEMA`
  and a new `run_health` stage in `artifact_manifest.json`.
- **Run health closeout wiring**: `/map-efficient`, `/map-debug`,
  `/map-check`, and `/map-review` write `run_health_report.json` after the
  terminal verdict is known. Closeout snippets set `RUN_HEALTH_STATUS` from
  the verdict instead of defaulting to `complete`, preserving `pending`,
  `blocked`, `won't_do`, and `superseded` paths.
- **Expanded hook degradation status coverage**: `workflow-context-injector.py`
  now records explicit skipped-hook reasons for malformed input, non-object
  payloads, non-injected tools, and insignificant Bash commands when an
  existing branch `step_state.json` can be safely parsed and updated.
- **Run health validator**: `validate_run_health_report` enforces required
  fields, terminal-status enum, artifact inventory entries, resiliency
  signal types, complete-without-pending-steps, complete-without-verification,
  retry overflow, and hook degradation reasons. Works in generated projects
  without `mapify_cli.schemas`.
- **Contract-sized subtask guardrails**: `validate_blueprint_contract` fails
  oversized, mixed-concern, untraceable, duplicate-ID, dangling-dependency,
  or non-logical subtasks before implementation starts. Blueprint schema
  gains `expected_diff_size`, `concern_type`, `one_logical_step`,
  `aag_contract`, `validation_criteria`, and `coverage_map` (with nested
  TaskDecomposer output support). Monitor and FinalVerifier prompts check
  for scope drift after planning.
- **Evidence-first prompt outputs**: `.claude/references/map-output-examples.md`
  provides a shared evidence-first JSON examples file. `/map-review`
  Monitor/Predictor/Evaluator, `/map-debug` investigation, and `/map-plan`
  spec-review/decomposition prompts now require `evidence[]` (with concrete
  quotes from logs, code, tests, or spec) before verdict, risk, or score
  fields. HIGH/CRITICAL issues, breaking changes, and sub-7 scores must be
  evidence-tied.
- **JSON prompt-contract lint**: `.claude/references/map-json-output-contracts.md`
  is the reusable backing reference for non-evidence JSON prompt sections.
  `/map-fast`, `/map-debug`, and `/map-learn` non-evidence outputs declare
  explicit contract references. `tests/test_skills.py` adds a generic
  scanner over both `.claude/skills/` and the shipped templates that fails
  if future JSON prompt sections lack either evidence or a contract
  reference.
- **Blueprint acceptance-criteria lineage**: every `coverage_map` key in
  `blueprint.json` must now appear as a bracketed tag in the owning
  subtask's `validation_criteria` (e.g., `VC1 [AC-1]: ...`).
  `validate_blueprint_contract` fails untagged validation criteria before
  Actor starts and names the missing tag.
- **Hard/soft constraint typing**: blueprint schema adds `hard_constraints`
  and `soft_constraints`. Hard constraint ids must appear in `coverage_map`
  and the owning subtask's bracketed `validation_criteria`; soft
  constraints may be omitted only with `tradeoff_rationale`. Planner and
  decomposer prompts (Claude and Codex) ask for and validate the contract.
- **Acceptance coverage reporting**: `write_verification_summary` and
  `create_review_bundle` summarize every `blueprint.json` `coverage_map`
  tag, marking each `covered` only when bracketed evidence (e.g., `[AC-1]`,
  `[INV-1]`) appears in downstream verification, QA, test contract,
  handoff, PR draft, or review artifacts. Otherwise outputs show
  `missing_evidence`. `REVIEW_BUNDLE_SCHEMA`, review-bundle Markdown, and
  manifest review-stage metadata surface both human and machine views.
- **Prior-stage artifact consumption gates**:
  `build_prior_stage_consumption_report` and
  `validate_prior_stage_consumption <implementation|review>` prove whether
  spec, task plan, blueprint, test contract, code diff, and review-time
  verification summary were consumed. `write_verification_summary` and
  `create_review_bundle` include `prior_stage_consumption`; review
  manifest status downgrades to `warn` when required prior-stage inputs
  are missing instead of hiding stage skipping.
- **Workflow effort and parallelism policies**: every shipped MAP task
  skill declares `## Effort and Parallelism Policy` with explicit
  `thinking_policy` (low/medium/high) and `parallel_tool_policy`.
  Lightweight workflows (`/map-fast`, `/map-check`, `/map-resume`) use
  `low/direct`; implementation/learning workflows use `medium/adaptive`;
  planning, review, and release use `high/adaptive`. Top-level
  `workflow-rules.json` records execution policies for workflow-triggered
  `/map-fast`, `/map-efficient`, and `/map-debug` suggestions.

### Changed
- **Workflow gate `COMPLETE` phase is permissive**: post-workflow polish and
  follow-up review fixes are no longer blocked. The atomic-completion invariant
  in `map_orchestrator.mark_workflow_complete` is the only writer of
  `current_step_phase=COMPLETE`, so the trust boundary is documented in-line
  on `TERMINAL_PHASES`.
- **Workflow gate `.claude/rules/learned/` exemption tightened to `*.md`**:
  the exemption now requires a markdown filename so the directory cannot
  quietly widen into a general bypass for arbitrary file types.
- **Stub detection in review bundle**: `_fixed_artifact_entry` now flags
  `verification-summary.md` and `pr-draft.md` as `present=False` when their
  content matches the strict initial placeholder (from `HUMAN_ARTIFACT_DEFAULTS`)
  or the writer-emitted soft stub (all sections `- [not recorded]`).
- **Skill rename `map-planning` → `map-state`**: resolves a slash-command
  collision where `/map-plan` was fuzzy-matched to the longer `map-planning`
  name when `map-plan` was hidden via `disable-model-invocation`. The skill
  body, hooks, and scripts are unchanged — only the directory and the entry
  in `skill-rules.json` are renamed. Existing `.map/<branch>/` artifacts
  remain compatible.
- **`map-plan` becomes model-invocable**: removed `disable-model-invocation:
  true` from `map-plan` SKILL frontmatter so the model sees `map-plan` and
  `map-state` as distinct skills and `/map-plan` resolves to the ARCHITECT
  decomposition skill instead of the planning-state skill.
- **`map_orchestrator.py` is now cwd-independent**: anchors itself to the
  project root via `Path(__file__).resolve().parents[2]` before any state
  lookup. Previously, invoking the orchestrator via an absolute path from a
  different cwd silently read `.map/<branch>/` from the caller's directory
  and returned misleading "step mismatch" errors.
- **Block "pre-existing, unrelated" excuse for surfaced quality-gate
  failures**: Monitor scope now distinguishes pre-existing DORMANT tech
  debt (still OUT OF SCOPE) from pre-existing SURFACED failures —
  lint/type/test errors that fail in the current run, regardless of
  whether the failing code predates the diff, must be fixed and are not
  downgraded to LOW. Actor's QUICK REFERENCE and Subtask Intent now ban
  one-line "pre-existing, unrelated" dismissals; deferral requires explicit
  user approval. Captured as a learned rule in
  `.claude/rules/learned/error-patterns.md`.
- **Hardened `map_step_runner._sanitize_for_json`**: the previous regex
  preserved `\t \n \r` and relied on `json.dumps` to escape them, but
  bash command substitution (`BUNDLE=$(... build_handoff_bundle)`) does
  not preserve byte-perfect roundtrip in all locales — `jq` then aborts
  with `Invalid string: control characters from U+0000 through U+001F
  must be escaped`. The function now flattens newline variants to spaces
  and strips the entire `\x00-\x1f\x7f` range so the bundle is robust
  through bash pipelines. Learned rule updated with WRONG/CORRECT
  example.
- **Action-first lightweight workflows**: `/map-fast` and `/map-debug`
  write-capable Actor steps edit files directly with Edit/Write tools and
  return compact summaries (`files_changed`, `tests_run`,
  `remaining_risks`) instead of serialized full-file `code_changes`.
  Monitor prompts validate written repo state from `Written Files`, and
  stale post-validation apply instructions are removed from workflow
  overviews and decision points.
- **Skill invocation metadata hardening**: regression tests now require
  manual slash skill classification to match frontmatter, assert direct
  invocation names appear in trigger keywords/patterns, verify selected
  negative-trigger fixtures do not match noisy skills, check that local
  Markdown supporting-file links resolve, validate hook commands using
  `CLAUDE_PLUGIN_ROOT` point at bundled scripts, and confirm non-`SKILL.md`
  supporting files stay synced into templates.
- **Calibrated workflow prompt guardrails**: non-release MAP skills use
  targeted guardrails and normal wording instead of blanket all-caps
  prohibition blocks. `/map-release` keeps explicit hard-stop language
  because tag pushes and PyPI publication are irreversible. Lightweight
  and resume workflows now have explicit `When Not To Expand Scope`
  clauses. Prompt-tone regression coverage rejects blanket prohibition
  blocks in non-release task skills.

### Fixed
- **Codex provider polish**: deprecated `codex_hooks` references; documented
  the required pre-tool-use hook configuration step in `docs/INSTALL.md`;
  noted leading-slash usage for Codex users in `docs/USAGE.md`; fixed
  `pyproject.toml` dev dependency declaration; aligned shipped Codex docs
  and CI checks (`.codex/AGENTS.md`, `.codex/config.toml`,
  `.github/workflows/ci.yml`).

## [3.9.0] - 2026-04-22

### Added
- **Codex CLI provider**: `mapify init . --provider codex` installs `.codex/` layout (skills, TOML agents, hooks) for OpenAI Codex CLI
- **Provider abstraction**: `BaseProvider` ABC and `ClaudeProvider`/`CodexProvider` in `mapify_cli.delivery.providers`
- **Provider-aware commands**: `mapify check`, `mapify doctor`, `mapify upgrade` now detect and adapt to the active provider

### Fixed
- **Workflow gate step-ID translation**: `subtask_phases` values (step IDs like "2.3") are now properly translated to phase names via `STEP_ID_TO_PHASE` dict before comparison against `EDITING_PHASES`
- **get_project_health provider awareness**: No longer reports `.claude/*` as missing paths for Codex-initialized projects

### Changed
- **Tagline**: Changed from "MAP Kit - for Claude Code" to "MAP Kit - Modular Agentic Planner Framework"
- **init() uses ClaudeProvider**: The claude path in `init()` now delegates to `ClaudeProvider.install()` instead of calling individual file creation functions directly

## [3.8.0] - 2026-04-17

### Added
- **Skill frontmatter hygiene**: Automated validation and cleanup of skill frontmatter across all MAP skills (#100)
- **Skill-first map-learn**: `/map-learn` now operates as a skill-first workflow for better integration (#99)
- **Repeated learned-rule violation tracking**: System now detects and tracks when learned rules are violated repeatedly (#98)
- **Learning handoff artifacts**: New artifacts for preserving learning context across workflow handoffs (#97)

### Changed
- **MAP runtime alignment**: Aligned runtime with workflow-fit handoffs for smoother transitions
- **Handoff flow improvements**: Addressed review feedback on handoff flow

### Fixed
- **Artifact timestamps and manifest branch loading**: Fixed timestamp handling in artifacts and branch loading in manifest

## [3.7.0] - 2026-04-11

### Added
- **Context-aware step injection**: Two-layer "active window" context system that replaces full plan injection with focused current-subtask context
  - Hook layer: `workflow-context-injector.py` now includes goal + subtask title in ≤500 char reminders
  - Actor prompt layer: structured `<map_context>` block with goal, current subtask details, sibling summaries, upstream results, and repo delta
  - New helpers in `map_step_runner.py`: `load_blueprint()`, `get_subtask_from_blueprint()`, `get_upstream_ids()`, `build_context_block()`
  - New `StepState` fields: `subtask_results` (per-subtask outcome tracking), `last_subtask_commit_sha` (differential insight baseline)
  - New function `compute_differential_insight()` in `repo_insight.py` for git-diff-based file change tracking between subtasks
- **Automatic ACTOR retry on Monitor failure**: Monitor `valid=false` now triggers automatic Actor retry instead of requiring manual intervention
- **Integration awareness in agent templates**: MAP agent templates now include integration test and reference accuracy checks (Step 5.7 in `/map-plan`)
- **Coverage verification in `/map-plan`**: Anti-compression guards ensure decomposer output preserves all subtasks and acceptance criteria
- **Integration tests and e2e Make targets**: New `make e2e` targets for end-to-end testing of plan-to-execution pipeline
- **Learned rules**: Added architecture patterns and error patterns from parallel wave and frontmatter bugfixes

### Changed
- **Mandatory research and sequential execution**: `/map-efficient` enforces mandatory research phase and build gate; sequential execution when parallel waves unavailable
- **Decomposer granularity rules**: Removed artificial `max_subtasks` constraint; added granularity rules to prevent over-splitting or under-splitting

### Fixed
- **Parallel wave execution**: Orchestrator now correctly supports parallel wave execution without state corruption
- **YAML frontmatter preservation**: Managed `.md` files no longer corrupt YAML frontmatter during metadata injection
- **Monitor phase enforcement**: Monitor phase marked as MANDATORY — never skipped even if tests pass
- **CLI dispatch and sanitization**: Fixed path consistency, injection safety, DRY violations, deleted file handling, and word truncation
- **Template sync**: `map-plan.md` template synced with dev copy
- **Code quality**: Resolved black formatting issues in 12 files and ruff lint errors (E402 import order, F841 unused variables)

## [3.6.0] - 2026-03-26

### Changed
- **Pipeline simplification**: `/map-efficient` reduced from 11 phases to 2-3 per subtask ([RESEARCH] → ACTOR → MONITOR). Removed XML_PACKET, CONTEXT_SEARCH, PREDICTOR, UPDATE_STATE, TESTS_GATE, LINTER_GATE, VERIFY_ADHERENCE, SUBTASK_APPROVAL phases
- **Per-wave gates**: Tests and linter now run once per wave (after all Monitor passes) instead of per subtask
- **Single state file**: `workflow_state.json` merged into `step_state.json` as single source of truth
- **Workflow gate rewrite**: Phase-based enforcement (ACTOR/APPLY/TEST_WRITER phases allow Edit) instead of completed_steps checking
- **Predictor**: No longer a pipeline phase; runs only during stuck recovery at retry 3

### Removed
- Evidence files and evidence directory (write-only artifacts nobody read)
- `session-log.md` and `devlog-XXX.md` (boilerplate, replaced by `code-review-XXX.md`)
- `workflow_state.json` (replaced by `step_state.json`)
- 8 pipeline phases (see Changed above)

### Added
- **Persist `/map-learn` lessons to `.claude/rules/`**: Extracted lessons are saved as rule files so future sessions apply them automatically
- **Platform refactor**: Extracted spec, decomposition, config, and managed file copier into standalone modules for cleaner architecture
- **Guard pattern**: Decision table for regression detection (monitor pass + guard fail → retry Actor max 2)
- **Stuck recovery protocol**: At monitor retry 3, invoke research-agent → predictor before retries 4-5
- **Scenario dimensions**: `test_strategy.scenario_dimensions` (happy_path, error, edge_case, security) in TaskDecomposer
- **Constraint enforcement**: `scope_glob` in workflow-gate.py hook
- **Flaky-aware verification**: FinalVerifier re-runs failed tests 3x with 2/3 majority rule
- **Iteration summary**: `iteration_summary.json` derived from ralph-iteration-logger
- **Git-as-memory**: Conditional `{{git_history}}` context in Actor for debug/retry/resume

### Fixed
- **Lint cleanup**: Removed unused imports, added re-export aliases, fixed E402 module ordering in `__init__.py`
- **Mypy config**: Added `[tool.mypy]` section to `pyproject.toml` excluding template scripts and ignoring missing yaml stubs

## [3.5.0] - 2026-03-18

### Added
- **TDD workflow (`/map-tdd`)**: Test-first development mode where tests are written from specification before implementation. Includes TEST_WRITER (2.25) and TEST_FAIL_GATE (2.26) phases
- **`--tdd` flag for `/map-efficient`**: Enables TDD mode within the standard efficient workflow
- **TDD support in Actor agent**: Two new modes — `test_writer` (write only tests from spec) and `code_only` (implement to make tests green, no test modifications)
- **`set_tdd_mode` orchestrator command**: Enable/disable TDD phases in the state machine
- **Single subtask execution (`/map-task ST-001`)**: Execute one specific subtask from an existing plan without running the full workflow. Requires `/map-plan` first
- **Single subtask TDD (`/map-tdd ST-001`)**: Write TDD tests and implement a specific subtask. Combines single-subtask execution with test-first development
- **`resume_single_subtask` orchestrator command**: Sets up state for executing a single subtask with optional `--tdd` flag
- **Enhanced SPEC phase in `/map-plan`**: Structured spec template with Invariants, Edge Cases, Acceptance Criteria, and Security Boundaries sections
- **Devil's Advocate review step**: After spec creation, Monitor agent adversarially reviews the spec for race conditions, ownership ambiguity, missing edge cases, contradictions, and security gaps (skipped for complexity < 5)
- **Spec invariant linkage in task-decomposer**: Contracts must trace back to spec invariants when spec exists; checklist enforces coverage
- **`skipped_steps` tracking**: TDD steps skipped when TDD is disabled are tracked separately from completed steps, making TDD toggle reversible
- **Plan progress tracking (`get_plan_progress`)**: Shows completed/pending subtask counts and suggests next subtask

### Fixed
- **`--tdd` flag leak**: Flag was leaking into agent prompts via `$ARGUMENTS`; now stripped into `$TASK_ARGS`
- **Wave-mode TDD support**: Waves now start subtasks at TEST_WRITER (2.25) instead of ACTOR (2.3) when TDD is enabled
- **`set_tdd_mode` restart bug**: Toggling TDD after first subtask no longer re-introduces completed global steps (1.x)
- **TDD toggle reversibility**: Re-enabling TDD correctly re-introduces TEST_WRITER/TEST_FAIL_GATE phases even when they come before the current position
- **ARCHITECTURE.md phase list**: Added missing `2.1 CONTEXT_SEARCH`, fixed `CHOOSE_MODE` description
- **SKIPPABLE_STEPS docstring**: Added 2.25/2.26 to documented skippable steps
- **`get_plan_progress` docstring**: Removed incorrect claim about dependency-aware ordering
- **Workflow gate `~/.claude/` scope**: Narrowed exemption from entire `~/.claude/` to only `~/.claude/projects/*/memory/`
- **Missing `blueprint.json` in `/map-plan`**: Added Step 5.5 to save decomposer output as `blueprint.json` for wave computation; `/map-efficient` gracefully falls back to sequential execution when missing

## [3.4.1] - 2026-03-09

### Fixed
- **Blueprint parsing in set_waves**: support nested decomposer output format where subtasks are under `blueprint.blueprint.subtasks`

## [3.4.0] - 2026-03-09

### Added
- **Pre-compact transcript saver** hook to preserve conversation context before compaction
- **SessionStart(compact) hook** to inject transcript path after compaction for context continuity

### Fixed
- **Hook test coverage**: replaced deleted hook tests with safety-guardrails tests
- **Copilot review comments**: addressed feedback from automated code review
- **Black formatting** in hook template files (safety-guardrails, workflow-gate, ralph-context-pruner)

## [3.3.0] - 2026-03-05

### Added
- **Wave-based parallel subtask execution** in `/map-efficient` with dependency-graph-driven wave ordering
- **Resume detection** in `/map-plan` for continuing interrupted planning sessions
- **Interactive 4-section map-review** rewrite with structured review flow

### Changed
- **Monitor forwarding**: Actor now forwards directly to Monitor instead of debugging after Actor phase
- **Parallel wave enforcement**: Enforced parallel wave execution in map-efficient workflow
- **Auto batch mode**: Automatically set batch mode in map-efficient, skip CHOOSE_MODE step
- **Monitor hard stop**: `valid=false` from Monitor is now a hard stop requiring fixes before proceeding
- **Integrated AAG contracts** with validation criteria enforcement (VC→tests)

### Removed
- **SQLite Knowledge Graph** modules removed entirely
- **Cipher and playbook references** removed, migrated to mem0 patterns terminology
- **mem0/ACE/Curator** agents removed, simplified architecture
- **context7 and claude-reviewer** MCP server configurations removed
- **Curator agent** template files removed

### Fixed
- **Claude Code hook configuration** and outputs for correct schema compliance
- **Workflow gate** now allows map artifact updates
- **Evidence writes** replaced heredoc pattern with Write tool, added predictor skip logic
- **PR review findings** across agents, CLI reference, and templates
- **Hook robustness** improvements and documentation
- **Black formatting**, ruff lint, and mypy type errors across 11 files

## [3.2.0] - 2026-02-14

### Added
- **Artifact-gated validation** in MAP orchestrator for stricter workflow enforcement
- **Enhanced skills** with examples, troubleshooting sections, trigger rules, and validation scripts
- **skip_step command** for MAP orchestrator to allow controlled step skipping

### Fixed
- **Documentation accuracy audit** (48 fixes): Comprehensive alignment of all docs, presentations, and templates with actual implementation
  - Corrected agent count references across all docs (8/9/11 → 12 agents)
  - Corrected command count references (updated to 10 MAP commands)
  - Added missing agents (Synthesizer, DebateArbiter, ResearchAgent, FinalVerifier) to ARCHITECTURE.md and presentations
  - Replaced phantom `/map-feature` and `/map-refactor` references with implemented workflows
  - Removed stale haiku model references from presentations
  - Fixed Evaluator workflow assignments and map-fast agent pipeline docs
- **Template variable consistency**: Resolved 8 template variable inconsistencies (`{{standards_url}}` → `{{standards_doc}}`, etc.)
- **Branch sanitization**: Unified branch name sanitization across all hooks, commands, and agents
- **Path conventions**: Corrected flat `.map/` path references to nested `<branch>/` directory convention
- **API parameter naming**: Fixed `top_k` → `limit` in documentation-reviewer and other agents
- **MAP workflow inconsistencies**: Resolved 35 audit issues across orchestrator, commands, and agent templates
- **Plan path bug** and evidence indentation in orchestrator
- **Removed stale references**: Cleaned up RETRY_LOOP/APPLY_CHANGES step references
- **Test fixtures**: Updated to cover all 12 agents and 10 commands
- **Black formatting**: Fixed formatting in 4 template/test files

## [3.1.0] - 2026-02-09

### Changed (BREAKING)
- **Hook-Based Context Injection**: Optimize /map-efficient workflow with state-machine orchestration
  - **Problem**: 995-line command file (5.4K tokens) caused attention dilution → 20% step compliance
  - **Solution**: State-machine + PreToolUse hook injection → 85% predicted compliance
  - Command file reduced: 995 → 394 lines (5.4K → 1.75K tokens, 68% reduction)
  - New hook: `workflow-context-injector.py` - Injects step reminders before every tool call
  - New state machine: `.map/scripts/map_orchestrator.py` - Enforces 14-phase workflow sequencing
  - New utilities: `.map/scripts/map_step_runner.py` - Deterministic step executors
  - State file: `.map/<branch>/step_state.json` - Tracks current step phase for hook injection
  - Token efficiency: 54K → 9.25K per workflow (83% reduction despite hook overhead)
  - **Migration**: Run `mapify init` to update project structure with new hooks and scripts
- **Simplified Workflow**: Removed workflow-gate.py enforcement hook
  - Actor now applies code directly with Edit/Write tools (no gate blocking)
  - Monitor validates WRITTEN code by running tests, not proposals
  - Simpler flow: Actor writes → Monitor tests → If issues, Actor fixes → Repeat
  - Phase 2.7 renamed: APPLY_CHANGES → UPDATE_STATE (code already applied by Actor)

### Added
- **Ralph Wiggum Loop Integration**: Continuous iteration pattern to prevent premature completion and hallucinated success
  - State machine with 10 phases (INIT → DECOMPOSITION → EXECUTION → FINAL_VERIFICATION → COMPLETE/RE_DECOMPOSITION/ESCALATE/HARD_STOP/RECOVERY/WONT_DO)
  - Circuit breaker with configurable limits (max 50 tool calls, 5 same-file edits, 60 min wall time)
  - Final verification step in map-efficient.md (Step 3.5) with re-decomposition on failure
  - Thrashing detection (oscillation detection via net_progress and confidence_variance)
  - Recovery path via RESET_LIMITS marker file
- **New Agent**: `final-verifier.md` - Adversarial verifier with Root Cause Analysis for Ralph Loop
- **New Hooks**:
  - `ralph-circuit-breaker.py` (PreToolUse): Enforces iteration limits, blocks at thresholds
  - `ralph-iteration-logger.py` (PostToolUse): Logs metrics, detects thrashing patterns
  - `ralph-context-pruner.py` (PreCompact): Archives old logs, truncates large files
- **New Python Modules**:
  - `src/mapify_cli/ralph_state.py`: State machine, circuit breaker config, verification types, thrashing detection
  - `src/mapify_cli/dependency_graph.py`: Cascade invalidation for subtask dependencies
- **New Configuration**: `.claude/ralph-loop-config.json` - Single source of truth for Ralph Loop limits
- **New Reference**: `.claude/references/escalation-matrix.md` - Escalation decision rules

### Changed
- **task-decomposer.md**: Enhanced with Acceptance Criteria table format, re-decomposition mode, dependency enforcement
- **map-efficient.md**: Added Step 3.5 Final Verification with circuit breaker check, final-verifier invocation, re-decomposition logic
- **.claude/settings.json (hooks)**: Added PreToolUse, PostToolUse, and PreCompact hook entries for Ralph Loop

### Documentation
- Branch-scoped artifacts stored in `.map/<sanitized-branch>/` directory
- Branch name sanitization (e.g., `feature/foo` → `feature-foo`) for safe filesystem paths

## [3.0.0] - 2026-01-16

### Changed (BREAKING)
- **Memory layer migration**: Migrate from `playbook.db` to mem0 MCP for all pattern storage. This is a breaking change that requires mem0 MCP server configuration.

### Added
- P0 foundation implementation: security hooks, permissions system, workflow recovery
- mem0 MCP integration for tiered pattern storage (branch → project → org scopes)
- Project settings allowlist extensions for worktree, sourcecraft, mem0 MCP tools

### Fixed
- Address PR #70 review feedback for P0 foundation
- Align documentation with actual implementation
- Workflow enforcement to prevent Actor→Monitor cycle skip
- Documentation fixes: ARCHITECTURE.md workflow diagrams, deprecated /map-feature /map-refactor references
- Code quality: Black formatting, ruff linting, mypy type errors

### Documentation
- Complete migration of playbook.db references to mem0 MCP across all docs and templates
- Comprehensive documentation update to v2.3.0 standards
- README optimization (418→93 lines) for improved conversion

## [2.3.0] - 2026-01-10

### Added
- `/map-planning` skill: File-based planning for MAP Framework workflows with branch-scoped task tracking in `.map/` directory
- Single-Writer Governance and 3-Strike Protocol for plan modification control
- Integration of map-planning skill with mapify templates and orchestrator

### Fixed
- Critical bugs in map-planning skill session state management

### Documentation
- Updated README and skills docs for map-planning skill

## [2.2.0] - 2026-01-08

### Added
- `/map-debate` command: Debate-based MAP workflow with Opus arbiter for multi-variant synthesis. Generates 3 Actor variants in parallel (security/performance/simplicity focus), validates with parallel Monitors, then uses `debate-arbiter` (Opus model) to cross-evaluate and synthesize optimal solution

### Changed
- Documentation cleanup: Remove deprecated `/map-feature` references, update learning workflow info

### Fixed
- Address reviewer feedback on map-debate documentation

## [2.1.0] - 2026-01-07

### Added
- External static analysis scripts for Monitor agent (`analyze.sh`, `lint-go.sh`, `lint-python.sh`)
- LLM Council recommended improvements to MAP workflow (context7 integration, parallel execution)

### Changed
- Optimize task-decomposer template with references to mapify init
- Extract common functions to shared module with tests
- Update README and sync templates with map-efficient improvements

### Fixed
- Security hardening per Copilot review
- Improve clarity per Copilot review comments (multiple rounds)
- Fix agent count documentation (8→10) and update template sync
- Fix black formatting issues

### Documentation
- Document map-efficient command template
- Sync map-efficient.md documentation with source template

## [2.0.0] - 2025-12-15

### Changed
- Parallelize Monitor, Predictor, Evaluator agents in `/map-review` workflow for improved performance
- Auto-create `.mcp.json` during `mapify init` for better MCP server integration

### Fixed
- Remove hooks-related CI job and test after hooks system removal
- Restore JSON validation in stop.sh hook for malformed input handling
- Address Copilot and LLM Council security review findings
- Clarify enforcement points and framework-level secret handling in documentation
- Handle malformed JSON in stop.sh hook with updated INPUT FORMAT docs
- Address PR #56 review comments
- Fix black formatting issues

### Added
- New research-agent for context isolation during research tasks

### BREAKING CHANGES

#### Hooks System Removed

The Claude Code hooks system has been completely removed from MAP Framework.

**Rationale:**
- Hooks added complexity without proportional value
- Core MAP workflows (`/map-efficient`, `/map-debug`, `/map-fast`) operate independently of hooks
- Maintenance burden outweighed benefits

**What was removed:**
- `.claude/hooks/` directory (13 hook scripts)
- `src/mapify_cli/__init__.py` functions: `load_settings_with_merge()`, `merge_hooks_settings()`, `install_hooks()`
- `src/mapify_cli/templates/hooks/` directory
- CLI option: `--with-hooks/--no-hooks` from `mapify init`
- 59 test cases (test_hooks_*.py, test_init_merge.py, test_inject_playbook_bullets.py)

**Migration guide:**

For existing projects with hooks installed:

1. **Hooks are now user-managed** - The `.claude/hooks/` directory (if present) will be ignored by MAP Framework
2. **No action required** - Your existing hooks will continue to work as Claude Code hooks
3. **Optional cleanup** - You can safely remove `.claude/hooks/` if you don't use custom hooks

**What continues to work:**
- ✅ All MAP workflows (`/map-efficient`, `/map-debug`, `/map-fast`, `/map-learn`, `/map-release`, `/map-review`)
- ✅ Agent orchestration via Task tool
- ✅ Pattern management via mem0 MCP tools (`mcp__mem0__map_tiered_search`, `mcp__mem0__map_add_pattern`, etc.)
- ✅ MCP server integration (context7, deepwiki, etc.)

**What no longer works:**
- ❌ `mapify init --with-hooks` / `--no-hooks` options (removed from CLI)
- ❌ Automatic hooks installation via `mapify init`
- ❌ Hooks template synchronization

**Upgrade path:**

```bash
# Upgrade MAP Framework to v2.0.0
uv tool upgrade mapify-cli

# (Optional) Remove hooks directory if you don't use custom hooks
rm -rf .claude/hooks/
```

## [1.7.0] - 2025-12-08

### Added
- **Optional Learning Command**: Added `/map-learn` command for optional post-workflow learning. Reflector and Curator agents are now invoked on-demand rather than automatically in workflows (cdc7e4e)
- **Auto-Approval Permissions**: `mapify init` now configures auto-approval rules for common readonly operations (tracker queries, sequential-thinking) to reduce permission prompts (18f9532)

### Changed
- **Workflow Simplification**: Removed unused workflow commands (`/map-feature`, `/map-refactor`) to reduce maintenance burden. Use `/map-efficient` for feature work (cdc7e4e)
- **Permissions Merge**: Settings permissions now use additive merge strategy to preserve user-defined rules (b585173, 1978af8)

### Fixed
- **Map-Review Command**: Restored `/map-review` command that was accidentally removed and updated stale agent references (1394935)
- **Stop Hook**: Restored malformed JSON handling in `stop.sh` quality gates hook for robustness (41b96c9)
- **README Accuracy**: Updated README to reflect actual available commands, fixed playbook bullet ID generation for consistent identifiers (af2d5d3)
- **Documentation Consistency**: Fixed Next Steps sections across commands to show actual available commands (c0a257d)
- **Map-Learn References**: Removed stale references to deleted commands in `/map-learn` template (3fcf8fc)
- **Agent Instructions**: Removed misleading 'orchestrator directly' instruction from agent templates (ea75b21)
- **Type Safety**: Resolved 39 mypy type errors across 11 files, improving code quality (fe474dd)

### Removed
- **Recitation Functionality**: Removed `mapify recitation` commands and related functionality. This feature was underutilized and added maintenance complexity (a1be4f8)
- **MCP Server: codex-bridge**: Removed codex-bridge MCP server from the framework (7a7e363)
  - Removed from `INDIVIDUAL_MCP_SERVERS` constant
  - Removed from agent template generators (actor, predictor)
  - Removed from `agent_mcp_mappings` configuration
  - Updated all agent templates to remove codex-bridge references
  - Updated documentation (README, ARCHITECTURE, presentations)
  - Updated `.mcp.json.example` and plugin configuration
  - Updated tests to expect 5 MCP servers instead of 6
  - **Rationale**: Simplify MCP server dependencies; codex-bridge functionality can be achieved through other tools

## [1.6.2] - 2025-11-29

### Fixed
- **MAP Efficient Workflow**: Fixed incorrect `subagent_type` parameters in `/map-efficient` command template. Changed from deprecated `type` parameter to correct `subagent_type` for all Task tool invocations (reflector, curator, monitor, predictor, evaluator) (e05793a)

## [1.6.1] - 2025-11-28

### Fixed
- **Playbook Migration**: Fixed migration from `playbook.json` to `playbook.db` when using `mapify init --force`. The migration now properly detects and removes invalid/incomplete `playbook.db` files before attempting migration, and cleans up stale `playbook.json` files after successful migration (7cfa82e)
- **Playbook References**: Removed all `playbook.json` references from codebase (except CHANGELOG history). Updated CLAUDE.md, agent templates, skills, and documentation to reference `playbook.db` only. Added clarifying comments to migration code and tests (fbe6bd3)

## [1.6.0] - 2025-11-27

### Changed
- **Agent Model Upgrades**: Upgraded `predictor.md` and `evaluator.md` from `haiku` to `sonnet` model
  - **Predictor** (v2.4.0 → v3.3.0): Impact analysis now uses sonnet for complex reasoning
  - **Evaluator** (v2.4.0 → v3.0.0): Quality evaluation now uses sonnet for nuanced judgment
  - **Cost Impact**: ~12x increase per agent call ($0.25→$3/1M input tokens, $1.25→$15/1M output tokens)
  - **Per-workflow impact**: ~$0.03 → ~$0.36 for typical 4-subtask feature
  - **Mitigation**: Use `/map-efficient` workflow (conditional Predictor, 30-40% token savings)
  - **Rationale**: Better analysis quality justifies cost for production code

- **Agent Template Rewrites**: Major rewrites of all 8 agent templates with LLM Council validation
  - **actor.md** (v2.5.0 → v3.1.0): Added Quick Reference box, enhanced MCP integration
  - **monitor.md** (v2.5.0 → v2.9.0): Added execution workflow, template configuration
  - **predictor.md** (v2.4.0 → v3.3.0): Added input schema, tool definitions, MAP integration
  - **evaluator.md** (v2.4.0 → v3.0.0): New Six-Dimensional Quality Model, score calibration
  - **curator.md** (v2.3.0 → v3.1.0): Simplified execution flow, canonical JSON shape
  - **reflector.md** (v2.5.0 → v3.0.0): Quick start paths, framework execution order
  - **task-decomposer.md**: Major rewrite with enhanced complexity scoring
  - **documentation-reviewer.md** (v3.0.0 → v3.1.0): Improved review workflow

### Removed
- **Agent Documentation Files**: Removed `.claude/agents/CHANGELOG.md`, `MCP-PATTERNS.md`, `README.md`
  - Version info now in agent frontmatter (`version:`, `last_updated:`)
  - MCP patterns consolidated into individual agents

## [1.5.0] - 2025-11-14

### Added
- **Non-Interactive Init**: `mapify init` now defaults to non-interactive mode, installing all MCP servers without prompts for better CI/CD compatibility (1ad6dd6)
- **Agent MCP Integration**: Integrated MCP tools across all 8 MAP agents (task-decomposer, actor, monitor, predictor, evaluator, reflector, curator, documentation-reviewer) for enhanced knowledge management and reasoning capabilities (aaded8a)
- **Release Validation**: Added CHANGELOG completeness validation to Gate 12 in release workflow, preventing releases with incomplete documentation (6541511)

### Changed
- **Playbook Migration**: Migrated all playbook.json references to playbook.db SQLite format throughout codebase, agents, documentation, and configuration (0332cdf)
- **Agent Optimization**: Optimized actor.md template for better performance and fixed variable inconsistency (2bc4b52)
- **Cleanup**: Removed unused files to reduce repository size (09a5b4d)

### Fixed
- **Pre-Release Validation**: Fixed undefined click references in init command, removed unused test variables, and resolved test isolation issue (f5cdb17)
- **Documentation**: Corrected commands in docs to use playbook.json after export (not playbook.db) (0c9fb38)
- **Documentation**: Fixed swapped filenames in playbook mistake example (5bfca90)
- **Playbook Error**: Corrected error message for playbook.json migration failure (4834574)
- **Agent Quality**: Addressed Copilot reviewer feedback improving code maintainability (c5a7dcc)

### Documentation
- **Playbook Access**: Updated documentation to use mapify CLI commands instead of Python API for playbook operations (ac56459)

## [1.4.0] - 2025-11-11

### Changed
- **Agent Optimization**: Optimized MAP agent prompts with stable prefix positioning and concrete quality rubrics for more consistent output (d5b76b0)
- **Agent Efficiency**: Reduced Reflector agent template size by 61.2% (from 5.3KB to 2.0KB) to mitigate token-induced brevity bias while maintaining functionality (2cadcbb)

### Fixed
- **Release Automation**: Fixed `bump-version.sh` script to automatically update `__version__` in `src/mapify_cli/__init__.py`. This prevents version mismatch between package metadata (pyproject.toml) and runtime version display (`mapify --version`).
- **Release Workflow**: Added critical verification step in `.claude/commands/map-release.md` to check `__version__` matches before pushing tags, preventing PyPI packages with incorrect version strings.
- **Code Quality**: Addressed 7 Copilot review comments improving code maintainability and type safety (620c1aa)

## [1.3.2] - 2025-11-07

### Fixed
- **PyPI Package Version**: Fix v1.3.1 PyPI package which was built before final commit amendment, resulting in package containing `__version__ = "1.3.0"` instead of "1.3.1". The v1.3.1 git tag points to correct code, but the PyPI package was built from an earlier state. This release ensures PyPI package matches git tag.

## [1.3.1] - 2025-11-07

### Fixed
- **Version Display**: Updated `__version__` in `__init__.py` to match package version (1.3.0). Previous release v1.3.0 had mismatched versions: pyproject.toml showed 1.3.0 but `mapify --version` displayed 1.0.4 due to missed update in bump-version.sh script.

## [1.3.0] - 2025-11-07

### Added

- **CLI Validation and Agent Guidance** (f8ce250, 0c71566)
  - Added MAP CLI reference skill for correcting mapify command errors
  - Documented actual CLI structure in machine-readable format
  - Updated Actor, Reflector, and Curator agent templates with CLI guidance
  - Added E2E tests for CLI command correctness validation
  - Updated documentation with CLI best practices

- **Claude Code Hooks Integration** (1ffedbc, d27bfb9, ba43d1b)
  - Integrated claude-code-prompt-improver with sequential hooks
  - Use CLAUDE_PROJECT_DIR for absolute hook paths
  - Added git hooks testing to CI pipeline

### Fixed

- **Code Quality and Linting** (251e5dd, 5b166d3, ce41dde)
  - Applied black formatting to 53 Python files for consistent code style
  - Fixed 38 ruff linting issues (removed unused imports, f-string prefixes, unused variables)
  - Added missing datetime import in CLI module
  - Resolved unittest.mock import issues in tests
  - Added noqa comments for intentional unused variables in test fixtures

- **Hooks System Improvements** (2f91b05, d35c954, ae22179, 67fdc49)
  - Removed redundant PreToolUse hook for template validation (d0c4d88, c35c12d)
  - Resolved JSON parsing errors in Claude Code hooks (manual JSON → jq-based generation)
  - Separated stdout/stderr in E2E tests for proper JSON parsing
  - Preserved user settings during hooks installation (merge strategy)

- **mapify init Command Fixes** (1aee890, 7d264ef, 956ef96)
  - Fixed mapify init to copy Python hooks and hook-enabled `.claude/settings.json` correctly
  - Corrected settings file location (.claude/ not .claude/hooks/)
  - Restored SessionStart hook functionality

- **Documentation Corrections** (d998100, cc572b0, 62f4626, 3b8b492, b62bea7, 5e5ee62)
  - Fixed Claude Desktop → Claude Code references in documentation
  - Addressed Copilot review comments across multiple PRs
  - Aligned with official Claude Code hooks documentation

### Changed

- **Documentation Organization** (1b8846e, 841c2d3)
  - Replaced programming-focused prompts with MAP Framework system prompt
  - Removed redundant hooks-json-parsing-errors.md documentation

### Removed

- **Cleanup** (cd93cfe, 4c0602b, cf0573c)
  - Removed obsolete example files and curator outputs
  - Removed generated curator_output.json file

## [1.2.3] - 2025-11-05

### Added

**P0 Improvement - Quality Checklist for Actor Agent (R1):**
- **Added Quality Checklist section to Actor agent template** (Implementation Plan P0 R1)
  - **New section**: 10-item self-review checklist following Claude Code "Rule of 10" pattern
  - **Location**: Inserted after `</examples>` section (line 1102-1142) in `.claude/agents/actor.md`
  - **Template variables**: Integrated `{{standards_url}}` for dynamic style guide reference
  - **Checklist items cover**:
    1. Code style compliance ({{standards_url}})
    2. Explicit error handling (no silent failures)
    3. Security review (SQL injection, XSS, sensitive data logging)
    4. Test case identification (happy path + edge cases)
    5. MCP tools usage (mem0, context7)
    6. Template variable preservation (orchestration compatibility)
    7. Trade-offs documentation
    8. Playbook bullet tracking (ACE feedback loop)
    9. Complete implementations (no ellipsis)
    10. Dependency justification
  - **Updated Critical Reminders**: Added reference to Quality Checklist at line 1148-1149
  - **Synchronized**: Template copied to `src/mapify_cli/templates/agents/actor.md`
  - **Expected impact**: 30-40% reduction in Monitor iteration cycles (from 2-3 to 1 iteration)
  - **Rationale**: Enables Actor self-review before Monitor submission, catching common rejection reasons early
  - **Reference**: Based on analysis in `docs/map-framework-improvement-plan.md` (P0 R1) and `analysis/claude-code-subagent-structure-analysis.md`

## [1.2.2] - 2025-11-03

### Fixed

**CRITICAL: Template Synchronization Bugfix:**
- **Fixed `mapify init --force` deleting user's custom files** (Critical Bug)
  - **Problem**: `install_hooks()` used `shutil.rmtree()` to delete entire `.claude/hooks/helpers/` directory before copying templates, destroying all user's custom helper scripts
  - **Solution**: Changed to individual file copying with `shutil.copy2()` - only updates template files, preserves user files
  - **Impact**: Users can now safely run `mapify init --force` to update templates without losing their custom scripts
  - **Files affected**: `src/mapify_cli/__init__.py` (lines 1118-1140)
  - **Test coverage**: Added comprehensive regression test `test_init_force_preserves_user_files` in `tests/test_mapify_cli.py`
  - **Verified**: Test creates user files in `.claude/hooks/helpers/`, runs `--force`, confirms files still exist with original content
  - **Related fix**: Added `validate_checkpoint_file.py` to templates (was missing, causing deletion during `--force`)

## [1.2.1] - 2025-11-02

### Fixed

**Playbook Database Initialization:**
- **Fixed playbook.db initialization and migration from playbook.json** (PR #18)
  - `mapify init` now creates `playbook.db` instead of `playbook.json`
  - RecitationManager checks for `playbook.db` existence instead of deprecated `playbook.json`
  - Added backward compatibility: automatically migrates data from `playbook.json` to `playbook.db` if old file exists
  - Updated all tests to use `--mcp none` flag for isolated testing
  - Fixed test assertions for corrupted JSON handling
  - **Impact**: Seamless migration for existing users, no data loss

### Removed

**Agent Framework Cleanup:**
- **Removed test-generator agent** from MAP Framework (reduced from 9 to 8 core agents)
  - Deleted `src/mapify_cli/templates/agents/test-generator.md` (1,175 lines)
  - Removed test-generator from `mcp_config.json` agent_mcp_mappings
  - Removed test-generator creation function from `src/mapify_cli/__init__.py`
  - Updated all documentation references from 9 agents to 8 agents
  - **Rationale**: Test generation responsibility shifted to Actor agent (which has codex-bridge access)
  - **Impact**: Zero breaking changes for existing users; orphaned files are harmless

### Changed

**Documentation Updates:**
- Updated `docs/IMPROVEMENT-STATUS.md` to reflect 8-agent architecture
  - Removed test-generator statistics from agent metrics
  - Recalculated totals: 2,354 → 7,841 lines (+233% growth)
- Updated presentation files (English and Russian) to show correct agent count
- Updated `tests/test_mapify_cli.py` to expect 8 agents

## [1.2.0] - 2025-10-30

### Added

**Compaction Recovery System:**
- **`mapify recitation checkpoint` CLI Command**: Displays state file paths, current progress, and recovery instructions (PR #15)
  - Shows absolute paths to all state files (.map/current_plan.json, .map/current_plan.md)
  - Displays current task, progress (N/M subtasks), and active subtask
  - Prints file contents with intelligent truncation (>2000 chars)
  - Provides copy-paste recovery instructions for post-compaction scenarios
  - Handles missing files gracefully with actionable error messages
  - **Benefits**: Self-service recovery reduces support burden, zero work loss guaranteed

- **Phase 2: Automatic Context Restoration via SessionStart Hook** (PR #15)
  - Automatic restoration of MAP workflow context after Claude Code session compaction
  - Filesystem persistence via `.map/` directory ensures workflow state survives compaction
  - Seamless user experience: workflows resume automatically without manual intervention
  - **Benefits**: Eliminates manual recovery steps, maintains workflow continuity

- **Defensive Documentation in MAP Workflow Templates** (PR #15)
  - Alert boxes in all command templates warn users about compaction before it occurs
  - Provide 4-step recovery workflow with concrete commands
  - Updated templates: map-feature.md, map-efficient.md, map-debug.md, map-refactor.md
  - Synchronized to `src/mapify_cli/templates/commands/` (all ✅ in sync)
  - **Benefits**: Users know what to do when compaction occurs, reduces confusion

**Multi-language Quality Gates:** (PR #14)
- **Extended Stop Hook**: Quality gates now support Go, TypeScript, and Rust beyond Python
  - **Go** (.go): `go fmt` + `go vet` for formatting and static analysis
  - **TypeScript** (.ts, .tsx): `tsc --noEmit` for type checking
  - **Rust** (.rs): `rustc` syntax validation
  - Language detection via file extension-based routing
  - Graceful degradation: skips checks if language toolchain not installed
  - Non-blocking: always exits 0, shows warnings only
  - **Benefits**: Universal code quality enforcement for polyglot codebases

**Hooks System Enhancements:**
- Hooks templates synchronized to `src/mapify_cli/templates/hooks/` for `mapify init`
- Implemented findings from Reddit post analysis (docs/reddit-analysis-improvements-CORRECTED.md)
- Enhanced hooks documentation and changelog

### Fixed

**FTS5 Query Engine:** (PR #16)
- **Resolved "no such column" SQL errors** for hyphenated queries in `mapify playbook query`
  - Root cause: FTS5 tokenizer splits hyphens at index time ("session-start" → ["session", "start"]), but queries preserved hyphens
  - Solution: Automatic hyphen-to-space conversion in `_build_fts_query` (playbook_manager.py:1012)
  - Fixed queries: "auto-activation" ✅, "session-start" ✅, "multi-subtask" ✅
  - Added 25 comprehensive regression tests covering hyphenated queries, edge cases, backward compatibility
  - Documented FTS5 query format guidelines in USAGE.md (383 lines)
  - **Benefits**: Playbook query now works reliably with natural hyphenated terms

**CLI Improvements:**
- Fixed `mapify init` not copying `helpers/` directory to `.claude/hooks/helpers/`
- Fixed 3 dataclass attribute access bugs in checkpoint command implementation
- Fixed size bomb test moved out of parametrize to avoid ARG_MAX limits
- Removed unused variables in tests (code review cleanup)

### Changed

**Documentation:**
- **USAGE.md**: Added "Handling Context Compaction" section (78 lines)
  - User-friendly explanation of compaction concept
  - Step-by-step recovery workflow with examples
  - Checkpoint command output format documentation

- **ARCHITECTURE.md**: Added "Compaction Resilience" section (101 lines)
  - Technical architecture with `.map/` directory diagram
  - Filesystem persistence mechanism details
  - Comparison table: conversation memory vs filesystem

**Playbook Growth:** 5 new patterns added
- **Recovery-Oriented CLI Design** (CLI_TOOL_PATTERNS - new section)
- **Dual-Documentation Pattern** (DOCUMENTATION_PATTERNS): Serve both user and developer audiences
- **Defensive Documentation in Templates** (DOCUMENTATION_PATTERNS): Warn users before problems occur
- **Filesystem-as-Resilience-Layer** (IMPLEMENTATION_PATTERNS): .map/ directory persistence strategy
- **Python Dataclass Attribute Access** (IMPLEMENTATION_PATTERNS): Best practices for dataclass usage

### Testing

- **All 386 tests passing** (no regressions from multi-language support)
- **25 new FTS5 query tests** covering hyphenated terms and edge cases
- Manual validation completed for multi-language quality gates (Go, TypeScript, Rust)
- Full test suite execution time: ~2 minutes

### Implementation Stats (PR #15)

- 8/8 subtasks completed (100% success rate)
- 8 total iterations (1 per subtask, zero rework)
- 179 lines of documentation added
- 95 lines of CLI implementation
- 68 lines of command template updates (4 files)

## [1.1.0] - 2025-10-29

## [1.1.0] - 2025-10-29

### Added
- **`mapify playbook apply-delta` CLI Command**: New command for applying Curator delta operations to playbook
  - Supports both file input and stdin (pipe-friendly for CI/CD)
  - `--dry-run` flag for preview without applying changes
  - `--verbose` flag for detailed operation logging
  - JSON output with operation results (added, updated, deprecated counts)
  - Comprehensive test suite with 19 tests (unit, CLI, integration)

### Changed
- **Complete SQLite Migration**: All playbook commands now use SQLite as source of truth
  - `playbook stats` now reads from SQLite backend (not JSON)
  - `playbook query`, `search`, `apply-delta`, `sync` all use SQLite
  - Automatic JSON → SQLite migration on first access
  - No breaking changes - JSON files still supported

- **Workflow Template Updates**: All MAP workflow templates now document CLI usage
  - `.claude/commands/map-feature.md` - Updated Step 1 and Step 3.10
  - `.claude/commands/map-efficient.md` - Same changes
  - `.claude/commands/map-debug.md` - Same changes
  - `.claude/agents/curator.md` - Documents apply-delta integration
  - All changes synced to `src/mapify_cli/templates/`

### Fixed
- **Unique ID Generation**: Fixed UNIQUE constraint failures in ADD operations
  - Changed from in-memory COUNT to SQLite MAX(id) + 1
  - Ensures IDs are always unique across concurrent operations

- **Test Compatibility**: Fixed `test_playbook_stats` to handle migration messages
  - Added JSON extraction logic for mixed output (migration messages + JSON)
  - All 315 tests passing on all platforms (Ubuntu + macOS, Python 3.11 + 3.12)

### Improved
- **Code Quality**: Addressed all Copilot code review feedback
  - Replaced magic numbers with named constants (QUALITY_SCORE_MAX, RELEVANCE_WEIGHT, QUALITY_WEIGHT)
  - Removed 7 unused imports across test files
  - Fixed comment typo (0.03 → 0.3) in quality score calculation

### Documentation
- **Updated USAGE.md**: Added examples for `mapify playbook apply-delta` command
- **Template Synchronization**: All .claude/ templates synced to src/mapify_cli/templates/

## [1.0.4] - 2025-10-27

### Added
- **Token-Optimized Workflow Variants**: Two new slash commands for token-conscious development
  - `/map-efficient` (⭐ RECOMMENDED): 30-40% token savings with full learning preservation
    - Batched Reflector/Curator execution (once at end vs per-subtask)
    - Conditional Predictor (only for high-risk subtasks)
    - Skips Evaluator (Monitor provides sufficient validation)
    - Maintains playbook updates and knowledge integration
  - `/map-fast` (⚠️ low-risk only): 40-50% token savings, no learning
    - Minimal agent sequence: TaskDecomposer → Actor → Monitor
    - Skips: Predictor, Evaluator, Reflector, Curator
    - Use only for small, low-risk changes with clear acceptance criteria

### Changed
- **Cleaner Command Templates**: Removed verbose marketing/educational content from slash commands
  - Commands now contain concise technical instructions only
  - Educational content preserved in README.md and docs/USAGE.md
  - Improved readability for Claude Code execution

### Fixed
- **Test Infrastructure**: Updated test suite to validate only canonical template sources
  - Tests now check `src/mapify_cli/templates/` (canonical source) instead of gitignored `.claude/` directory
  - Prevents CI failures due to missing generated files

### Documentation
- **Comprehensive Workflow Guide** (docs/USAGE.md): 220+ line guide for workflow selection
  - Decision flowchart for choosing between /map-feature, /map-efficient, /map-fast
  - Real-world token usage examples (small/medium/large tasks)
  - Cost analysis: $270/month savings for teams running 10 workflows/day
  - Migration guide and common misconceptions
- **Architecture Documentation** (docs/ARCHITECTURE.md): Technical details on workflow optimization
  - Conditional Predictor logic implementation
  - Batched learning algorithms
  - Token savings breakdown per optimization
- **Updated Development Instructions** (.claude/CLAUDE.md): Commands directory synchronization process

## [1.0.3] - 2025-10-27

## [1.0.2] - 2025-10-27

## [1.0.0] - 2025-10-26

### Added - PyPI Package Release Automation

#### Release Infrastructure
- **PyPI Distribution**: MAP Framework now available as `mapify-cli` on PyPI for easy installation via `pip install mapify-cli`
  - Version pinning support: Install specific versions using `mapify-cli==X.Y.Z` or version constraints (e.g., `~=1.0.0`, `>=1.0.0,<2.0.0`)
  - **Benefits**: Simple installation without git clone, reproducible builds with version pinning

- **Automated PyPI Publishing** (`.github/workflows/release.yml`): GitHub Actions workflow automatically publishes releases to PyPI using OIDC trusted publishing
  - Triggers on git tags matching `v*.*.*` pattern (semantic versioning)
  - Multi-gate validation: tag format verification, version consistency checks, artifact validation with twine
  - Deploy-what-you-test pattern: reuses CI build artifacts to ensure published package matches tested code
  - OIDC authentication: no manual API token management required
  - **Benefits**: Secure automated releases, reduced human error, consistent release process

- **Version Bumping Script** (`scripts/bump-version.sh`): Automated semantic versioning workflow (458 lines)
  - Updates `pyproject.toml` version field and moves `CHANGELOG.md` [Unreleased] section to versioned section
  - Creates conventional commit messages and annotated git tags with changelog excerpts
  - Multi-gate validation: semver format, duplicate tag detection, git working directory cleanliness, CHANGELOG.md structure
  - Cross-platform compatibility: handles both GNU sed (Linux) and BSD sed (macOS)
  - **Benefits**: Consistent versioning across files, automated changelog updates, prevents version conflicts

#### Documentation
- **Release Process Guide** (`RELEASING.md`): Comprehensive 350-line release documentation
  - Pre-release checklist covering code quality, documentation, dependencies, git state
  - Version bumping workflow with semantic versioning examples (major/minor/patch)
  - GitHub release creation commands and verification steps
  - Rollback procedures including PyPI yanking with blast radius documentation
  - PyPI OIDC trusted publishing setup instructions
  - Troubleshooting section for common issues
  - **Benefits**: Single source of truth for release process, reduced onboarding time for maintainers

- **README.md Installation Updates**: Restructured with PyPI as primary installation method
  - Progressive complexity design: simple (`pip install mapify-cli`) → intermediate (version pinning) → advanced (development install)
  - Version management section with links to PyPI package page and GitHub releases
  - Semantic versioning explanation for version constraint syntax
  - **Benefits**: Clearer installation path for end users, better segmentation of user types

- **Playbook Enhancements** (`.claude/playbook.json`): Added 11 new release automation patterns (64 → 75 bullets)
  - Security: PyPI OIDC trusted publishing, GitHub Actions least-privilege permissions
  - Implementation: Deploy-what-you-test pattern, multi-gate validation, cross-platform sed compatibility
  - Documentation: Executable documentation, single source of truth derivation, temporal risk management, progressive complexity

### Changed

- **Installation Priority**: README.md now recommends PyPI installation as primary method, with GitHub installation as alternative for development work
- **Release Process**: Maintainers use automated workflows (`release.yml`) and scripts (`bump-version.sh`) instead of manual version updates

### Changed - Documentation Structure Reorganization

#### Repository Documentation Organization
- **Moved user-facing documentation to `docs/`**: INSTALL.md, USAGE.md, ARCHITECTURE.md, SEMANTIC_SEARCH_SETUP.md, IMPROVEMENT-STATUS.md
- **Moved research materials to `docs/research/`**: Research PDFs (map.pdf, context-engenering.pdf, 2510.04618v1.pdf) and analysis documents (opus-4.1-thinking.md, sonnet-4.5.md, prompt-improvement-analysis.md)
- **Updated 25 documentation link references** across README.md and docs/ files
- **Git history fully preserved** using `git mv` for all moved files
- **Zero breaking changes**: Documentation only, no code dependencies affected

**Benefits:**
- Decluttered repository root (11 docs → 2: README.md, CHANGELOG.md)
- Clear hierarchical navigation by audience (users → docs/, researchers → docs/research/)
- Professional appearance improves project credibility
- Scalable structure accommodates growth without re-cluttering
- Improved first impressions and onboarding experience

**Quality Improvement:** Overall score 8.4/10 (Modularity: 10/10, Readability: 9/10, Complexity: 9/10, Maintainability: 8/10)

### Added - CLI Tool Development Improvements

#### Enhanced MAP Agents for CLI Development
- **Monitor Agent** (v2.3.0): Added comprehensive CLI Tool Validation section (### 6)
  - Manual execution test checklist
  - Output stream validation (stdout/stderr separation)
  - Library version compatibility checks
  - Integration testing requirements
  - Common CLI issues and solutions with examples
  - **Benefits**: Catches stdout pollution, version incompatibility, CliRunner vs real CLI mismatches

- **Predictor Agent** (v2.3.0): Added CLI Tool Specific Risks section
  - HIGH risk: Library parameter availability in minimum version
  - HIGH risk: Diagnostic messages printing to stdout instead of stderr
  - HIGH risk: CLI output format changes breaking user scripts
  - MEDIUM risk: Environment variable and error message location changes
  - Real-world example from mapify CLI subcommands implementation
  - **Benefits**: Proactively identifies CLI-specific risks before implementation

- **Reflector Agent** (v2.3.0): Added CLI Tool Pattern Recognition
  - New pattern type: `CLI_TOOL_PATTERNS` section
  - Recognition signals: output pollution, version incompatibility, stream handling
  - CLI Reflection Template: what test missed, manual verification needed
  - Pattern extraction for reusable CLI lessons
  - **Benefits**: Systematically captures CLI development lessons

#### Playbook Schema Enhancement
- **CLI_TOOL_PATTERNS Section**: New playbook section for CLI development patterns
  - 10 playbook sections (was 9)
  - Captures lessons about output streams, version compatibility, testing methodology
  - Enables pattern reuse across CLI implementations
  - **Benefits**: Institutional memory for CLI development

#### Documentation
- **CLI Testing Guide** (`docs/CLI_TESTING_GUIDE.md`): Comprehensive 400+ line guide
  - Output stream management (stdout for output, stderr for diagnostics)
  - Version compatibility patterns and detection
  - Integration testing workflows (CliRunner vs subprocess)
  - Common pitfalls with real-world examples
  - Best practices checklist and testing workflow
  - **Benefits**: Single source of truth for CLI testing best practices

### Changed
- **playbook_manager.py**: Updated sections_count from 9 to 10

### Context
These improvements were extracted from lessons learned during implementation of mapify CLI subcommands (PR #6), where we discovered:
1. SemanticSearchEngine printed to stdout, polluting JSON output
2. `CliRunner(mix_stderr=False)` parameter unavailable in CI's older Click version
3. Tests passed with CliRunner but real CLI had issues
4. Manual testing required to catch output pollution

These patterns are now captured in MAP framework to prevent similar issues in future CLI development.

## [2.2.0] - 2025-10-18

### Added - Phase 1 Context Engineering Complete ✅

#### Phase 1.1: Recitation Pattern (RecitationManager)
- **RecitationManager** (`src/mapify_cli/recitation_manager.py`, 543 lines): CLI-based workflow plan management
  - Implements "Recitation" pattern from context engineering research
  - Creates `.map/current_plan.md` with visual progress markers (✓, →, ☐, ✗)
  - Tracks subtask status and error history for retry awareness
  - Integration via `/map-feature` workflow (steps 2.5, 3.1.5, 3.4, 3.7, 4.6)
  - Actor template receives `{{plan_context}}` variable for goal focus
  - **Benefits**: Prevents focus drift on long workflows, +20-30% success rate on complex tasks

#### Phase 1.2: Workflow Logging (MapWorkflowLogger)
- **MapWorkflowLogger** (`src/mapify_cli/workflow_logger.py`, 411 lines): Optional JSON Lines workflow logging
  - Tracks workflow events: workflow_start/end, agent_call, tool_use, recitation_created/updated, error
  - JSON Lines format for easy parsing and analysis
  - Task ID correlation across events for debugging
  - Optional enable/disable flag (no-op when disabled for zero overhead)
  - Logs stored in `.map/logs/workflow_<TASK_ID>.log`
  - **Benefits**: Full workflow observability, debugging aid, performance analysis

#### Phase 1.3: Playbook Pattern Limit
- **Top-K Configuration** (`.claude/playbook.json`): `top_k=5` to limit playbook pattern retrieval
  - Prevents context distraction by returning only 5 most relevant patterns
  - Reduces token usage in playbook context by ~50%
  - Improves Actor focus on truly relevant patterns
  - Scalable as playbook grows beyond current 11 bullets
  - **Benefits**: Better pattern matching, reduced cognitive load, improved signal-to-noise ratio

#### Phase 1.4: Template Optimization
- **Monitor Template** (`.claude/agents/monitor.md`): 1006 → 909 lines (-97 lines, 9.6% reduction)
  - Compressed MCP Integration, Documentation Consistency, Examples
  - Preserved critical sections: Security Checklist, Severity Guidelines, Decision Rules
  - Validation: scored 9.7/10 by Evaluator
- **Evaluator Template** (`.claude/agents/evaluator.md`): 934 → 844 lines (-90 lines, 9.6% reduction)
  - Balanced optimization with teaching quality preservation
  - Partial rollback: restored Example 1 full code (52 lines) for pedagogical value
  - Preserved 6-Dimensional Scoring Model, Weighted Calculation, Decision Tree
  - Validation: scored Monitor optimization 9.7/10
- **Total savings**: 187 lines (~750 tokens per Monitor+Evaluator call)

#### Documentation
- `docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md`: Complete planning document for Phases 1-4
- `docs/PHASE-1-COMPLETION-SUMMARY.md`: Phase 1 results with metrics, architecture, troubleshooting, Phase 2 roadmap
- `docs/RECITATION-INTEGRATION-VERIFICATION.md`: Detailed verification report for RecitationManager integration
- Updated `README.md` Context Engineering section with Phase 1 completion status

### Changed - Phase 1

- **Playbook Growth**: 3 → 11 bullets (+8 new patterns, 267% growth)
  - arch-0001: Workflow-Scoped Learning Context Architecture
  - arch-0002: Analysis-Implementation Pipeline Pattern
  - impl-0001: Multi-Agent Workflow Documentation
  - impl-0002: Inter-Subtask Learning Propagation
  - impl-0003: Executable Specification for Code Transformations
  - impl-0004: Bounded Optimization Specifications
  - qual-0001: Analysis Document Completeness (WHAT/WHERE/HOW/WHY)
  - qual-0002: Template Purpose Classification (teaching vs validation)
  - test-0001: Iterative Refinement Based on Monitor Feedback
  - test-0002: Iteration Count as Learning Effectiveness Metric
  - test-0003: Over-Delivery Pattern Recognition

- **Architecture**: Documentation-driven orchestration pattern
  - Claude Code executes `/map-feature` workflow steps
  - RecitationManager and MapWorkflowLogger called via CLI at specific workflow points
  - No Python orchestrator class (human-in-the-loop design)

### Fixed

- Agent template optimizations preserve quality while reducing token usage
- Playbook retrieval limited to prevent context overload

### Migration Notes

**Backward Compatible**: Phase 1 is fully additive with no breaking changes.

**New Dependencies**: None (uses existing Python stdlib)

**New Directories**:
- `.map/` - RecitationManager state files (auto-created, gitignored)
  - `.map/current_plan.json` - Machine-readable workflow state
  - `.map/current_plan.md` - Human-readable plan context
  - `.map/logs/` - Optional workflow logs (MapWorkflowLogger)

**Configuration Updates**:
- `.claude/playbook.json`: Added `metadata.top_k = 5` for pattern limit
- No changes required for existing workflows to continue working

**To Upgrade**:
```bash
# Pull latest code
git pull origin main

# Verify Phase 1 components
ls -l src/mapify_cli/recitation_manager.py  # 482 lines
ls -l src/mapify_cli/workflow_logger.py     # 246 lines

# Create .map directory structure
mkdir -p .map/logs

# Update playbook config (if needed)
jq '.metadata.top_k = 5' .claude/playbook.json > tmp.json && mv tmp.json .claude/playbook.json

# Test RecitationManager
python -m mapify_cli.recitation_manager create "test" "Test goal" '[{"id": 1, "description": "Test"}]'
python -m mapify_cli.recitation_manager clear
```

### Performance Metrics - Phase 1

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Token Efficiency | Baseline | 9.6% reduction | -187 lines (Monitor + Evaluator) |
| Playbook Patterns | 3 bullets | 11 bullets | +267% growth |
| Context Focus | No recitation | Active | Progress markers + error history |
| Observability | No logging | JSON Lines logs | Optional .map/logs/ |
| Pattern Retrieval | Unlimited | Top-5 limit | 50% context reduction |
| Infrastructure | Baseline | +728 lines | RecitationManager (482) + MapWorkflowLogger (246) |

### Research Foundation

Phase 1 based on:
- **"Context Engineering for AI Agents: Lessons from Building Manus"** (Y. Ji, Manus.im, 2025)
  - Recitation pattern (keep goals fresh in context)
  - KV-cache optimization principles
  - External memory as context extension
- **MAP Framework ACE System**
  - Reflector/Curator workflow-to-playbook learning
  - Semantic search with embeddings
  - Multi-agent orchestration

### Next Steps - Phase 2 Roadmap

**Priority 1: Checkpoints (Phase 2.1)** - HIGH IMPACT
- MapStateManager for workflow resumption
- Integration with RecitationManager
- Timeline: 2-3 weeks

**Priority 2: MCP Caching (Phase 2.2)** - MEDIUM-HIGH IMPACT
- MCPCacheManager for context7/deepwiki
- Latency reduction: 50-80%
- Timeline: 1-2 weeks

**Priority 3: Keyword+Semantic Search (Phase 2.4)** - MEDIUM IMPACT
- Enhanced PlaybookManager retrieval
- Improved pattern relevance
- Timeline: 1-2 weeks

**Priority 4: Playbook Variation (Phase 2.3)** - LOW-MEDIUM IMPACT
- Pattern reformulation to reduce few-shot bias
- Timeline: 2-3 weeks

**Total Phase 2 Timeline**: ~10 weeks (2.5 months)

---

## [2.1.0] - 2025-10-18

### Changed - Agent Templates

See [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md) for detailed agent template changes.

**Summary:**
- Actor v2.1.0: Added Recitation Pattern integration (`{{plan_context}}`)
- Monitor v2.1.0: Optimized for 9.6% token reduction
- Evaluator v2.1.0: Optimized for 9.6% token reduction with teaching quality preservation

---

## [2.0.0] - 2025-10-17

### Added - Agent Templates Overhaul

See [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md) for complete v2.0.0 changes.

**Summary:**
- Comprehensive MCP integration framework
- XML-style semantic structure for better LLM parsing
- Template size: 2,232 → 9,269 lines (+258% for comprehensive guidance)
- Removed orchestrator as subagent (moved to slash commands)

---

For older changes and agent template details, see:
- [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md)
- Git commit history

## Versioning

**Version Format**: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes (incompatible API/workflow changes)
- **MINOR**: New features (backward compatible additions like Phase 1)
- **PATCH**: Bug fixes and minor improvements

**Current Version**: 2.2.0 (Phase 1 Context Engineering Complete)
