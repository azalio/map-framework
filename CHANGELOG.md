# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
