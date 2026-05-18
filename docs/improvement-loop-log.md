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
