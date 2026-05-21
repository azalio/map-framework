## 2026-05-20 - Clean-room retry and context quarantine for failed agent iterations [2605.08563]

- Decision: `implemented`
- Branch: `codex/2605-08563-clean-retry`
- Baseline: `/map-efficient`, `/map-task`, and `/map-debug` carried Monitor feedback forward through repeated Actor retries, while `run_health_report.json` only recorded retry counts. Repeated failures could therefore reuse rejected implementation momentum without a durable clean-room boundary.
- Forward Change: Repeated Monitor rejection now marks `clean_retry_required`, writes `.map/<branch>/retry_quarantine.json`, validates the quarantine artifact before the next clean Actor attempt, updates run-health clean vs ordinary retry counters, and surfaces quarantine paths during `/map-resume`.
- Decisive Validation: Focused retry, run-health, schema, and template-sync tests cover serial retry, wave retry, quarantine validation, and generated template parity. Generated-project smoke exercised installed `.map/scripts/map_orchestrator.py` and `.map/scripts/map_step_runner.py`, validated `retry_quarantine.json`, wrote `run_health_report.json`, and inspected clean-retry counters plus artifact presence.
- Next Trigger: Reuse this when changing Actor->Monitor retry behavior, retry counters, resume diagnostics, or any workflow prompt that tells Actor to retry after validation failure.
- Reusable Learnings:
  - command: `pytest tests/test_map_orchestrator.py::TestMonitorFailed tests/test_map_orchestrator.py::TestWaveMonitorFailed tests/test_map_step_runner.py::test_build_retry_quarantine_writes_valid_artifact tests/test_artifact_schemas.py::test_validate_retry_quarantine_schema tests/test_template_sync.py -v`
  - invariant: `After the second Monitor rejection for a subtask, the next Actor attempt must use clean retry context from retry_quarantine.json instead of raw failed-session context.`
  - review-check: `When adding retry isolation fields, verify step_state.json, retry_quarantine.json, run_health_report.json, shipped skills, templates, schemas, and resume briefing stay aligned.`

## 2026-05-20 - Compact `/map-resume` Recovery Skill Body [2604.033-1]

- Decision: `implemented`
- Branch: `codex/2604-033-resume-skill-lifecycle`
- Baseline: Claude Code's official skill docs say invoked skill content stays in context and recommend concise `SKILL.md` bodies with supporting files; `/map-resume` is specifically used after context exhaustion, but its active body still carried 504 lines including low-frequency examples, state-file examples, token-budget notes, and troubleshooting.
- External Docs: Claude Code skills docs, https://docs.anthropic.com/en/docs/claude-code/skills, accessed 2026-05-20; applied rules: invoked skill content stays in context, compaction reattaches recent skill invocations within a limited token budget, supporting files should hold detailed reference material, and `SKILL.md` should stay focused.
- Forward Change: Moved the low-frequency material into `.claude/skills/map-resume/resume-reference.md`, kept the active recovery path in `SKILL.md`, synced the template copy, updated docs, and split the parent plan into future high-traffic workflow playbook and retained-body lint slices.
- Decisive Validation: Focused skill lifecycle regression checks both source and template copies for the compact `/map-resume` body and supporting reference. Generated-project smoke inspected installed `.claude/skills/map-resume/SKILL.md` and `resume-reference.md` so the installed recovery workflow matches the repo surface.
- Next Trigger: Reuse this when a task skill is invoked after compaction, `/clear`, or long-running workflow interruption and contains examples/troubleshooting that do not need to stay in the active body.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestSkillStructure::test_map_resume_keeps_recovery_skill_body_compact tests/test_template_sync.py -v`
  - invariant: `Recovery skills should keep the active SKILL.md body focused on checkpoint detection and next action; move low-frequency examples, state-shape references, token notes, and troubleshooting into bundled supporting files.`
  - review-check: `When externalizing skill content, verify local Markdown links resolve, supporting files are template-synced, and generated-project smokes inspect both the compact SKILL.md and the supporting file.`

## 2026-05-19 - Reviewer Prompt Budget Enforcement [2604.023-2]

- Decision: `implemented`
- Branch: `codex/2604-023-review-prompt-budget`
- Baseline: `/map-review` already persisted a primary review bundle and separated it from raw diff with XML prompt envelopes, but reviewer fan-out still asked the operator to paste unbounded bundle/diff text into each Monitor, Predictor, and Evaluator prompt.
- Forward Change: Added `build_review_prompts` to the runtime helper and shipped template copy, wired `/map-review` to call it before Task fan-out, kept the review bundle primary, clipped lower-priority raw diff first under `MAP_REVIEW_PROMPT_BUDGET_TOKENS`, and documented the review prompt budget boundary.
- Decisive Validation: Focused prompt-builder tests and a synthetic old/new reviewer A/B test prove oversized raw diffs are clipped while bundle evidence, XML envelope shape, reviewer instructions, and expected output contracts survive. A generated-project smoke ran the installed helper against an oversized review bundle plus real git diff and confirmed the prompt stayed under 1,500 estimated tokens with `git diff` clipped.
- Review Result: Inline diff review checked source/template sync, prompt-envelope preservation, review-bundle priority, docs/plan consistency, and the new CLI surface; no blocking issues remained before commit.
- Next Trigger: Reuse this learning whenever a MAP workflow fans out long branch artifacts into multiple reviewer or verifier prompts.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py build_review_prompts --budget-tokens 1500 --review-preferences "Flag correctness first."`
  - invariant: `/map-review` reviewer prompts must keep the persisted review bundle as primary context and clip raw diff before bundle text whenever prompt budgeting is required.
  - review-check: `For prompt-budget changes, include an old/new A/B test that proves the old prompt exceeds the target while the new prompt preserves task/instruction/output-contract sections under budget.`

## 2026-05-19 - Actor Context Block Token Budget Enforcement [2604.023-1]

- Decision: `implemented`
- Branch: `codex/2604-023-context-budget`
- Baseline: `build_context_block()` assembled current subtask, dependency results, plan overview, and repo delta as an unbounded string; long plans could silently crowd out the active Actor prompt even though MAP already exposed transcript-level compaction nudges.
- Forward Change: Added deterministic estimated-token helpers, enforced a default 4,000-token cap for generated Actor `<map_context>` blocks, prioritized current-subtask and dependency summaries over broad overview text, preserved valid XML shape with a truncation note, synced the template helper copy, and documented the `MAP_CONTEXT_BLOCK_BUDGET_TOKENS` override.
- Decisive Validation: Focused token-budget and context-block tests prove oversized multi-subtask contexts stay within the configured budget while preserving current-task and dependency evidence. Template sync verifies generated projects receive the runner change. Generated-project smoke and broader validation are recorded in the PR evidence.
- Review Result: Inline diff review checked source/template parity, current-context preservation, dependency-summary ordering, and docs/plan consistency; no blocking issue remained after reducing file-list caps so dependency summaries survive tight budgets.
- Next Trigger: Reuse this learning whenever a generated prompt helper assembles branch artifacts into a model-facing context block.
- Reusable Learnings:
  - command: `pytest tests/test_token_budget.py tests/test_map_step_runner.py::TestBuildContextBlock -v`
  - invariant: `Generated prompt context builders must preserve valid envelope shape and prioritize current-task/dependency evidence before broad plan overview when clipping to a budget.`
  - review-check: `When adding prompt budget enforcement, test the forced-truncation path with a small configured budget rather than only asserting normal-sized prompts still render.`

## 2026-05-19 - Clean-session TEST->CODE handoff for TDD workflows [2604.036]

- Decision: `rejected`
- Branch: `codex/2604-036-close-tdd-handoff`
- Baseline: The active plan still described split-session TDD as missing, but the current product already has targeted TDD red-phase handoff artifacts and `/map-task` resume behavior.
- Forward Change: Removed the stale active plan section and recorded the exact `[2604.036]` heading in `docs/improvement-done.md` with runtime, template, docs, roadmap, and regression-test evidence.
- Decisive Validation: Focused TDD handoff/resume tests and template sync passed; a repo-built generated-project smoke confirmed installed `/map-tdd` and `/map-task` expose the contract handoff and resume paths; `make lint` and `pytest -m "not slow"` passed; the idea indexer confirmed `2604.036` is now done-only. Full `pytest` was attempted and hit the cumulative live SDK boundary after surfacing transient plan/efficient results; the surfaced plan and efficient tests passed on rerun, the live SDK module passed through review E2E before its cumulative timeout, and the final full-flow boundary passed individually.
- Review Result: Inline diff review found no blocking issues; the diff is ledger-only, the roadmap already marks targeted TDD handoff as shipped, and the generated-project smoke supports the installed-user evidence claimed in the done entry.
- Next Trigger: Reuse this learning whenever an active plan item describes a workflow behavior already shipped in a targeted mode rather than the broad mode originally proposed.
- Reusable Learnings:
  - review-check: `Before implementing a broad workflow-mode item, inspect whether the highest-payoff targeted mode already shipped the promised user journey and close the stale parent with evidence instead of rebuilding it.`

## 2026-05-18 - Command-specific thinking and parallelism profiles [2604.029]

- Decision: `implemented`
- Branch: `codex/2604-029-effort-parallelism`
- Baseline: MAP task skills mixed direct, adaptive, and deep workflows without an explicit per-command effort contract, while `/map-review`, `/map-efficient`, and `/map-release` used different parallelism wording that could encourage over-triggering or unsafe fan-out.
- Forward Change: Added `thinking_policy` and `parallel_tool_policy` blocks to all shipped task skills, added matching execution policies to `workflow-rules.json` for triggered workflows, synced templates, documented the calibration in README/usage/architecture, and added tests that fail if source or shipped template skills lose the policy blocks.
- Decisive Validation: Focused skill policy tests, full `tests/test_skills.py tests/test_template_sync.py`, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke passed. Full `pytest` hit the live Claude SDK review boundary after prior live plan/efficient tests passed; the first boundary test passed separately in 7:01, and the subsequent full slow run was user-stopped while another live review test was still running.
- Review Result: Inline diff review found no blocking issues; the change is limited to prompt/template policy, docs, and regression tests, with no runtime state-machine semantics changed.
- Next Trigger: Reuse this learning whenever changing shipped MAP task skill orchestration wording, especially around reasoning depth, parallel fan-out, or command latency claims.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestSkillStructure::test_task_skills_have_effort_and_parallelism_policy tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every shipped task skill must declare an explicit thinking_policy and parallel_tool_policy in both .claude/skills and src/mapify_cli/templates/skills.`
  - review-check: `When adding or editing workflow parallelism wording, verify the policy allows only dependency-free, side-effect-safe fan-out and keeps state-machine transitions sequential.`

## 2026-05-18 - Prior-stage artifact consumption gates [2604.039-followup-3]

- Decision: `implemented`
- Branch: `codex/2604-039-prior-artifact-gates`
- Baseline: verification summaries and review bundles recorded artifact presence and acceptance coverage, but they did not explicitly state which prior-stage inputs were consumed before closeout, so maintainers still had to infer stage skipping from scattered files or chat history.
- Forward Change: Added `prior_stage_consumption` reporting for implementation and review closeout, including a nonzero `validate_prior_stage_consumption` CLI gate, Markdown rendering in verification summaries/review bundles, review manifest warn status for missing inputs, schema support, prompt guidance, synced templates, and user/architecture docs.
- Decisive Validation: Focused prior-stage helper/schema/template/skill tests passed, `make lint` passed, `pytest -m "not slow"` passed, and a repo-built generated-project smoke confirmed both implementation and review validators return `ready` when spec, task plan, blueprint, test contract, verification summary, and a real git diff are present.
- Review Result: Inline diff review checked the schema, generated-template sync, prompt docs, manifest status semantics, and test fixture drift; no blocking issues remained after updating legacy tests to expect `warn` when prior-stage inputs are missing.
- Next Trigger: Reuse this learning whenever adding a new branch-scoped closeout or review artifact that claims workflow readiness from prior-stage evidence.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption implementation`
  - command: `python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption review`
  - invariant: `Review bundles may still be generated with missing artifacts, but the review manifest must warn when required prior-stage inputs are missing.`
  - review-check: `When adding required fields to review-bundle schema, update source helper output, shipped template helper, schema fixtures, integration tests, docs, and generated-project smoke together.`

## 2026-05-18 - Acceptance coverage in review and verification artifacts [2604.039-followup-4]

- Decision: `implemented`
- Branch: `codex/2604-039-acceptance-coverage`
- Baseline: `blueprint.json` required bracketed acceptance and invariant tags in `validation_criteria`, but later verification and review artifacts did not summarize which tags were actually evidenced, so reviewers still had to grep branch artifacts manually.
- Forward Change: Added acceptance coverage reporting to verification summaries and review bundles, including machine-readable `acceptance_coverage`, Markdown rendering, review manifest metadata, and synced generated-project helper templates.
- Decisive Validation: Focused acceptance-coverage/review-bundle/schema tests passed, `make lint` and `pytest -m "not slow"` passed, and a repo-built generated-project smoke confirmed the shipped helper can report coverage from generated `.map/default` artifacts.
- Validation Boundary: Full unfiltered `pytest` was attempted and reached the live Claude SDK suite, then exceeded a 20-minute tool timeout at `TestMapEfficientE2E::test_efficient_produces_code_changes`; rerunning that single live boundary with a 30-minute tool timeout passed in 19:06.
- Review Result: The gstack `/review` checklist path was unavailable, so review continued as a repo-local diff review. It found no blocking issues and confirmed coverage sources are restricted to downstream artifacts that actually contain bracketed tags.
- Next Trigger: Reuse this learning whenever adding branch-scoped review, verification, or manifest fields derived from `blueprint.json` contracts.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py build_acceptance_coverage_report`
  - invariant: `Acceptance coverage is evidence-based: a coverage_map key is covered only when the bracketed tag appears in downstream verification, QA, test, handoff, PR draft, or review artifacts.`
  - review-check: `When adding review-bundle fields, update the runtime helper, shipped template copy, JSON schema, Markdown rendering, manifest metadata, docs, focused tests, and generated-project smoke together.`

## 2026-05-18 - Hard/soft constraint typing in spec and blueprint gates [2604.039-followup-2]

- Decision: `implemented`
- Branch: `codex/2604-039-hard-soft-constraints`
- Baseline: `blueprint.json` could trace acceptance criteria with `coverage_map`, but it did not distinguish requirements that must block progress from preferences that can be traded off, so reviewers still had to infer whether missing coverage was a hard failure or an intentional scope decision.
- Forward Change: Added `hard_constraints` and `soft_constraints` to schema, validator, Claude/Codex planner and decomposer surfaces, decomposition examples, generated templates, and user docs. The validator now fails missing hard-constraint coverage and fails soft constraints that are neither covered nor explained with `tradeoff_rationale`.
- Decisive Validation: Focused schema/validator/prompt/template-sync tests passed, and a repo-built `uv run --no-sync mapify init <new-dir> --no-git --mcp none` smoke confirmed the generated validator accepts covered hard constraints and exits nonzero for missing hard coverage plus unexplained soft tradeoff.
- Validation Boundary: `make lint` and `pytest -m "not slow"` passed. Full `pytest` reached live Claude SDK e2e and exceeded the 15-minute tool timeout at `TestMapEfficientE2E::test_efficient_produces_code_changes`; rerunning that single slow test with a 20-minute timeout also exceeded the limit without a deterministic assertion failure.
- Review Result: The gstack `/review` checklist path was unavailable at `~/.Codex/skills/review/checklist.md`, so review continued as a repo-local diff review. It found one non-blocking cleanup, an unused soft constraint id accumulator, which was removed and templates were resynced.
- Next Trigger: Reuse this learning whenever blueprint schema semantics change or prompt-generated plan fields become validation gates.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_blueprint_contract <path-to-blueprint.json>`
  - invariant: `Every hard_constraints id must be in coverage_map and cited as a bracketed validation_criteria tag; every uncovered soft_constraints id must include tradeoff_rationale.`
  - review-check: `When adding blueprint fields that prompts must emit, update schema, validator, Claude agents/skills, Codex agents/skills, decomposition examples, template copies, docs, and generated-project pass/fail smokes together.`

## 2026-05-18 - Acceptance-criteria lineage tags in blueprint validation [2604.039-followup-1]

- Decision: `implemented`
- Branch: `codex/2604-039-ac-lineage`
- Baseline: `coverage_map` assigned each acceptance criterion or invariant to an owner subtask, but the owning subtask's `validation_criteria` did not have to cite the requirement ID, so reviewers could still receive plans where ownership and executable checks were disconnected.
- Forward Change: Split the broad `2604.039-followup` parent into value-bearing child slices, then made `validate_blueprint_contract` fail untagged owner criteria, updated Claude/Codex planner and decomposer prompts, refreshed schema descriptions and docs, and kept source/template copies in sync.
- Decisive Validation: Focused validator/schema/prompt/template-sync tests passed, and a repo-built `uv run --no-sync mapify init <new-dir> --no-git --mcp none` smoke confirmed the generated validator accepts tagged blueprints and rejects untagged ones with a nonzero exit.
- Validation Boundary: `make lint` and `pytest -m "not slow"` passed. Full `pytest` was attempted and reached the live Claude SDK suite, then exceeded tool timeout at `TestMapPlanE2E::test_plan_creates_required_artifacts`; rerunning that single slow test with a 10-minute timeout also exceeded the limit without a deterministic assertion failure.
- Review Result: Diff review found no blocking issues; invalid coverage owners still fail before lineage checks, nested blueprint output remains supported, and source/template surfaces are synced.
- Next Trigger: Reuse this learning whenever extending blueprint, review-bundle, or verification artifacts with new traceability fields.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_blueprint_contract <path-to-blueprint.json>`
  - invariant: `Every coverage_map key must appear as a bracketed tag in the owning subtask's validation_criteria before implementation starts.`
  - review-check: `When changing decomposer contracts, update Claude agents, Codex agents, shipped templates, schema descriptions, docs, and generated-project smokes together.`

## 2026-05-17 - Generic JSON prompt-contract lint for future MAP skills [2604.027-1]

- Decision: `implemented`
- Branch: `codex/2604-027-json-contract-lint`
- Baseline: Evidence-first tests protected selected review/debug/plan prompts, but no generic scanner failed future MAP skill prompt sections that introduced `Output JSON with:` without evidence, quotes, or a reusable output contract.
- Forward Change: Added `map-json-output-contracts.md`, annotated existing non-evidence JSON output sections in `/map-fast`, `/map-debug`, and `/map-learn`, synced templates, documented the guardrail, and added fixtures plus a scanner over source and shipped template skills.
- Decisive Validation: Focused prompt-contract tests, template sync tests, generated-project `mapify init` smoke, `make lint`, and `pytest -m "not slow"` covered the source, template, and installed-project paths.
- Review Result: Diff review confirmed the shipped user/operator payoff is a maintainer-facing release guardrail, not another prompt-polish-only change.
- Next Trigger: Reuse this learning whenever adding or editing `Output JSON with:` prompt sections in MAP skills.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestEvidenceFirstPromptContracts tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every MAP skill prompt section containing Output JSON with: must either be evidence-first or cite .claude/references/map-json-output-contracts.md before listing fields.`
  - review-check: `Prompt-contract tests must scan both .claude/skills and src/mapify_cli/templates/skills so generated users get the same guardrail as the repo working set.`

## 2026-05-17 - LEARN as a philosophical requirement with soft runtime ergonomics [2604.035]

- Decision: `rejected`
- Branch: `codex/2604-035-close-learn-parent`
- Baseline: The parent item remained active in `docs/improvement-plan.md`, but its executable child slices `2604.035-1`, `2604.035-2`, and `2604.035-3` were already recorded as shipped and the runtime/docs evidence showed the soft-LEARN user payoff was live.
- Forward Change: Removed the stale active parent section and recorded the exact `[2604.035]` heading in `docs/improvement-done.md` with repo-grounded evidence instead of rebuilding the learning handoff, zero-argument `/map-learn`, metrics, or repeated-rule tracking behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused learning handoff regression tests, and repo evidence searches verified the parent is no longer active while shipped learning artifacts remain covered.
- Review Result: Diff review confirmed this is a ledger-only stale-parent closure with no runtime or template mutations.
- Next Trigger: Reuse this learning whenever an active umbrella item says to use child slices and all children are already shipped in `docs/*-done.md`.
- Reusable Learnings:
  - review-check: `Before selecting an active umbrella item, compare its proposed changes against shipped child slice ids in docs/*-done.md; if all value-bearing children are already complete, close the parent with evidence rather than executing it again.`

## 2026-05-17 - Detached reviewer context and worktree-assisted review [2604.037]

- Decision: `rejected`
- Branch: `codex/2604-037-close-detached-review-plan`
- Baseline: The idea remained active in `docs/improvement-plan.md`, but runtime, shipped template, docs, and tests showed `/map-review --detached` and the canonical review bundle had already shipped.
- Forward Change: Removed the stale active plan section, recorded the exact `[2604.037]` heading in `docs/improvement-done.md` with repo-grounded evidence, and changed `docs/roadmap.md` from open follow-up to shipped status instead of rebuilding existing behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused detached-review skill tests, focused `prepare_detached_review` tests, and a repo-built generated-project smoke verified the plan/done state and shipped review-isolation artifacts.
- Review Result: Diff review found `docs/roadmap.md` still listed `2604.037` as open; fixed by marking the review-independence iteration shipped and keeping contract-sized subtasks as the next active roadmap work.
- Next Trigger: Reuse this learning whenever an active plan item describes a workflow capability that may already be visible in skill prompts, generated templates, helper scripts, user docs, and focused regression tests.
- Reusable Learnings:
  - review-check: `Before implementing a review-workflow backlog item, inspect both the user-facing skill surface and generated template copy, then verify helper-script and focused-test coverage for the advertised flags/artifacts.`
  - review-check: `When closing stale plan items, reconcile secondary ledgers such as roadmap status tables, not only docs/improvement-plan.md and docs/improvement-done.md.`

## 2026-05-16 - Workflow fit classifier and explicit off-ramp for trivial work [2604.038]

- Decision: `rejected`
- Branch: `codex/2604-038-close-workflow-fit-plan`
- Baseline: The idea remained active in `docs/improvement-plan.md`, but runtime, schema, skill, docs, and test evidence showed workflow-fit routing had already shipped.
- Forward Change: Removed the stale active plan section and recorded the exact `[2604.038]` heading in `docs/improvement-done.md` with repo-grounded evidence instead of rebuilding existing behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused workflow-fit regression tests, template sync tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke verified the plan/done state and shipped off-ramp artifacts.
- Validation Boundary: Full `pytest` was attempted and progressed through deterministic tests plus the first three live Claude SDK checks, then exceeded the tool timeout at `TestMapEfficientE2E::test_efficient_produces_code_changes`; rerunning that single live SDK test also exceeded 15 minutes without a deterministic assertion failure.
- Review Result: Diff review confirmed the change is documentation/ledger-only and does not alter runtime behavior.
- Next Trigger: Reuse this learning whenever an active plan item references behavior already visible in runtime code, generated templates, docs, and tests.
- Reusable Learnings:
  - review-check: `Before implementing an active idea, inspect active and done headings, then search runtime, shipped templates, docs, and tests for the core artifact/route names; close stale plan entries instead of rebuilding shipped behavior.`

## 2026-05-16 - Health report analytics and CI assertions [2604.017-4]

- Decision: `implemented`
- Branch: `2604.017-4-health-report-validation`
- Baseline: `run_health_report.json` was written during workflow closeout, but teams had no deterministic command to fail inconsistent reports in CI or operator handoff.
- Forward Change: Added `validate_run_health_report` with schema checks when available plus built-in shape and semantic checks for generated projects, synced the shipped script template, documented the command, and added regressions for valid reports, complete-with-pending steps, missing verification evidence, retry overflow, unexplained hook degradation, invalid terminal status, and CLI non-zero exit.
- Decisive Validation: `pytest tests/test_map_step_runner.py::test_write_run_health_report_creates_report_and_manifest tests/test_map_step_runner.py::test_validate_run_health_report_accepts_valid_complete tests/test_map_step_runner.py::test_validate_run_health_report_rejects_inconsistent_complete tests/test_map_step_runner.py::test_validate_run_health_report_rejects_retry_and_hook_degradation tests/test_map_step_runner.py::test_validate_run_health_report_rejects_schema_drift_without_package_schema tests/test_map_step_runner.py::test_map_step_runner_cli_validate_run_health_report_exits_nonzero tests/test_template_sync.py -v`, `make lint`, `pytest -m "not slow"`, and generated-project pass/fail smoke passed.
- Validation Boundary: Full `pytest` and `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` were attempted, but live Claude SDK e2e timed out at `TestMapEfficientE2E::test_efficient_produces_code_changes`; no deterministic failure surfaced before the timeout.
- Review Result: Diff review found schema drift could pass when package schema/jsonschema was unavailable; fixed by adding built-in run-health shape checks and a regression that disables package schema loading.
- Next Trigger: Reuse this learning whenever adding generated-project validators that must fail CI without optional package dependencies.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_run_health_report [path]`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Generated-project validators must enforce critical schema shape locally, not only through optional package imports or optional jsonschema behavior.`
  - review-check: `When documenting a validator as CI-failing schema enforcement, test the dependency-unavailable path and at least one malformed-but-semantically-benign artifact.`

## 2026-05-16 - Expand hook degradation status coverage [2604.017-3]

- Decision: `implemented`
- Branch: `2604.017-3-hook-degradation-status`
- Baseline: The PreToolUse hook wrote `hook_injection` for emitted reminders and no-reminder formatting skips, but malformed hook input and insignificant Bash commands were silent when safe branch state existed.
- Forward Change: Added safe state reads with explicit degradation reasons, persisted skipped outcomes for malformed hook payloads and insignificant Bash commands when `step_state.json` is parseable, preserved non-blocking/no-clobber behavior for missing or invalid state, synced the shipped hook template, and documented the new diagnostic signal.
- Decisive Validation: `pytest tests/test_workflow_context_injector.py tests/test_template_sync.py -v`, `pytest tests/test_map_step_runner.py::test_write_run_health_report_creates_report_and_manifest tests/test_artifact_schemas.py::test_validate_run_health_report_schema -v`, `make lint`, `pytest -m "not slow"`, and generated-project `uv run --no-sync mapify init <new-dir> --no-git --mcp none` hook smokes passed.
- Review Result: Diff-scoped review found a malformed payload gap where non-string Bash commands could still raise; fixed by normalizing `tool_name` and `command` before classification and added a regression test.
- Next Trigger: Reuse this learning whenever hook code accepts JSON from Claude/tooling before deciding whether to mutate branch state.
- Reusable Learnings:
  - command: `pytest tests/test_workflow_context_injector.py tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Hook inputs are untrusted even after JSON parsing; normalize field types before calling string-specific helpers.`
  - invariant: `Hook degradation status may update only parseable existing branch state; missing or invalid state must not be created or clobbered by a diagnostic write.`
  - review-check: `When adding a skipped/degraded hook path, test both the persisted reason and the non-blocking/no-state-mutation failure path.`

## 2026-05-16 - Auto-write run health reports from workflow closeout paths [2604.017-2]

- Decision: `implemented`
- Branch: `2604.017-2-run-health-closeout`
- Baseline: `write_run_health_report` existed and had schema/writer tests, but `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` closeout prompts did not call it, so `run_health_report.json` was optional/manual.
- Forward Change: Added closeout prompt wiring in the four workflow skills, required `RUN_HEALTH_STATUS` to be set from the final verdict before invoking the helper, synced templates, and documented automatic closeout-time report generation.
- Decisive Validation: `pytest tests/test_skills.py::TestRunHealthCloseoutWiring -v`, `pytest tests/test_template_sync.py tests/test_skills.py::TestSkillStructure::test_skill_templates_in_sync -v`, `make lint`, `pytest -m "not slow"`, and a repo-built `uv run --no-sync mapify init <new-dir> --no-git --mcp none` smoke that wrote and inspected `.map/default/run_health_report.json` passed. Read-only review found and then confirmed fixes for prompt sequencing/status-default issues.
- Validation Boundary: Unfiltered `pytest` and `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` were attempted against live Claude SDK tests, but both exceeded tool timeouts after partial progress. This slice's no-LLM artifact contract was validated directly in a generated project.
- Next Trigger: Reuse this learning whenever adding prompt-level closeout commands whose arguments depend on workflow verdicts or terminal states.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestRunHealthCloseoutWiring -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Prompt closeout snippets that write terminal artifacts must appear after the section that determines the final verdict/status.`
  - review-check: `Tests must reject both direct hard-coded happy-path arguments and variable defaults such as RUN_HEALTH_STATUS="complete" when non-happy terminal statuses are valid.`

## 2026-05-15 - Action-first tool use in lightweight workflows [2604.028]

- Decision: `implemented`
- Branch: `codex/2604-028-action-first-lightweight`
- Baseline: `map-fast` and `map-debug` asked Actor to return `code_changes` with full file content, then told the orchestrator to apply changes after validation, while `map-efficient` already used direct Actor Edit/Write behavior.
- Forward Change: Converted the lightweight Actor prompts to apply edits directly, changed Monitor prompts to read written files from the repo, removed stale post-validation apply steps, synced templates, and documented the action-first behavior.
- Decisive Validation: `pytest tests/test_skills.py::TestLightweightWorkflowSkillContracts tests/test_template_sync.py -v`, `make lint`, `pytest -m "not slow"`, and `uv run mapify init <temp-path> --no-git --mcp none` with generated-file inspection passed. Unfiltered `pytest` was attempted twice but timed out in real Claude SDK slow e2e tests.
- Next Trigger: Reuse this learning whenever changing workflow prompts that describe Actor output, Monitor validation inputs, or generated skill templates.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestLightweightWorkflowSkillContracts tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `If Actor applies edits directly, no workflow overview, decision point, or post-review step may still describe a separate apply phase.`
  - review-check: `Prompt regression tests should reject both old schema terms like code_changes and natural-language leftovers such as "Apply fix" or "ACCEPT and apply changes".`

## 2026-04-13 - Official-frontmatter hygiene for MAP skills [2604.031]

- Decision: `implemented`
- Branch: `codex/2604-031-skill-frontmatter`
- Baseline: `map-planning` shipped with a 371-character description that referenced non-existent `map-workflows-guide` and `map-cli-reference` surfaces, `map-learn` had no argument hint for manual invocation, and no test failed on those metadata regressions.
- Forward Change: Shortening the two shipped skill descriptions, adding `argument-hint: "[workflow-summary]"` to `map-learn`, and adding dedicated metadata lint tests closed the actual UX gaps without pulling the whole stale skill taxonomy into scope.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py tests/test_command_templates.py -v` passed, and `uv run mapify init <new-dir> --no-git --mcp none` generated the updated skill frontmatter in a throwaway project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/`, `src/mapify_cli/templates/skills/`, or the installer copy path and you need to prove the generated project reflects the branch state.
- Reusable Learnings:
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `When changing shipped skill metadata, keep descriptions under 250 characters and make every map-* reference resolve to a real shipped command or skill.`
  - gotcha: `The globally installed mapify binary can lag behind the branch under test and show stale templates even when the repo diff is correct.`
  - review-check: `For manual slash skills, always verify the frontmatter exposes an argument hint before shipping catalog changes.`

## 2026-05-15 - Skill trigger and invocation regression testing [2604.034]

- Decision: `implemented`
- Branch: `codex/2604-034-skill-invocation-tests`
- Baseline: `test_skills.py` validated basic skill frontmatter and sync, but did not prove `skill-rules.json` manual invocation metadata matched `SKILL.md`, did not require direct slash names in trigger rules, did not test selected negative-trigger fixtures, and did not verify relative supporting links, supporting-file template sync, or `CLAUDE_PLUGIN_ROOT` hook commands.
- Forward Change: Added those catalog integrity checks and corrected `map-learn` from suggested domain skill to manual slash skill in both development and shipped template metadata.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v` passed, `pytest -m "not slow"` passed, and `uv run mapify init <temp-dir> --no-git --mcp none` emitted manual `map-learn` metadata plus bundled rule templates in a generated project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/skill-rules.json`, skill frontmatter, hook metadata, or Markdown links to files bundled under a skill directory.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `A skill with manual slash invocation must have an argument-hint and its direct map-* name in skill-rules keywords and intent patterns.`
  - invariant: `Relative Markdown links, non-SKILL supporting files, and CLAUDE_PLUGIN_ROOT hook commands must resolve and stay synced before template release.`
  - gotcha: `When linting Markdown links in skill bodies, strip fenced code blocks first so regex snippets like [ =]([0-9]+) are not mistaken for Markdown links.`

## 2026-05-15 - Explicit reference-vs-task skill architecture [2604.032]

- Decision: `implemented`
- Branch: `codex/2604-032-skill-taxonomy`
- Baseline: The shipped skills README still said skills were passive documentation only, referenced non-existent `map-workflows-guide`, and `skill-rules.json` had no machine-readable way to distinguish task workflows from reference guidance or `map-state` hook side effects.
- Forward Change: Added `skillClass` metadata, classified MAP slash workflows as `task`, classified `map-state` as `hybrid` with `runtimeEffects`, rewrote skill taxonomy docs, removed stale skill references, and added regression tests for task/reference/hybrid boundaries.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v`, `pytest -m "not slow"`, and `make lint` passed. `uv run mapify init <new-dir> --no-git --mcp none` emitted `map-state` as `hybrid`, `map-learn` as `task`, and the generated skills README included the taxonomy.
- Next Trigger: Reuse this learning whenever a change adds, removes, or reclassifies a shipped skill, especially if it changes manual invocation, hooks, scripts, or file-writing behavior.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every shipped skill-rules.json entry must declare skillClass as reference, task, or hybrid.`
  - invariant: `Task skills must be manual slash workflows; reference skills must not hide manual invocation, hooks, or runtime effects; hybrid skills must declare runtimeEffects.`
  - gotcha: `Docs can retain stale skill names even after catalog tests pass; grep for removed/non-shipped skill names such as map-workflows-guide and map-cli-reference when changing skill taxonomy.`
## 2026-05-17 - Few-shot command examples and evidence-quoted outputs [2604.027]

- Decision: `implemented`
- Branch: `codex/2604-027-evidence-outputs`
- PR: `https://github.com/azalio/map-framework/pull/122`
- Baseline: MAP review, debug, and planning prompts asked agents for JSON verdicts, risks, root causes, and decomposition results without consistently requiring quoted evidence first. The active plan also bundled future generic JSON-contract linting with the user-visible evidence-output behavior.
- Forward Change: Shipped a compact shared evidence examples reference and wired `/map-review`, `/map-debug`, and `/map-plan` to require quotes/evidence before high-risk judgments. After review, split the broader generic JSON-contract linting ask into active follow-up `2604.027-1` instead of claiming it shipped in this PR.
- Decisive Validation: Focused prompt/template tests passed, the generated-project `mapify init` smoke emitted the new reference and prompt lines, reference template sync now has a regression, and `pytest -m "not slow"` plus `make lint` passed. Unfiltered `pytest` was attempted and timed out at the known live Claude SDK boundary after deterministic tests and the first three slow SDK tests passed.
- Next Trigger: Reuse this when changing MAP skill prompts that ask agents for JSON judgments, verdicts, risks, root causes, scores, or decomposition boundaries.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestEvidenceFirstPromptContracts tests/test_template_sync.py::TestReferenceTemplateSynchronization -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `If shipped skills link to .claude/references files, the matching src/mapify_cli/templates/references files must exist, be byte-identical, and be covered by template-sync tests.`
  - review-check: `When a plan item mixes user-visible prompt behavior with future generic lint tooling, close only the shipped behavior and leave the lint rule as a child follow-up.`
## 2026-05-18 - Claude 4.6 command simplification and verb calibration [2604.025]

- Decision: `implemented`
- Branch: `codex/2604-025-prompt-calibration`
- PR: `https://github.com/azalio/map-framework/pull/129`
- Baseline: MAP task skills still contained older prompt patterns such as `ABSOLUTELY FORBIDDEN`, `STRICTLY PROHIBITED`, `CRITICAL: ALWAYS`, and generic `YOU MUST:` blocks in non-release workflows. Anthropic's current prompt guidance says Claude 4.5/4.6-era prompts can overtrigger tools and subagents when older undertriggering workarounds remain in place.
- Forward Change: Replaced non-release blanket prohibition blocks with targeted workflow guardrails, added explicit `When Not To Expand Scope` clauses to lightweight/resume/single-subtask skills, preserved real hard stops in `/map-release`, synced templates, and added a scanner that rejects the banned blanket prohibition phrases outside release safety.
- Decisive Validation: Focused prompt-tone and template-sync tests passed, `make lint` passed, `pytest -m "not slow"` passed, and generated-project `uv run --no-sync mapify init ... --no-git --mcp none` emitted calibrated skill prompts. Full `pytest` was attempted and reached the live Claude SDK review boundary after plan/efficient live tests passed; the timed-out review boundary then passed both individually and as the full `TestMapReviewE2E` class.
- Next Trigger: Reuse this learning whenever editing `.claude/skills/map-*/SKILL.md`, shipped template skill copies, or workflow prompt wording that could affect subagent/tool triggering.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestPromptToneCalibration tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Non-release MAP task skills should use targeted guardrail wording and explicit scope off-ramps; reserve blanket all-caps prohibition blocks for irreversible release/tag safety.`
  - review-check: `When changing prompt tone, verify required workflow gates remain semantically explicit even if CRITICAL/MUST/NEVER wording is reduced.`

## 2026-05-19 - Context-first XML envelopes for slash commands [2604.026]

- Decision: `implemented`
- Branch: `codex/2604-026-xml-envelopes`
- PR: `https://github.com/azalio/map-framework/pull/131`
- Baseline: High-context MAP skills mixed persisted artifacts, user requests, workflow policy, and output schemas in ad hoc markdown inside subagent prompts. `/map-review` in particular passed the review bundle, review preferences, and git diff as inline prose, so future edits could accidentally move long artifacts below instructions or blur primary bundle context with secondary diff context.
- Forward Change: Added `.claude/references/map-xml-prompt-envelopes.md` and the shipped template copy, then applied the artifact-first envelope to `/map-plan`, `/map-efficient`, `/map-debug`, and `/map-review`. The change preserved existing MAP semantic tags such as `<MAP_Contract>` and `<map_context>` while wrapping larger prompt inputs in `<documents>` before `<task>`, `<workflow_policy>` or `<instructions>`, and `<expected_output>`.
- Decisive Validation: Focused XML envelope tests scan both `.claude/skills/` and `src/mapify_cli/templates/skills/` for the reference link and required tags. The generated-project smoke confirmed `mapify init` emits the new reference and XML tags in installed skills. `make lint`, `pytest -m "not slow"`, the timed-out live SDK boundary test, live `/map-review` E2E, and live full-flow E2E passed. Full `pytest` and full live SDK module runs both hit the 30-minute tool timeout at the same cumulative boundary, with no deterministic failure before timeout.
- Next Trigger: Reuse this learning whenever changing MAP skill prompts that pass specs, review bundles, diffs, logs, current-subtask context, or other large artifacts into subagents.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestXMLPromptEnvelopeContracts tests/test_template_sync.py::TestReferenceTemplateSynchronization -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `High-context MAP skill prompts should put long artifacts in <documents> before task/instructions/output schema and keep source/template skill copies byte-synced.`
  - gotcha: `Existing prompt contract tests may assert marker phrases such as Written Files; XML refactors must preserve those explicit markers inside the tagged document content.`
  - review-check: `When changing /map-review reviewer prompts, verify the review bundle remains the primary tagged document and raw diff remains secondary.`

## 2026-05-19 - Compile-time skill IR and anti-injection audit for provider surfaces [2605.221]

- Decision: `implemented`
- Branch: `codex/2605-221-skill-ir-audit`
- PR: `https://github.com/azalio/map-framework/pull/132`
- Baseline: MAP shipped Claude and Codex provider skills as hand-authored Markdown templates. Existing tests covered frontmatter, trigger rules, prompt tone, JSON contracts, links, and template sync, but there was no single typed representation that could parse every shipped `SKILL.md`, record content hashes, and fail unsafe provider-surface drift before `mapify init` installed the files into user repos.
- Forward Change: Added `src/mapify_cli/skill_ir.py` with a `SkillIR` dataclass, parser, audit findings, supporting-file/link validation, hidden instruction-override phrase detection, deterministic content hashes, and a CLI entry point. Added focused tests that parse all shipped Claude and Codex template skills, reject missing references, reject unsupported frontmatter, reject injection-like instructions, and verify the CLI exits non-zero on findings.
- Decisive Validation: Focused Skill IR tests passed, the audit command returned no findings for both shipped provider skill roots, focused skill/template sync regressions passed, `make lint` passed, `pytest -m "not slow"` passed, generated Claude and Codex `mapify init` smokes emitted the expected skill trees, and the full `pytest` attempt reached live review E2E before the 30-minute tool timeout; the timed-out review boundary test passed when rerun directly.
- Next Trigger: Reuse this when changing `SKILL.md` templates, adding new provider skill roots, changing supported frontmatter, or adding a future generated-skill emitter.
- Reusable Learnings:
  - command: `PYTHONPATH=src python -m mapify_cli.skill_ir src/mapify_cli/templates/skills src/mapify_cli/templates/codex/skills --format json`
  - invariant: `When changing provider skill templates, parse both Claude and Codex SKILL.md trees into SkillIR so content hashes, frontmatter shape, references, and injection-like text are validated together.`
  - gotcha: `Claude skill Markdown references can legitimately point outside the skill folder to sibling bundled references such as ../../references/*.md, so audits should allow links inside the provider bundle root rather than only inside the individual skill directory.`
  - review-check: `When adding static provider-surface audits, verify they cover generated-template roots and do not only inspect repo-local .claude skills.`

## 2026-05-20 - Budget Decision Artifact for Active Prompt Paths [2604.023-3]

- Decision: `implemented`
- Branch: `codex/2604-023-budget-artifact`
- Baseline: Actor and review prompt builders enforced deterministic budgets, but users had to inspect prompt text or transcripts to know which active prompt path clipped context and which budget to adjust.
- Forward Change: The active Actor context and `/map-review` prompt builders now append compact decisions to `.map/<branch>/token_budget.json` and record a `token_budget` manifest stage, while docs explain how operators use the report to continue, raise a budget, or split a workflow.
- Decisive Validation: Focused Actor/review prompt tests assert token-budget decisions, clipped sections, and manifest stage updates. A generated-project smoke ran installed `.map/scripts/map_step_runner.py build_context_block` and `build_review_prompts --branch default --budget-tokens 1500` against real branch artifacts plus a real git diff, then inspected `.map/default/token_budget.json` for all four active prompt-path decisions.
- Next Trigger: Reuse this learning whenever a MAP prompt path clips context, adds a new budgeted prompt builder, or needs an operator-facing diagnostic artifact for a current workflow decision.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py build_review_prompts --branch <branch> --budget-tokens <n> --review-preferences "..."`
  - invariant: `Only active prompt builders that already enforce budgets should write token_budget.json decisions; do not add telemetry for dormant context mechanisms before activation evidence exists.`
  - gotcha: `Generated-project review prompt smokes should pass --branch when the desired .map branch differs from git's current branch name.`
  - review-check: `When adding prompt-budget artifacts, verify the artifact names clipped sections and source artifacts, not only before/after token counts.`
## 2026-05-20 - Compact high-traffic workflow playbooks [2604.033-2]

- Decision: `implemented`
- Branch: `codex/2604-033-2-compact-playbooks`
- PR: `https://github.com/azalio/map-framework/pull/138`
- Baseline: The high-traffic workflow skills `/map-plan`, `/map-efficient`, `/map-check`, and `/map-review` each carried hundreds of lines of active instructions, examples, troubleshooting, and low-frequency reference material. Official Claude Code skill docs say invoked `SKILL.md` content stays in context and compaction reattaches recent skill invocations within a limited budget, so large active bodies increase recurring context cost for the workflows users run most.
- Forward Change: Moved low-frequency examples, troubleshooting, detailed rationale, command matrices, wave details, and section rubrics into bundled supporting files while keeping mandatory next-action flow, state-machine commands, output contracts, run-health closeout, review bundle wiring, and handoff flows in each active `SKILL.md`.
- Decisive Validation: Focused skill/template tests passed, generated-project smoke confirmed installed high-traffic skills were <=500 lines and included supporting references, `make lint` passed, `pytest -m "not slow"` passed, and Skill IR audit found no provider-surface findings.
- Next Trigger: Reuse this when a task skill used in normal workflows grows beyond 500 lines, or when examples/troubleshooting/rationale start living in invoked `SKILL.md` instead of supporting files.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestSkillStructure::test_high_traffic_workflow_skills_keep_active_bodies_compact tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `High-traffic workflow SKILL.md files should keep active next-action flow under 500 lines and link bundled supporting files for examples/troubleshooting/reference material.`
  - review-check: `When compacting task skills, verify source and template SKILL.md files still preserve state-machine commands, output contracts, closeout artifact writes, and prompt-contract markers before moving detail into references.`
  - gotcha: `Tests that assert a command appears before first Task( can fail if prose mentions Task( earlier than the real launch; keep literal launch markers out of preflight prose.`

## 2026-05-20 - Constraint-first provider rule templates [2604.040]

- Decision: `implemented`
- Branch: `codex/2604-040-constraint-provider-rules`
- Baseline: The active plan identified that generated provider rules lacked a structural guardrail against broad positive write directives. Claude write-capable surfaces already had scattered scope wording, but there was no uniform installed-project constraint that blocked unrelated edits, dependency churn, or neighboring refactors at mutation boundaries.
- Forward Change: Added `Mutation Boundary Constraints` to the Actor agent, `/map-fast`, `/map-efficient`, `/map-task`, `/map-debug`, `.codex/AGENTS.md`, and Codex `$map-fast`, then synced the shipped templates. The constraints require agents to report dependency changes, broad refactors, or scope expansion as blockers/tradeoffs instead of doing them silently.
- Decisive Validation: Focused prompt regression tests now scan source and shipped Claude/Codex provider surfaces for the mutation-boundary section and required unrelated-file/dependency/refactor/blocker phrases. Generated-project smokes inspected installed `.claude/` files, root `AGENTS.md` for Codex, and `.codex/skills/map-fast/SKILL.md`.
- Validation Boundary: `pytest` and `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` were both attempted and exceeded the 30-minute tool timeout without a deterministic failure message. Deterministic validation passed via `make lint`, `pytest -m "not slow"`, focused skill/template tests, no-LLM e2e artifact tests, Skill IR audit, and generated-project smokes.
- Next Trigger: Reuse this when adding a write-capable provider surface, changing Actor/fix prompts, or introducing any prompt that says to apply edits directly.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestSkillStructure::test_write_capable_claude_surfaces_have_constraint_first_boundaries tests/test_skills.py::TestSkillStructure::test_write_capable_codex_surfaces_have_mutation_boundaries -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every write-capable provider surface should include Mutation Boundary Constraints that block unrelated edits, dependency changes, and neighboring refactors unless the current contract explicitly requires them.`
  - review-check: `When a prompt says Actor/fix/apply_patch should edit files directly, verify the same prompt or its enclosing skill tells the agent to report required scope expansion as a blocker/tradeoff.`
## 2026-05-20 - Clean-room retry and context quarantine [2605.08563]

- Decision: `implemented`
- Branch: `codex/2605-08563-clean-retry`
- PR: `pending`
- Baseline: Repeated Monitor failures fed feedback back into Actor without a clean-room context boundary, so rejected approaches could carry forward while run health only exposed retry counts.
- Forward Change: Repeated Monitor rejection now writes `retry_quarantine.json`, marks `clean_retry_required` in step state, validates the quarantine artifact, surfaces clean/ordinary retry counters in `run_health_report.json`, and tells resume/Actor prompts not to rehydrate raw failed context.
- Decisive Validation: Focused retry/schema/template tests passed; generated-project smoke exercised installed `map_orchestrator.py` and `map_step_runner.py`, validated `retry_quarantine.json`, wrote `run_health_report.json`, and inspected `clean_retry_count` plus retry-quarantine artifact presence.
- Next Trigger: Read these learnings before changing Actor->Monitor retry logic, run-health retry signals, resume diagnostics, or workflow prompts that describe retries after validation failure.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_retry_quarantine`
  - invariant: `After the second Monitor rejection for a subtask, the next Actor attempt must use clean retry context from retry_quarantine.json instead of raw failed-session context.`
  - review-check: `When adding retry isolation fields, verify step_state.json, retry_quarantine.json, run_health_report.json, shipped skills, templates, schemas, and resume briefing stay aligned.`
